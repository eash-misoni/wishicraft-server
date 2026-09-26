from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from tests.unit.test_daily_backup import ApplyingStore, Store, environment, repo
from tests.unit.test_daily_backup_domain import NOW, VOLUME
from wishicraft import admission_lambda as admission
from wishicraft import daily_backup as domain
from wishicraft import daily_backup_lambda as task
from wishicraft.operation import OperationAdmissionService, OperationType
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.system_state import utc_timestamp

# Reuse the established handler environment fixture without changing its scope.
__all__ = ["environment"]


def metrics(api: Store) -> dict[str, int]:
    return {m["MetricName"]: m["Value"] for m in api.metrics[-1]["MetricData"]}


@pytest.mark.parametrize(
    "history",
    [
        None,
        {},
        {"operation_type": "STOP", "status": "FAILED"},
        {"operation_type": "START", "status": "SUCCEEDED"},
    ],
)
def test_missing_normal_stop_notifies_without_inventing_stop_time(
    environment: None, history: dict[str, str] | None
) -> None:
    api = Store()
    del api.state["backup_protection"]
    if history is not None:
        api.state["last_operation_id"] = "op-historical"
        api.operations["op-historical"] = history
    api.state["last_backup_at"] = utc_timestamp(NOW)
    for seconds in (0, 1800, 86399, 86400):
        now = NOW + timedelta(seconds=seconds)
        api.state["observed_at"] = utc_timestamp(now)
        result = task.evaluate(api, api, api, api, now=now)
        assert result["reason"] == "NORMAL_STOP_REQUIRED" and result["needs_operator"]
        assert metrics(api) == {
            "DailyBackupHeartbeat": 1,
            "DailyBackupNeedsOperator": 1,
            "DailyBackupStoppedOverdue": 0,
            "DailyBackupIntervalOverdue": int(seconds >= 86400),
            "DailyBackupObservationUnknown": 0,
        }
        p = api.state["backup_protection"]
        assert p["stopped_at"] is None and p["protected_boundary"] == 0
        assert p["unknown_since"] == utc_timestamp(NOW)
        assert not api.invocations


