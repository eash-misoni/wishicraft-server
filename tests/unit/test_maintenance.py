from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any, cast

import pytest
from aws_cdk import App, Stack
from aws_cdk.assertions import Template
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

from infrastructure.app import build_app
from tests.unit.test_monitoring import THRESHOLDS, snapshot
from tests.unit.test_monitoring_infrastructure import ROOT
from tests.unit.test_monitoring_telemetry import INSTANCE, NOW, inputs
from tests.unit.test_operation import FakeDynamo, repository, request
from wishicraft.maintenance import lease_active, maintenance_metrics, new_lease
from wishicraft.maintenance_operator import safe_state
from wishicraft.maintenance_repository import transition
from wishicraft.monitoring import evaluate_monitoring_snapshot
from wishicraft.monitoring_telemetry import evaluate_telemetry
from wishicraft.operation import OperationType


def lease() -> dict[str, Any]:
    return new_lease(
        lease_id="maint-test",
        actor="synthetic-operator",
        reason="host-migration",
        stage="dev",
        duration=3600,
        now=NOW,
    )


def planned() -> dict[str, Any]:
    values = inputs()
    state = values["state"]
    state.update(
        maintenance=lease(),
        desired_state="STOPPED",
        health="DEGRADED",
        discrepancies=["dns-missing-when-required"],
    )
    state["observation"].update(
        instance_id=INSTANCE,
        ec2_state="running",
        runtime_ready=False,
        dns_state="absent",
        container_state="not-found",
        host_runtime_state="not-running",
        minecraft_service_state="not-running",
        minecraft_protocol_state="not-applicable",
        observed_active_game_id=None,
        ssm_state="online",
        docker_state="active",
        mount_state="expected",
    )
    values["heartbeat"].update(active_game_id=None, protocol_state="unknown", player_count=None)
    return values


def metrics(values: dict[str, Any]) -> dict[str, float]:
    return maintenance_metrics(
        **{k: values[k] for k in ("state", "lock", "instance", "now")}, freshness_seconds=600
    )


@pytest.mark.parametrize(
    "elapsed,active", [(0, True), (3599, True), (3600, False), (3601, False), (-1, False)]
)
def test_expiry_is_application_time_not_dynamodb_ttl(elapsed: int, active: bool) -> None:
    value = lease()
    assert lease_active(value, now=NOW + timedelta(seconds=elapsed)) is active
    assert "expires_at" in value  # Expired records remain intact and auditable.


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"status": "ACTIVE"},
        {**lease(), "expires_at": "tomorrow"},
        {**lease(), "status": "INCIDENT"},
    ],
)
def test_malformed_or_incident_lease_cannot_suppress(value: Any) -> None:
    assert not lease_active(value, now=NOW)


def test_base_metrics_remain_abnormal_before_during_and_after_maintenance() -> None:
    values = planned()
    base = evaluate_monitoring_snapshot(
        snapshot(actual_ec2_state="running"), now=NOW, thresholds=THRESHOLDS
    )
    runtime, _ = evaluate_telemetry(**values)
    assert base["DesiredStoppedEc2Running"] == base["DesiredActualDivergence"] == 1
    assert runtime["RuntimeObservationUnknown"] == 1
    assert metrics(values) == {
        "MaintenanceActive": 1,
        "MaintenanceSuppressionEligible": 1,
        "MaintenanceExpiresAt": lease()["expires_at"],
    }
    before = deepcopy(values["state"])
    values["now"] = NOW + timedelta(hours=1)
    assert metrics(values) == {
        "MaintenanceActive": 0,
        "MaintenanceSuppressionEligible": 0,
        "MaintenanceExpiresAt": 0,
    }
    assert values["state"] == before
    del values["state"]["maintenance"]
    assert metrics(values) == {
        "MaintenanceActive": 0,
        "MaintenanceSuppressionEligible": 0,
        "MaintenanceExpiresAt": 0,
    }
    assert (
        evaluate_monitoring_snapshot(
            snapshot(actual_ec2_state="running"), now=NOW, thresholds=THRESHOLDS
        )
        == base
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_state", "running"),
        ("container_state", "unknown"),
        ("container_state", "stopped"),
        ("runtime_ready", True),
        ("dns_state", "present"),
        ("ssm_state", "unknown"),
        ("mount_state", "mismatch"),
        ("docker_state", "failed"),
        ("instance_id", "wrong"),
        ("observed_active_game_id", "game-unexpected"),
    ],
)
def test_unknown_or_unexpected_host_never_suppresses(field: str, value: Any) -> None:
    values = planned()
    values["state"]["observation"][field] = value
    assert metrics(values) == {
        "MaintenanceActive": 1,
        "MaintenanceSuppressionEligible": 0,
        "MaintenanceExpiresAt": lease()["expires_at"],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("desired_state", "RUNNING"),
        ("current_operation_id", "op-foreign"),
        ("observation_errors", ["SSM_OBSERVATION_FAILED"]),
        ("health", "UNKNOWN"),
        ("discrepancies", ["runtime-state-mismatch"]),
        ("observed_at", (NOW - timedelta(minutes=11)).isoformat()),
    ],
)
def test_unexpected_control_state_never_suppresses(field: str, value: Any) -> None:
    values = planned()
    values["state"][field] = value
    assert metrics(values)["MaintenanceSuppressionEligible"] == 0


