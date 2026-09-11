"""Actual SDK transport/serialization and production handler boundary tests (no AWS)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer  # type: ignore[import-untyped]
from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from tests.unit.test_backup import Ec2
from wishicraft import backup_workflow_lambda as task
from wishicraft.backup import BackupCoordinator, SnapshotAdapter
from wishicraft.backup_create import (
    BackupCreateGuard,
    BackupCreateOutcomeUnknown,
    BackupCreateRejected,
    BackupProvenanceOutcomeUnknown,
)
from wishicraft.backup_provenance import BackupProvenanceRepository
from wishicraft.operation import LeaseRepository, OperationRepository
from wishicraft.system_state import utc_timestamp

OP = "op-01234567-89ab-cdef-0123-456789abcdef"
LEASE = "lease-test"


class MemoryDynamo:
    """Small stateful CAS fixture; SDK wire validation is tested separately."""

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.items: dict[str, dict[str, Any]] = {
            OP: {
                "operation_id": OP,
                "operation_type": "BACKUP",
                "status": "RUNNING",
                "target_game_id": "game-vanilla-main",
                "lease_id": LEASE,
                "timeout_at": utc_timestamp(now + timedelta(minutes=15)),
                "requested_at": utc_timestamp(now),
                "result": None,
            },
            "control": {
                "lock_name": "control",
                "owner_operation_id": OP,
                "lease_id": LEASE,
                "resource_id": "system",
                "lease_expires_at": int(now.timestamp()) + 900,
            },
            "system": {"system_id": "system", "current_operation_id": OP},
        }
        self.lose_reservation = False
        self.lose_completion = False
        self.reject_completion = False
        self.transactions: list[dict[str, Any]] = []

    @staticmethod
    def encode(item: dict[str, Any]) -> dict[str, Any]:
        return {k: TypeSerializer().serialize(v) for k, v in item.items()}

    @staticmethod
    def decode(item: dict[str, Any]) -> dict[str, Any]:
        return {k: TypeDeserializer().deserialize(v) for k, v in item.items()}

    def get_item(self, **kwargs: Any) -> Any:
        assert kwargs["ConsistentRead"] is True
        key = next(iter(self.decode(kwargs["Key"]).values()))
        return {"Item": self.encode(self.items[key])} if key in self.items else {}

    def update_item(self, **kwargs: Any) -> Any:
        values = self.decode(kwargs["ExpressionAttributeValues"])
        self.items[OP]["backup_snapshot_id"] = values[":snapshot"]
        return {}

    def delete_item(self, **kwargs: Any) -> Any:
        raise AssertionError("unexpected standalone delete")

    def transact_write_items(self, **kwargs: Any) -> Any:
        self.transactions.append(kwargs)
        writes = kwargs["TransactItems"]
        if "ConditionCheck" in writes[0]:
            check = writes[0]["ConditionCheck"]
            values = self.decode(check["ExpressionAttributeValues"])
            lock = self.items.get("control", {})
            assert "lease_expires_at >= :now" in check["ConditionExpression"]
            update = writes[1]["Update"]
            v = self.decode(update["ExpressionAttributeValues"])
            op = self.items[OP]
            if (
                lock.get("owner_operation_id") != values[":op"]
                or lock.get("lease_id") != values[":lease"]
                or lock.get("resource_id") != values[":system"]
                or lock.get("lease_expires_at", 0) < values[":now"]
                or op.get("backup_create_intent") is not None
                or op["status"] != "RUNNING"
                or op["lease_id"] != v[":lease"]
                or op["target_game_id"] != v[":game"]
                or op["timeout_at"] <= v[":now"]
            ):
                raise RuntimeError("condition rejected")
            op["backup_create_intent"] = v[":intent"]
            if self.lose_reservation:
                raise TimeoutError("lost transaction response")
        else:
            if self.reject_completion:
                raise RuntimeError("transaction rejected")
            for write in writes:
                if "Put" in write:
                    item = self.decode(write["Put"]["Item"])
                    self.items[item["provenance_key"]] = item
            v = self.decode(writes[0]["Update"]["ExpressionAttributeValues"])
            self.items[OP].update(status=v[":status"], result=v[":result"])
            self.items.pop("control", None)
            self.items["system"].pop("current_operation_id", None)
            if self.lose_completion:
                raise TimeoutError("lost terminal response")
        return {}


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> Any:
    db = MemoryDynamo()
    ec2 = Ec2()
    leases = LeaseRepository(db, table_name="locks", lock_name="control")
    value = SimpleNamespace(
        system_id="system",
        db=db,
        ec2=ec2,
        operations=OperationRepository(
            db,
            operations_table="operations",
            locks_table="locks",
            system_state_table="state",
            system_id="system",
            lock_name="control",
        ),
        create_guard=BackupCreateGuard(
            db, operations_table="operations", locks_table="locks", lock_name="control"
        ),
        provenance=BackupProvenanceRepository(db, table_name="backups"),
        coordinator=BackupCoordinator(
            leases=leases,
            snapshots=SnapshotAdapter(ec2, account_id="123456789012"),
            expected_volume_id="vol-03ac9f534326c345c",
            availability_zone="ap-northeast-1a",
            project="wishicraft",
            stage="dev",
            game_id="game-vanilla-main",
            lease_seconds=900,
        ),
    )
    monkeypatch.setattr(task, "_runtime", value)
    return value


def event(action: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "action": action, "operation_id": OP, "lease_id": LEASE, **extra}


def test_handler_replay_cannot_create_again(runtime: Any) -> None:
    result = task.handler(event("create"), None)
    assert result["snapshot_id"] == runtime.db.items[OP]["backup_snapshot_id"]
    with pytest.raises(BackupCreateOutcomeUnknown):
        task.handler(event("create"), None)
    assert len(runtime.ec2.created) == 1
    assert runtime.db.items[OP]["backup_create_intent"] == result["tags"]


def test_lost_reservation_response_never_grants_create(runtime: Any) -> None:
    runtime.db.lose_reservation = True
    for _ in range(2):
        with pytest.raises(BackupCreateOutcomeUnknown):
            task.handler(event("create"), None)
    assert runtime.ec2.created == []
    assert "backup_create_intent" in runtime.db.items[OP]


def test_lost_ec2_response_does_not_create_twice(
    runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = runtime.ec2.create_snapshot

    def lost(**kwargs: Any) -> Any:
        original(**kwargs)
        raise TimeoutError("response lost after AWS acceptance")

    monkeypatch.setattr(runtime.ec2, "create_snapshot", lost)
    for _ in range(2):
        with pytest.raises(BackupCreateOutcomeUnknown):
            task.handler(event("create"), None)
    assert len(runtime.ec2.created) == 1
    assert "backup_snapshot_id" not in runtime.db.items[OP]


def test_lost_snapshot_id_persistence_does_not_create_twice(
    runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lost(**kwargs: Any) -> Any:
        raise TimeoutError("response persistence unavailable")

    monkeypatch.setattr(runtime.db, "update_item", lost)
    for _ in range(2):
        with pytest.raises(BackupCreateOutcomeUnknown):
            task.handler(event("create"), None)
    assert len(runtime.ec2.created) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_game_id", "game-other"),
        ("lease_id", "other"),
        ("status", "SUCCEEDED"),
        ("timeout_at", "2000-01-01T00:00:00Z"),
    ],
)
def test_wrong_operation_cannot_reserve(runtime: Any, field: str, value: str) -> None:
    runtime.db.items[OP][field] = value
    with pytest.raises(BackupCreateOutcomeUnknown):
        task.handler(event("create"), None)
    assert runtime.ec2.created == []


@pytest.mark.parametrize(
    "code,http,exception",
    [
        ("UnauthorizedOperation", 403, BackupCreateRejected),
        ("InternalError", 500, BackupCreateOutcomeUnknown),
        ("RequestLimitExceeded", 503, BackupCreateOutcomeUnknown),
    ],
)
def test_explicit_rejection_and_ambiguity(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, code: str, http: int, exception: type[Exception]
) -> None:
    def failure(**kwargs: Any) -> Any:
        runtime.ec2.created.append(kwargs)
        raise ClientError(
            {
                "Error": {"Code": code, "Message": "private diagnostic"},
                "ResponseMetadata": {"HTTPStatusCode": http},
            },
            "CreateSnapshot",
        )

    monkeypatch.setattr(runtime.ec2, "create_snapshot", failure)
    with pytest.raises(exception) as caught:
        task.handler(event("create"), None)
    assert "private diagnostic" not in str(caught.value)
    with pytest.raises(BackupCreateOutcomeUnknown):
        task.handler(event("create"), None)
    assert len(runtime.ec2.created) == 1


def prepare_complete(runtime: Any) -> dict[str, Any]:
    result = task.handler(event("create"), None)
    snap = runtime.ec2.snapshot["Snapshots"][0]
    snap["Tags"] = [{"Key": k, "Value": v} for k, v in cast(dict[str, str], result["tags"]).items()]
    return event("complete", **result)


def test_lost_provenance_response_and_terminal_handler_replay(runtime: Any) -> None:
    payload = prepare_complete(runtime)
    runtime.db.lose_completion = True
    assert task.handler(payload, None) == {"status": "SUCCEEDED"}
    assert task.handler(payload, None) == {"status": "SUCCEEDED"}
    assert runtime.db.items[OP]["status"] == "SUCCEEDED"
    assert len(runtime.ec2.created) == 1
    assert len([k for k in runtime.db.items if k.startswith("SNAPSHOT#")]) == 1


def test_rejected_provenance_keeps_snapshot_and_can_complete_same_snapshot(runtime: Any) -> None:
    payload = prepare_complete(runtime)
    runtime.db.reject_completion = True
    with pytest.raises(BackupProvenanceOutcomeUnknown):
        task.handler(payload, None)
    assert runtime.db.items[OP]["status"] == "RUNNING"
    assert len(runtime.ec2.created) == 1
    runtime.db.reject_completion = False
    assert task.handler(payload, None) == {"status": "SUCCEEDED"}


class Raw:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def stream(self, **kwargs: Any) -> Any:
        yield self.data


def test_runtime_sdk_transport_total_attempts_and_read_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("AWS_RETRY_MODE", "standard")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for name in (
        "AWS_REGION",
        "SYSTEM_ID",
        "OPERATIONS_TABLE",
        "LOCKS_TABLE",
        "GLOBAL_LOCK_NAME",
        "SYSTEM_STATE_TABLE",
        "BACKUPS_TABLE",
        "AWS_ACCOUNT_ID",
        "DATA_VOLUME_ID",
        "AVAILABILITY_ZONE",
        "PROJECT",
        "STAGE",
        "GAME_ID",
    ):
        monkeypatch.setenv(name, "ap-northeast-1" if name == "AWS_REGION" else "test")
    monkeypatch.setenv("LOCK_LEASE_SECONDS", "900")
    session = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing")
    monkeypatch.setattr(task, "importlib", SimpleNamespace(import_module=lambda name: session))
    rt = task.Runtime()
    reader = cast(Any, rt.coordinator.snapshots._api)
    writer = cast(Any, rt.coordinator.snapshots._create_api)
    assert writer.meta.config.retries["total_max_attempts"] == 1
    assert reader.meta.config.retries["total_max_attempts"] == 4
    attempts: list[str] = []

    def send(request: Any) -> Any:
        attempts.append(request.body.decode() if isinstance(request.body, bytes) else request.body)
        return AWSResponse(
            request.url,
            500,
            {},
            Raw(
                b"<Response><Errors><Error><Code>InternalError</Code><Message>error</Message>"
                b"</Error></Errors><RequestID>test</RequestID></Response>"
            ),
        )

    monkeypatch.setattr(writer._endpoint.http_session, "send", send)
    monkeypatch.setattr(reader._endpoint.http_session, "send", send)
    monkeypatch.setattr("botocore.endpoint.time.sleep", lambda delay: None)
    with pytest.raises(ClientError):
        writer.create_snapshot(VolumeId="vol-0123456789abcdef0")
    assert len(attempts) == 1
    with pytest.raises(ClientError):
        reader.describe_snapshots(SnapshotIds=["snap-0123456789abcdef0"])
    assert len(attempts) == 5


def test_reservation_uses_real_sdk_wire_and_distinct_transaction_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from wishicraft.operation import LeaseProof

    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    client = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing").client(
        "dynamodb", region_name="ap-northeast-1"
    )
    requests: list[dict[str, Any]] = []

    def send(request: Any) -> Any:
        requests.append(json.loads(request.body))
        return AWSResponse(
            request.url, 200, {"content-type": "application/x-amz-json-1.0"}, Raw(b"{}")
        )

    monkeypatch.setattr(client._endpoint.http_session, "send", send)
    guard = BackupCreateGuard(
        client, operations_table="operations", locks_table="locks", lock_name="control"
    )
    from tests.unit.test_backup import backup_tags

    for _ in range(2):
        guard.reserve(
            proof=LeaseProof("system", OP, LEASE, 0), tags=backup_tags(), now=datetime.now(UTC)
        )
    assert requests[0]["ClientRequestToken"] != requests[1]["ClientRequestToken"]
    for request in requests:
        check, update = request["TransactItems"]
        assert check["ConditionCheck"]["TableName"] == "locks"
        assert update["Update"]["TableName"] == "operations"
        assert (
            "attribute_not_exists(backup_create_intent)" in update["Update"]["ConditionExpression"]
        )
        assert update["Update"]["ExpressionAttributeValues"][":intent"]["M"][
            "WishicraftGameId"
        ] == {"S": "game-vanilla-main"}
