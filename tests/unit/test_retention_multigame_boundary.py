"""Synthesized config -> real admission/serialization/Reconcile/RETENTION handler."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template
from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]

from infrastructure.app import build_app
from tests.unit.test_backup_provenance import record
from tests.unit.test_reconcile import Factory, target_status
from wishicraft import reconcile_lambda
from wishicraft import retention_workflow_lambda as task
from wishicraft.backup_provenance import BackupProvenanceRepository
from wishicraft.backup_recovery import shared_tags
from wishicraft.operation import (
    AdmissionConflict,
    OperationAdmissionRepository,
    OperationRequest,
    OperationType,
    RequestSource,
)
from wishicraft.retention import plan_retention
from wishicraft.status import Ec2State, PublicIpv4State

ROOT = Path(__file__).resolve().parents[2]
A, B = "game-vanilla-main", "game-vanilla-secondary"
INSTANCE = "i-04fc0629dc4ea466e"


def wire(value: dict[str, Any]) -> dict[str, Any]:
    return {k: TypeSerializer().serialize(v) for k, v in value.items()}


@pytest.fixture(scope="module")
def configuration() -> dict[str, Any]:
    app = build_app(ROOT, "dev", phase=8, deployment="control-plane", two_games=True)
    return cast(
        dict[str, Any],
        Template.from_stack(
            cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
        ).to_json()["Resources"],
    )


class Api:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.running = False
        self.selected = A
        self.reads: list[dict[str, Any]] = []
        self.transactions: list[list[dict[str, Any]]] = []
        self.inventory: list[dict[str, Any]] = []
        self.provenance: list[dict[str, Any]] = []
        self.volume = "vol-03ac9f534326c345c"
        self.attachment = INSTANCE
        self.clock = datetime.now(UTC)
        self.snapshot_calls = 0
        self.updates: list[dict[str, Any]] = []
        self.registered_games = {A, B}

    def get_item(self, **kw: Any) -> dict[str, Any]:
        assert kw["ConsistentRead"]
        self.reads.append(kw)
        key = next(iter(kw["Key"].values()))["S"]
        item = self.items.get((kw["TableName"], key))
        return {"Item": item} if item is not None else {}

    def update_item(self, **kw: Any) -> dict[str, Any]:
        # Reconcile/step writes are captured at their real serializer boundary.
        self.updates.append(kw)
        return {}

    def transact_write_items(self, **kw: Any) -> dict[str, Any]:
        writes = kw["TransactItems"]
        # Assert ownership conditions before applying a terminalization fixture.
        for entry in writes:
            if "ConditionCheck" in entry:
                check = entry["ConditionCheck"]
                game = check["Key"]["game_id"]["S"]
                assert "lifecycle_state = :active" in check["ConditionExpression"]
                if game not in self.registered_games:
                    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

                    raise ClientError(
                        {"Error": {"Code": "TransactionCanceledException"}},
                        "TransactWriteItems",
                    )
            if "Delete" in entry:
                delete = entry["Delete"]
                values = delete["ExpressionAttributeValues"]
                lock = self.items[(delete["TableName"], delete["Key"]["lock_name"]["S"])]
                assert lock["owner_operation_id"] == values[":operation_id"]
                assert lock["lease_id"] == values[":lease_id"]
                assert "lease_expires_at >= :now" in delete["ConditionExpression"]
        self.transactions.append(writes)
        for entry in writes:
            if "Put" in entry:
                put = entry["Put"]
                item = put["Item"]
                key = next(
                    item[k]["S"]
                    for k in ("idempotency_key", "operation_id", "lock_name")
                    if k in item
                )
                # Operation contains idempotency_key too: its table key remains operation_id.
                if put["TableName"].endswith("operations"):
                    key = item["operation_id"]["S"]
                self.items[(put["TableName"], key)] = item
            elif "Delete" in entry:
                delete = entry["Delete"]
                del self.items[(delete["TableName"], delete["Key"]["lock_name"]["S"])]
            elif "Update" in entry:
                update = entry["Update"]
                values = update["ExpressionAttributeValues"]
                key = next(iter(update["Key"].values()))["S"]
                item = self.items[(update["TableName"], key)]
                if ":status" in values:
                    item["status"] = values[":status"]
                    item["result"] = values[":result"]
                elif ":operation_id" in values:
                    if update["UpdateExpression"].startswith("REMOVE"):
                        assert item["current_operation_id"] == values[":operation_id"]
                        item.pop("current_operation_id")
                    else:
                        item["current_operation_id"] = values[":operation_id"]
        return {}

    def scan(self, **kw: Any) -> dict[str, Any]:
        return {"Items": self.provenance}

    def describe_volumes(self, **kw: Any) -> dict[str, Any]:
        return {
            "Volumes": [
                {
                    "VolumeId": self.volume,
                    "AvailabilityZone": "ap-northeast-1a",
                    "Encrypted": True,
                    "Attachments": [
                        {
                            "InstanceId": self.attachment,
                            "Device": "/dev/sdf",
                            "State": "attached",
                            "DeleteOnTermination": False,
                        }
                    ],
                }
            ]
        }

    def describe_instances(self, **kw: Any) -> dict[str, Any]:
        assert "Filters" in kw
        return {"Reservations": [{"Instances": [{"InstanceId": INSTANCE}]}]}

    def describe_snapshots(self, **kw: Any) -> dict[str, Any]:
        self.snapshot_calls += 1
        assert kw["OwnerIds"] == ["385526546525"]
        return {"Snapshots": self.inventory}

    def describe_locked_snapshots(self, **kw: Any) -> dict[str, Any]:
        return {"Snapshots": []}

    def list_rules(self, **kw: Any) -> dict[str, Any]:
        return {"Rules": []}

    def list_resource_record_sets(self, **kw: Any) -> dict[str, Any]:
        return {
            "ResourceRecordSets": (
                [
                    {
                        "Name": "mc-dev.wishicraft.net.",
                        "Type": "A",
                        "TTL": 60,
                        "ResourceRecords": [{"Value": "192.0.2.1"}],
                    }
                ]
                if self.running
                else []
            ),
            "IsTruncated": False,
        }


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch, configuration: dict[str, Any]) -> Api:
    api = Api()
    monkeypatch.setattr(reconcile_lambda, "datetime", SimpleNamespace(now=lambda _: api.clock))
    for name in ("wc-dev-reconcile", "wc-dev-retention-task"):
        resource = next(
            r["Properties"]
            for r in configuration.values()
            if r["Type"] == "AWS::Lambda::Function" and r["Properties"]["FunctionName"] == name
        )
        for key, value in resource["Environment"]["Variables"].items():
            monkeypatch.setenv(
                key,
                configuration[value["Ref"]]["Properties"]["TableName"]
                if isinstance(value, dict)
                else value,
            )
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    import boto3  # type: ignore[import-untyped]

    monkeypatch.setattr(boto3, "client", lambda *args, **kw: api)

    def factory(*args: Any, **kw: Any) -> Factory:
        return Factory(
            replace(
                target_status(
                    ec2=Ec2State.RUNNING if api.running else Ec2State.STOPPED,
                    ready=api.running,
                    game_id=api.selected if api.running else None,
                    public_state=PublicIpv4State.ASSIGNED
                    if api.running
                    else PublicIpv4State.ABSENT,
                    public_ip="192.0.2.1" if api.running else None,
                ),
                expected_game_id=kw["game_id"],
                observed_at=api.clock,
            )
        )

    monkeypatch.setattr(reconcile_lambda, "AwsStatusFactory", factory)
    monkeypatch.setattr(task, "_runtime", None)
    return api


def admitted(api: Api, game: str, index: int = 0, *, running: bool = False) -> dict[str, Any]:
    api.selected, api.running = game, running
    api.clock = datetime.now(UTC)
    api.items[("wc-dev-system-state", "wishicraft-main")] = wire(
        {
            "desired_state": "RUNNING" if running else "STOPPED",
            "desired_game_id": game,
            "desired_revision": index,
        }
    )
    now = api.clock - timedelta(seconds=1)
    repo = OperationAdmissionRepository(
        cast(Any, api),
        operations_table="wc-dev-operations",
        games_table="wc-dev-games",
        idempotency_table="wc-dev-idempotency",
        locks_table="wc-dev-locks",
        system_state_table="wc-dev-system-state",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
        lease_seconds=900,
        lease_id_factory=lambda: f"lease-{index}",
    )
    result = repo.admit(
        OperationRequest(
            operation_id=f"op-retention-{index}",
            idempotency_key=f"retention:fixture-{index}",
            operation_type=OperationType.RETENTION,
            target_game_id=game,
            requested_by=RequestSource.ADMIN,
            requested_at=now,
            timeout_at=now + timedelta(seconds=300),
        )
    )
    state = reconcile_lambda.handler({"schema_version": 1, "operation": "reconcile"}, None)
    assert state["health"] == "HEALTHY"
    return {
        "schema_version": 1,
        "action": "run",
        "operation_id": result.operation_id,
        "lease_id": result.lease_id,
        "state": json.loads(json.dumps(state)),
    }


@pytest.mark.parametrize("game,running", [(A, False), (B, False), (B, True)])
def test_real_handler_accepts_both_games(boundary: Api, game: str, running: bool) -> None:
    payload = admitted(boundary, game, running=running)
    assert task.handler(payload, None)["status"] == "SUCCEEDED"


def inventory(api: Api, configuration: dict[str, Any], *, tie: bool = False) -> None:
    backup = next(
        r["Properties"]
        for r in configuration.values()
        if r["Type"] == "AWS::Lambda::Function"
        and r["Properties"]["FunctionName"] == "wc-dev-backup-task"
    )
    recovery = json.dumps(
        {
            "schema_version": 1,
            "source_volume_id": api.volume,
            "games": {
                g: {"game_id": g, "data_source": f"/srv/minecraft/games/{g}/server"} for g in (A, B)
            },
            "runtime": json.loads(backup["Environment"]["Variables"]["RECOVERY_RUNTIME_JSON"]),
        },
        sort_keys=True,
    )
    for index in range(12):
        # Nine shared normal backups, then v1 normal / migration / protected.
        game = (A, B)[index % 2]
        base = record()
        stamp = base.snapshot_start_time + timedelta(hours=1 if tie and index == 2 else index)
        metadata = {
            **base.metadata,
            "WishicraftGameId": game,
            "WishicraftOperationId": f"op-backup-{index}",
            "WishicraftCreatedAt": (stamp - timedelta(seconds=1)).isoformat(),
        }
        if index < 9:
            metadata = shared_tags(metadata, recovery)
        elif index == 10:
            metadata["WishicraftCategory"] = "migration"
        elif index == 11:
            metadata["WishicraftProtected"] = "true"
        snapshot_id = f"snap-{index:017x}"
        api.inventory.append(
            {
                "SnapshotId": snapshot_id,
                "VolumeId": api.volume,
                "State": "completed",
                "OwnerId": "385526546525",
                "StartTime": stamp,
                "StorageTier": "standard",
                "Description": f"Wishicraft backup op-backup-{index}",
                "Tags": [{"Key": k, "Value": v} for k, v in metadata.items()],
            }
        )
        if index < 10:
            proof = replace(
                base,
                snapshot_id=snapshot_id,
                operation_id=f"op-backup-{index}",
                game_id=game,
                verified_owner_id="385526546525",
                metadata=metadata,
                snapshot_start_time=stamp,
                operation_requested_at=stamp - timedelta(seconds=2),
                wishicraft_created_at=stamp - timedelta(seconds=1),
                provenance_recorded_at=stamp + timedelta(seconds=2),
                schema_version=2 if index < 9 else 1,
                recovery_json=recovery if index < 9 else None,
            )
            puts = BackupProvenanceRepository(api, table_name="wc-dev-backups").transactional_puts(
                proof
            )
            api.provenance.extend(cast(Any, p)["Put"]["Item"] for p in puts)


@pytest.mark.parametrize("tie", [False, True])
def test_cached_runtime_a_b_a_has_identical_shared_plan(
    boundary: Api, configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tie: bool
) -> None:
    inventory(boundary, configuration, tie=tie)
    original = plan_retention
    plans = []

    def capture(*args: Any, **kw: Any) -> Any:
        plan = original(*args, **kw)
        plans.append(plan)
        return plan

    monkeypatch.setattr(task, "plan_retention", capture)
    runtime = task._get_runtime()
    for index, game in enumerate((A, B, A)):
        payload = admitted(boundary, game, index, running=game == B)
        result = task.handler(payload, None)
        assert result["status"] == ("FAILED" if tie else "SUCCEEDED")
        assert task._get_runtime() is runtime
        assert runtime.context.game_id == A  # No request context mutation.
        assert ("wc-dev-locks", "minecraft-control") not in boundary.items
        assert (
            "current_operation_id" not in boundary.items[("wc-dev-system-state", "wishicraft-main")]
        )
        assert any(
            r["TableName"] == "wc-dev-operations"
            and r["Key"] == {"operation_id": {"S": payload["operation_id"]}}
            for r in boundary.reads
        )
    assert plans[0] == plans[1] == plans[2]
    plan = plans[0]
    assert len(plan.keep_ids) == (9 if tie else 7)
    assert len(plan.candidate_ids) == (0 if tie else 2)
    assert set(plan.excluded_ids) == {f"snap-{i:017x}" for i in (9, 10, 11)}
    if tie:
        assert plan.reason == "keep-delete-boundary-tie"
        assert plan.planned_delete_ids == ()
    else:
        assert plan.keep_ids == tuple(f"snap-{i:017x}" for i in range(8, 1, -1))
        assert plan.candidate_ids == tuple(f"snap-{i:017x}" for i in (1, 0))
        assert plan.planned_delete_ids == ("snap-00000000000000000",)
    assert not hasattr(boundary, "delete_snapshot")


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_game_id", B),
        ("target_game_id", "game-unknown"),
        ("operation_type", "START"),
        ("status", "SUCCEEDED"),
        ("lease_id", "other-lease"),
        ("lock_name", "other-lock"),
        ("requested_by", {"source": "DISCORD"}),
        ("schema_version", 2),
    ],
)
def test_operation_authority_rejects_mismatch(boundary: Api, field: str, value: Any) -> None:
    payload = admitted(boundary, A)
    boundary.items[("wc-dev-operations", payload["operation_id"])][field] = (
        TypeSerializer().serialize(value)
    )
    with pytest.raises(ValueError):
        task.handler(payload, None)
    assert boundary.snapshot_calls == 0


@pytest.mark.parametrize(
    "fault",
    ["volume", "instance", "lock-owner", "lock-lease", "observation", "missing-operation", "stale"],
)
def test_invalid_execution_fails_before_inventory(boundary: Api, fault: str) -> None:
    payload = admitted(boundary, B)
    if fault == "volume":
        boundary.volume = "vol-00000000000000000"
    elif fault == "instance":
        boundary.attachment = "i-other"
    elif fault.startswith("lock-"):
        key = "owner_operation_id" if fault == "lock-owner" else "lease_id"
        boundary.items[("wc-dev-locks", "minecraft-control")][key] = {"S": "other"}
    elif fault == "observation":
        payload["state"]["observation"]["expected_game_id"] = A
    elif fault == "missing-operation":
        del boundary.items[("wc-dev-operations", payload["operation_id"])]
    else:
        payload["state"]["observed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises((ValueError, RuntimeError)):
        task.handler(payload, None)
    assert boundary.snapshot_calls == 0


def test_unregistered_game_cannot_produce_admission_record(boundary: Api) -> None:
    boundary.registered_games = {A}
    with pytest.raises(AdmissionConflict):
        admitted(boundary, B)
    assert not any(table == "wc-dev-operations" for table, _ in boundary.items)


def test_precondition_failure_uses_existing_owned_terminalization(boundary: Api) -> None:
    payload = admitted(boundary, B)
    payload["state"]["observation"]["expected_game_id"] = A
    with pytest.raises(ValueError):
        task.handler(payload, None)
    task.handler({**payload, "action": "fail", "error_code": "TASK_FAILED"}, None)
    item = boundary.items[("wc-dev-operations", payload["operation_id"])]
    assert item["status"] == {"S": "FAILED"}
    assert ("wc-dev-locks", "minecraft-control") not in boundary.items
    assert "current_operation_id" not in boundary.items[("wc-dev-system-state", "wishicraft-main")]
    assert boundary.snapshot_calls == 0


@pytest.mark.parametrize("fault", ["owner", "provenance"])
def test_snapshot_authority_remains_fail_closed(
    boundary: Api, configuration: dict[str, Any], fault: str
) -> None:
    inventory(boundary, configuration)
    if fault == "owner":
        boundary.inventory[0]["OwnerId"] = "000000000000"
    else:
        boundary.provenance = boundary.provenance[2:]
    result = task.handler(admitted(boundary, B), None)
    assert result == {"status": "FAILED", "reason": "inventory-anomaly"}
    assert not hasattr(boundary, "delete_snapshot")