def test_stopped_preflight_and_closeout() -> None:
    values = planned()
    state = values["state"]
    state.update(health="HEALTHY", discrepancies=[])
    state["observation"]["ec2_state"] = "stopped"
    values["instance"]["State"]["Name"] = "stopped"
    safe_state(state, instance_id=INSTANCE, actual="stopped", now=NOW)
    assert metrics(values)["MaintenanceSuppressionEligible"] == 1
    state["maintenance"].update(status="ENDED", ended_at=int(NOW.timestamp()))
    assert metrics(values)["MaintenanceSuppressionEligible"] == 0
    assert state["health"] == "HEALTHY" and state["desired_state"] == "STOPPED"
    with pytest.raises(ValueError):
        safe_state(state, instance_id=INSTANCE, actual="running", now=NOW)


def test_begin_and_end_are_atomic_with_immutable_audit_and_no_lock() -> None:
    api = FakeDynamo()
    state = planned()["state"]
    del state["maintenance"]
    kwargs = dict(
        table="state",
        locks_table="locks",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
        state=state,
        now=NOW,
    )
    transition(api, lease=lease(), event="begin", **kwargs)
    tx: Any = api.transactions[-1]["TransactItems"]
    assert len(tx) == 3
    assert "observed_at = :observed" in tx[0]["Update"]["ConditionExpression"]
    assert "maintenance.#ms = :maintenance_ended" in tx[0]["Update"]["ConditionExpression"]
    assert tx[1]["Put"]["ConditionExpression"] == "attribute_not_exists(system_id)"
    assert tx[2]["ConditionCheck"]["ConditionExpression"] == "attribute_not_exists(lock_name)"
    state["maintenance"] = lease()
    for now in (NOW, NOW + timedelta(hours=2)):
        with pytest.raises(ValueError, match="already open"):
            transition(api, lease=lease(), event="begin", **{**kwargs, "now": now})
    ended = {**lease(), "status": "ENDED", "ended_at": int(NOW.timestamp())}
    transition(api, lease=ended, event="end", **kwargs)
    tx = api.transactions[-1]["TransactItems"]
    assert "maintenance = :previous" in tx[0]["Update"]["ConditionExpression"]
    assert (
        TypeDeserializer().deserialize(tx[0]["Update"]["ExpressionAttributeValues"][":lease"])
        == ended
    )


def test_incident_resumes_notifications_without_claiming_safe_closeout() -> None:
    api = FakeDynamo()
    state = planned()["state"]
    incident = {**lease(), "status": "INCIDENT", "incident_at": int(NOW.timestamp())}
    transition(
        api,
        table="state",
        locks_table="locks",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
        state=state,
        lease=incident,
        event="incident",
        now=NOW,
    )
    assert len(cast(list[Any], api.transactions[-1]["TransactItems"])) == 2
    assert not lease_active(incident, now=NOW)