def test_disabled_then_enabled_missing_stop_preserves_unknown_interval(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = Store()
    del api.state["backup_protection"]
    monkeypatch.setenv("DAILY_BACKUP_ENABLED", "0")
    result = task.evaluate(api, api, api, api, now=NOW)
    assert result["reason"] == "DISABLED" and not result["needs_operator"]
    assert metrics(api)["DailyBackupNeedsOperator"] == 0 and not api.invocations
    now = NOW + timedelta(days=1)
    api.state["observed_at"] = utc_timestamp(now)
    result = task.evaluate(api, api, api, api, now=now)
    assert not result["interval_warning"] and metrics(api)["DailyBackupIntervalOverdue"] == 0
    monkeypatch.setenv("DAILY_BACKUP_ENABLED", "1")
    result = task.evaluate(api, api, api, api, now=now)
    assert result["reason"] == "NORMAL_STOP_REQUIRED" and result["needs_operator"]
    assert metrics(api)["DailyBackupNeedsOperator"] == 1
    assert metrics(api)["DailyBackupIntervalOverdue"] == 1
    assert api.state["backup_protection"]["unknown_since"] == utc_timestamp(NOW)
    assert api.state["backup_protection"]["stopped_at"] is None


@pytest.mark.parametrize("bootstrap", [False, True])
def test_normal_stop_clears_intervention_but_not_unprotected_warning(
    environment: None, bootstrap: bool
) -> None:
    api = Store()
    if bootstrap:
        del api.state["backup_protection"]
        api.state["last_operation_id"] = "op-stop"
        api.operations["op-stop"] = {"operation_type": "STOP", "status": "SUCCEEDED"}
    else:
        api.state["backup_protection"] = domain.stopped(domain.initial(VOLUME, NOW), NOW)
    for seconds in (0, 1800, 86400):
        now = NOW + timedelta(seconds=seconds)
        api.state["observed_at"] = utc_timestamp(now)
        result = task.evaluate(api, api, api, api, now=now)
        assert result["reason"] == "AVAILABLE" and not result["needs_operator"]
        assert metrics(api)["DailyBackupNeedsOperator"] == 0
        assert metrics(api)["DailyBackupStoppedOverdue"] == int(seconds >= 1800)
        assert metrics(api)["DailyBackupIntervalOverdue"] == int(seconds >= 86400)
        assert api.state["backup_protection"]["stopped_at"] == utc_timestamp(NOW)
        assert result["admission"]["outcome"] == "CONFLICT"


@pytest.mark.parametrize("reason", ["RUNNING", "MAINTENANCE", "OTHER_OPERATION", "SAFE_RETRY"])
def test_normal_wait_and_safe_retry_do_not_require_operator(
    environment: None, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    api = Store()
    p = api.state["backup_protection"]
    p["unknown_since"] = utc_timestamp(NOW - timedelta(days=1))
    if reason == "RUNNING":
        api.state["desired_state"] = "RUNNING"
        p["stopped_at"] = None
        monkeypatch.setattr(
            api,
            "describe_instances",
            lambda **kw: {
                "Reservations": [
                    {"Instances": [{"InstanceId": "i-test", "State": {"Name": "running"}}]}
                ]
            },
        )
    elif reason == "MAINTENANCE":
        api.state["maintenance"] = {"status": "ACTIVE"}
    elif reason == "OTHER_OPERATION":
        api.state["current_operation_id"] = "op-other"
    else:
        p["attempts"] = 1
        p["intent"] = {"status": "FAILED", "safe_retry": True, "finished_at": utc_timestamp(NOW)}
    result = task.evaluate(api, api, api, api, now=NOW)
    assert result["reason"] == ("FAILED" if reason == "SAFE_RETRY" else reason)
    assert not result["needs_operator"] and metrics(api)["DailyBackupNeedsOperator"] == 0
    assert metrics(api)["DailyBackupIntervalOverdue"] == 1
    assert not api.invocations


@pytest.mark.parametrize(
    "safe,attempts,needed", [(True, 1, False), (True, 2, False), (True, 3, True), (False, 1, True)]
)
def test_failed_status_and_intervention_metric_agree(
    environment: None, safe: bool, attempts: int, needed: bool
) -> None:
    api = Store()
    p = api.state["backup_protection"]
    p["attempts"] = attempts
    p["intent"] = {"status": "FAILED", "safe_retry": safe, "finished_at": utc_timestamp(NOW)}
    result = task.evaluate(api, api, api, api, now=NOW)
    assert result["reason"] == "FAILED" and result["needs_operator"] is needed
    assert metrics(api)["DailyBackupNeedsOperator"] == int(needed)
    assert not api.invocations


@pytest.mark.parametrize("failure", ["response_lost", "already_exists"])
def test_real_launcher_reconciles_same_backup_execution_after_start_error(
    environment: None, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    machine = "arn:aws:states:ap-northeast-1:385526546525:stateMachine:wc-dev-backup"
    execution = "arn:aws:states:ap-northeast-1:385526546525:execution:wc-dev-backup:op-test"
    monkeypatch.setenv("BACKUP_STATE_MACHINE_ARN", machine)

    class ExecutionStore(ApplyingStore):
        def update_item(self, **kw: Any) -> dict[str, Any]:
            assert kw["TableName"] == "operations"
            assert kw["Key"] == {"operation_id": {"S": "op-test"}}
            assert kw["ExpressionAttributeValues"][":arn"] == {"S": execution}
            self.updates.append(kw)
            self.operations["op-test"]["workflow_execution_arn"] = execution
            return {}

    api = ExecutionStore()
    service = OperationAdmissionService(
        repo(api),
        game_id="game-a",
        timeout_seconds={OperationType.BACKUP: 900},
        operation_id_factory=lambda: "op-test",
    )
    monkeypatch.setattr(admission, "_get_service", lambda: service)
    monkeypatch.setattr(
        "wishicraft.runtime_catalog.configured_catalog",
        lambda: RuntimeCatalog(("game-a", "game-b")),
    )

    class Clock:
        @staticmethod
        def now(zone: object) -> datetime:
            return NOW

    class Sdk:
        def client(self, name: str) -> Store:
            return api

    class StepFunctions:
        starts: list[dict[str, Any]] = []
        describes: list[dict[str, Any]] = []

        def start_execution(self, **kw: Any) -> object:
            self.starts.append(kw)
            if failure == "response_lost":
                raise TimeoutError("response lost after execution accepted")
            raise ClientError({"Error": {"Code": "ExecutionAlreadyExists"}}, "StartExecution")

        def describe_execution(self, **kw: Any) -> object:
            self.describes.append(kw)
            assert kw == {"executionArn": execution}
            return {"executionArn": execution, "status": "RUNNING"}

    sfn = StepFunctions()
    launcher = admission.WorkflowLauncher(
        sfn, api, state_machine_environment="BACKUP_STATE_MACHINE_ARN"
    )
    monkeypatch.setattr(admission, "_get_backup_launcher", lambda: launcher)
    monkeypatch.setattr(task, "datetime", Clock)
    monkeypatch.setattr(task, "clients", Sdk)
    event = {"schema_version": 1, "boundary": 1}
    assert task.admit(event, None) == {"outcome": "ADMITTED", "operation_id": "op-test"}
    api.idempotency.clear()
    api.state["desired_game_id"] = "game-b"
    assert task.admit(event, None) == {"outcome": "EXISTING", "operation_id": "op-test"}
    assert (
        len(api.transactions) == len(api.operations) == len(sfn.starts) == len(sfn.describes) == 1
    )
    assert sfn.starts[0]["stateMachineArn"] == machine and sfn.starts[0]["name"] == "op-test"
    assert api.state["backup_protection"]["intent"]["status"] == "ADMITTED"
    assert api.lock["owner_operation_id"] == "op-test"