@pytest.mark.parametrize(
    "kind",
    [
        OperationType.START,
        OperationType.STOP,
        OperationType.SWITCH,
        OperationType.RESET,
        OperationType.BACKUP,
        OperationType.RETENTION,
    ],
)
def test_all_workflow_admissions_share_atomic_maintenance_fence(kind: OperationType) -> None:
    api = FakeDynamo()
    repo = repository(api)
    tx: Any = repo._ownership_transaction(request(kind), "lease-test")
    update = tx[-1]["Update"]
    assert "maintenance.#ms = :maintenance_ended" in update["ConditionExpression"]
    assert "expires_at" not in update["ConditionExpression"]  # Expiry does not reopen START.
    assert update["ExpressionAttributeNames"]["#ms"] == "status"
    assert update["ExpressionAttributeValues"][":maintenance_ended"] == {"S": "ENDED"}


@pytest.mark.parametrize("mode", ["prepare", "active"])
def test_alarm_actions_are_one_to_one_and_only_three_are_suppressed(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import infrastructure.app as app_module

    monkeypatch.setattr(
        app_module, "App", lambda: App(context={"maintenance_notification_mode": mode})
    )
    app = build_app(ROOT, "dev", phase=8, deployment="control-plane")
    template = Template.from_stack(
        cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    ).to_json()
    resources = template["Resources"]
    base = {
        k: v["Properties"] for k, v in resources.items() if v["Type"] == "AWS::CloudWatch::Alarm"
    }
    composites = [
        v["Properties"]
        for v in resources.values()
        if v["Type"] == "AWS::CloudWatch::CompositeAlarm"
    ]
    assert len(composites) == 3
    eligible = {"DesiredStoppedEc2Running", "RuntimeObservationUnknown", "DesiredActualDivergence"}
    for logical, alarm in base.items():
        if alarm.get("MetricName") in eligible:
            assert bool(alarm.get("AlarmActions")) == (mode == "prepare")
            matching = [c for c in composites if logical in str(c["AlarmRule"])]
            assert len(matching) == 1
            assert matching[0]["AlarmActions"] == next(
                a["AlarmActions"] for a in base.values() if a.get("MetricName") == "Errors"
            )
            assert matching[0]["ActionsSuppressorWaitPeriod"] == 0
            assert matching[0]["ActionsSuppressorExtensionPeriod"] == 0
        elif "MaintenanceSuppressor" in logical:
            assert not alarm.get("AlarmActions")
            assert alarm["TreatMissingData"] == "notBreaching"
            assert alarm["Metrics"][0]["Expression"] == (
                "IF((FILL(eligible, 0) >= 1) AND (EPOCH(eligible) + 600 < FILL(expiry, 0)), 1, 0)"
            )
        else:
            assert alarm["AlarmActions"], logical
    dlqs = [v for v in base.values() if v.get("Namespace") == "AWS/SQS"]
    assert not dlqs  # Existing monitoring gap is explicitly deferred by the operator.


@pytest.mark.parametrize(
    "status,allowed", [("ACTIVE", False), ("INCIDENT", False), ("ENDED", True)]
)
def test_real_start_admission_blocks_unclosed_expired_lease(status: str, allowed: bool) -> None:
    from web.local_operations import MemoryDynamo, service
    from wishicraft.operation import AdmissionConflict, RequestSource

    db = MemoryDynamo()
    db.records["system", "local"] = {
        "system_id": {"S": "local"},
        "maintenance": {"M": {"status": {"S": status}, "expires_at": {"N": "0"}}},
    }
    db.records["games", "game-demo-one"] = {
        "game_id": {"S": "game-demo-one"},
        "lifecycle_state": {"S": "ACTIVE"},
    }
    before = deepcopy(db.records)
    arguments = dict(
        operation_type=OperationType.START,
        idempotency_key="test-maintenance-start",
        requested_by=RequestSource.CLI,
        requested_at=NOW,
    )
    if allowed:
        assert service(db).admit(**arguments).created  # type: ignore[arg-type]
    else:
        with pytest.raises(AdmissionConflict):
            service(db).admit(**arguments)  # type: ignore[arg-type]
        assert db.records == before and db.transactions == 0


@pytest.mark.parametrize("change", [None, "unexpected-game", "stale", "identity", "filesystem"])
def test_actual_observer_keeps_base_flags_and_rejects_unexpected_heartbeat(
    monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    from tests.unit.test_monitoring_telemetry import setup_handler
    from wishicraft import monitoring_lambda

    aws = setup_handler(monkeypatch)
    aws.values = planned()
    if change == "unexpected-game":
        aws.values["heartbeat"]["active_game_id"] = "game-vanilla-main"
    elif change == "stale":
        aws.values["heartbeat"]["observed_at"] = (NOW - timedelta(minutes=6)).isoformat()
    elif change == "identity":
        aws.values["heartbeat"]["instance_id"] = "i-foreign"
    elif change == "filesystem":
        aws.values["state"]["observation"]["telemetry"]["state"] = "unknown"
    monitoring_lambda.handler({}, None)
    emitted = {m["MetricName"]: m["Value"] for m in aws.published[-1]["MetricData"]}
    assert emitted["DesiredStoppedEc2Running"] == 1
    assert emitted["DesiredActualDivergence"] == 1
    assert emitted["RuntimeObservationUnknown"] == 1
    assert emitted["MaintenanceActive"] == 1
    assert emitted["MaintenanceSuppressionEligible"] == (change is None)


@pytest.mark.parametrize(
    "field,value",
    [
        ("health", "DEGRADED"),
        ("desired_state", "RUNNING"),
        ("current_operation_id", "op-active"),
        ("observation_errors", ["SSM_FAILED"]),
        ("discrepancies", ["dns-present-while-endpoint-should-be-absent"]),
        ("observed_at", (NOW - timedelta(minutes=3)).isoformat()),
    ],
)
def test_operator_refuses_invalid_stopped_preflight(field: str, value: Any) -> None:
    state = planned()["state"]
    state.update(health="HEALTHY", discrepancies=[])
    state["observation"]["ec2_state"] = "stopped"
    state[field] = value
    with pytest.raises(ValueError, match="fresh STOPPED"):
        safe_state(state, instance_id=INSTANCE, actual="stopped", now=NOW)


@pytest.mark.parametrize("blocked", [None, "workflow", "command", "session", "no-machines"])
def test_operator_checks_paginated_workflow_and_ssm_preconditions(blocked: str | None) -> None:
    from wishicraft.maintenance_operator import no_external_work

    class Api:
        def client(self, service_name: str) -> Api:
            return self

        def get_paginator(self, operation: str) -> Any:
            class Pages:
                def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
                    if operation == "list_stack_resources":
                        return [
                            {"StackResourceSummaries": []},
                            {
                                "StackResourceSummaries": []
                                if blocked == "no-machines"
                                else [
                                    {
                                        "ResourceType": "AWS::StepFunctions::StateMachine",
                                        "PhysicalResourceId": "synthetic-machine",
                                    }
                                ]
                            },
                        ]
                    if operation == "list_executions":
                        assert kwargs["statusFilter"] == "RUNNING"
                        return [
                            {"executions": []},
                            {"executions": ["active"] if blocked == "workflow" else []},
                        ]
                    if operation == "list_commands":
                        assert kwargs["InstanceId"] == INSTANCE
                        return [
                            {"Commands": []},
                            {
                                "Commands": [
                                    {"Status": "Pending" if blocked == "command" else "Success"}
                                ]
                            },
                        ]
                    assert operation == "describe_sessions" and kwargs["State"] == "Active"
                    return [
                        {"Sessions": []},
                        {"Sessions": ["active"] if blocked == "session" else []},
                    ]

            return Pages()

    if blocked:
        with pytest.raises(ValueError):
            no_external_work(Api(), stack="synthetic-stack", instance_id=INSTANCE)
    else:
        no_external_work(Api(), stack="synthetic-stack", instance_id=INSTANCE)
