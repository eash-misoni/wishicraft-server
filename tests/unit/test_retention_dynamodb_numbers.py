"""Low-level DynamoDB wire responses, real deserializer/repository/recovery readers."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

from tests.unit.test_retention_execution import CANARY, PROOF, Harness
from tests.unit.test_retention_execution_boundaries import AwsReads, initial_record, repository
from tests.unit.test_retention_execution_inventory import deleted_fixture
from tests.unit.test_retention_inventory import journal as restore_journal
from tests.unit.test_retention_release_gates import recovery
from wishicraft.maintenance_operator import item
from wishicraft.maintenance_repository import encode
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord
from wishicraft.retention_execution import ExecutionMode, RetentionExecution
from wishicraft.retention_execution_reads import ExecutionReads
from wishicraft.retention_recovery_reads import read_recovery


class WireDynamo:
    """Stores Put wire values unchanged; no int-returning decoder in the fake."""

    meta = SimpleNamespace(region_name="ap-northeast-1")

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, Any]]] = {
            name: {} for name in ("backups", "locks", "states", "games", "operations")
        }
        self.transactions: list[list[dict[str, Any]]] = []
        self.account = "123456789012"

    def get_item(self, **kw: Any) -> dict[str, Any]:
        assert kw["ConsistentRead"] is True
        key = next(iter(kw["Key"].values()))["S"]
        value = self.tables[kw["TableName"]].get(key)
        return {"Item": deepcopy(value)} if value is not None else {}

    def scan(self, **kw: Any) -> dict[str, Any]:
        assert kw["ConsistentRead"] is True
        return {"Items": deepcopy(list(self.tables[kw["TableName"]].values()))}

    def describe_table(self, **kw: Any) -> dict[str, Any]:
        return {
            "Table": {
                "TableArn": (
                    f"arn:aws:dynamodb:ap-northeast-1:{self.account}:table/{kw['TableName']}"
                )
            }
        }

    def transact_write_items(self, **kw: Any) -> dict[str, Any]:
        tx = kw["TransactItems"]
        self.transactions.append(deepcopy(tx))
        for action in tx:
            if "Put" in action:
                put = action["Put"]
                self.tables[put["TableName"]][put["Item"]["provenance_key"]["S"]] = deepcopy(
                    put["Item"]
                )
            if "Update" in action and action["Update"]["TableName"] == "locks":
                update = action["Update"]
                lock = self.tables["locks"]["minecraft-control"]
                values = update["ExpressionAttributeValues"]
                if update["UpdateExpression"] == "SET retention_delete_pending = :snapshot":
                    assert (
                        "attribute_not_exists(retention_delete_pending)"
                        in update["ConditionExpression"]
                    )
                    assert "retention_delete_pending" not in lock
                    lock["retention_delete_pending"] = values[":snapshot"]
                elif update["UpdateExpression"] == "REMOVE retention_delete_pending":
                    assert "retention_delete_pending = :snapshot" in update["ConditionExpression"]
                    assert "lease_expires_at >= :now" in update["ConditionExpression"]
                    assert lock["retention_delete_pending"] == values[":snapshot"]
                    assert lock["owner_operation_id"] == values[":operation"]
                    assert lock["lease_id"] == values[":lease"]
                    assert Decimal(lock["lease_expires_at"]["N"]) >= Decimal(values[":now"]["N"])
                    del lock["retention_delete_pending"]
        return {}


def lock_row() -> dict[str, Any]:
    return encode(
        dict(
            lock_name="minecraft-control",
            resource_id=PROOF.resource_id,
            owner_operation_id=PROOF.owner_operation_id,
            lease_id=PROOF.lease_id,
            lease_expires_at=PROOF.lease_expires_at,
            operation_type="RETENTION",
        )
    )


@pytest.mark.parametrize("bound", [False, True])
def test_wire_round_trip_and_repository_pair(bound: bool) -> None:
    record = recovery().record if bound else initial_record()
    wire = encode(record.item())
    decoded = {k: TypeDeserializer().deserialize(v) for k, v in wire.items()}
    assert type(decoded["revision"]) is Decimal
    if bound:
        assert wire["dispatcher_timeout"] == {"N": "120"}
        assert type(decoded["dispatcher_timeout"]) is Decimal
    restored = DeletionRecord.parse(decoded)
    assert restored == record
    if bound:
        assert type(restored.dispatcher_timeout) is int
    else:
        assert "dispatcher_timeout" not in restored.item()
    api = WireDynamo()
    api.tables["locks"]["minecraft-control"] = lock_row()
    repo = repository(api)  # type: ignore[arg-type]
    assert repo.claim(record, PROOF, Harness().now)
    assert repo.read_snapshot(record.snapshot_id) == record
    assert repo.read_operation(record.retention_operation_id) == record


@pytest.mark.parametrize("in_bin", [False, True])
def test_bound_record_normal_reconcile_reads_wire_before_clearing_pending(in_bin: bool) -> None:
    h, api = Harness(), WireDynamo()
    api.tables["locks"]["minecraft-control"] = lock_row()
    repo = repository(api)  # type: ignore[arg-type]
    binding = recovery().record
    assert binding.execution_arn and binding.dispatcher_arn and binding.dispatcher_revision
    engine = RetentionExecution(
        reads=h,
        leases=h,
        journal=repo,
        clock=lambda: h.now,
        adapter=h.adapter,
        dispatcher=(
            binding.execution_arn,
            binding.dispatcher_arn,
            binding.dispatcher_revision,
            120,
        ),
    )
    record = engine.execute(engine.prepare(PROOF), PROOF, mode=ExecutionMode.DELETE_ONE)
    assert record and repo.read_operation(PROOF.owner_operation_id) == record
    h.observation_bin = in_bin
    lock = api.tables["locks"]["minecraft-control"]
    h.tick()
    first = engine.reconcile(PROOF)
    assert first and first.phase == DeletionPhase.RESPONSE_RECORDED
    assert "retention_delete_pending" in lock
    assert engine.reconcile(PROOF) == first
    h.tick()
    final = engine.reconcile(PROOF)
    assert final and final.phase == DeletionPhase.FORMALLY_DELETED
    assert final.reconciliation == ("RECYCLE_BIN_RETAINED" if in_bin else "ACTIVE_ABSENT")
    assert repo.read_snapshot(final.snapshot_id) == final
    assert type(final.dispatcher_timeout) is int
    assert "retention_delete_pending" not in lock
    assert len(h.adapter.calls) == 1


class RecoveryAws(AwsReads):
    meta = SimpleNamespace(region_name="ap-northeast-1")

    def __init__(self, record: DeletionRecord, fixture: dict[str, Any]) -> None:
        super().__init__()
        self.record, self.fixture = record, fixture
        self.terminal = fixture["now"] - timedelta(seconds=1700)
        self.status = "FAILED"
        self.revision = record.dispatcher_revision

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": self.record.account}

    def describe_snapshots(self, **kw: Any) -> dict[str, Any]:
        return {"Snapshots": deepcopy(self.fixture["snapshots"])}

    def describe_execution(self, **kw: Any) -> dict[str, Any]:
        r = self.record
        return dict(
            executionArn=r.execution_arn,
            name=r.retention_operation_id,
            stateMachineArn=str(r.execution_arn)
            .rsplit(":", 1)[0]
            .replace(":execution:", ":stateMachine:"),
            status=self.status,
            stopDate=self.terminal,
            redriveCount=0,
        )

    def get_execution_history(self, **kw: Any) -> dict[str, Any]:
        r = self.record
        return {
            "events": [
                {
                    "id": 1,
                    "taskScheduledEventDetails": {
                        "resourceType": "lambda",
                        "resource": "invoke",
                        "parameters": json.dumps(
                            {
                                "FunctionName": r.dispatcher_arn,
                                "Payload": {
                                    "action": "run",
                                    "operation_id": r.retention_operation_id,
                                    "lease_id": r.dispatcher_lease_id,
                                },
                            }
                        ),
                    },
                },
                {"id": 2, "type": "TaskStarted", "previousEventId": 1},
                {"id": 3, "type": "TaskFailed", "previousEventId": 2, "timestamp": self.terminal},
                {
                    "id": 4,
                    "type": "ExecutionFailed",
                    "previousEventId": 3,
                    "timestamp": self.terminal,
                },
            ]
        }

    def get_function_configuration(self, **kw: Any) -> dict[str, Any]:
        return dict(
            FunctionArn=self.record.dispatcher_arn,
            RevisionId=self.revision,
            Timeout=120,
            Environment={"Variables": {"TOKEN": CANARY}},
        )


def recovery_wire() -> tuple[WireDynamo, RecoveryAws, dict[str, Any]]:
    f, old = deleted_fixture()
    record = replace(
        old,
        phase=DeletionPhase.DISPATCHED,
        request_outcome="NOT_RECORDED",
        reconciliation="OUTCOME_UNKNOWN",
        confirmed_at=None,
        first_absent_at=None,
        last_observed_at=None,
        revision=1,
        requested_at=(f["now"] - timedelta(seconds=2000)).isoformat(),
        execution_arn=f"arn:aws:states:{old.region}:{old.account}:execution:wc-dev-retention:{old.retention_operation_id}",
        dispatcher_arn=f"arn:aws:lambda:{old.region}:{old.account}:function:wc-dev-retention-task",
        dispatcher_revision="revision-1",
        dispatcher_timeout=120,
        dispatcher_lease_id=PROOF.lease_id,
    )
    api = WireDynamo()
    api.account = record.account
    for row in f["provenance_rows"]:
        api.tables["backups"][row["provenance_key"]] = encode(row)
    api.tables["locks"]["minecraft-control"] = lock_row()
    admitted_at = f["now"] - timedelta(seconds=2000)
    admitted_lease = replace(PROOF, lease_expires_at=int(admitted_at.timestamp()) + 900)
    api.tables["locks"]["minecraft-control"]["lease_expires_at"] = {
        "N": str(admitted_lease.lease_expires_at)
    }
    repo = repository(api)  # type: ignore[arg-type]
    repo.claim(record, admitted_lease, admitted_at)
    api.tables["states"][record.system_id] = encode(f["state"])
    for row in f["games"]:
        api.tables["games"][row["game_id"]] = encode(row)
    aws = RecoveryAws(record, f)
    reads = ExecutionReads(
        ec2=aws,
        rbin=aws,
        dynamodb=api,
        sts=aws,
        context=f["context"],
        region=f["region"],
        system_id=f["system_id"],
        operation_id=f["operation_id"],
        tables=dict(state="states", games="games", backups="backups", operations="operations"),
        holds={},
        hold_revision="reviewed-live-holds",
        clock=lambda: f["now"],
    )
    args = dict(
        record=record,
        reads=reads,
        dynamodb=api,
        locks_table="locks",
        lock_name="minecraft-control",
        states=aws,
        functions=aws,
        now=f["now"],
        journal=repo,
    )
    return api, aws, args


def test_real_recovery_reader_normalizes_decimal_lease_without_reader_mock(capsys: Any) -> None:
    api, _, args = recovery_wire()
    decoded = item(api, "locks", "lock_name", "minecraft-control")
    assert type(decoded["lease_expires_at"]) is Decimal
    before = deepcopy(api.tables)
    result = read_recovery(**args)
    assert type(result.old_lease.lease_expires_at) is int
    result.verify(args["now"])
    assert api.tables == before  # read-only; no unlock, resend, provenance change
    assert CANARY not in repr(result) + str(capsys.readouterr())


BAD_WIRE = [
    {"N": v} for v in ("1.5", "NaN", "Infinity", "-Infinity", "-1", "0", "253402300800")
] + [{"BOOL": True}, {"S": CANARY}, {"NULL": True}, {"M": {}}, {"N": "1e999"}]


@pytest.mark.parametrize("value", BAD_WIRE)
def test_recovery_invalid_numeric_wire_is_not_repaired(value: dict[str, Any], capsys: Any) -> None:
    api, _, args = recovery_wire()
    api.tables["locks"]["minecraft-control"]["lease_expires_at"] = value
    with pytest.raises(ValueError, match="MANUAL_REVIEW_REQUIRED") as error:
        read_recovery(**args)
    assert CANARY not in str(error.value) + str(capsys.readouterr())
    assert "retention_delete_pending" in api.tables["locks"]["minecraft-control"]


@pytest.mark.parametrize(
    "change",
    [
        "lease",
        "quiescence",
        "identity",
        "reference",
        "owner",
        "snapshot",
        "nonterminal",
        "recent-expiry",
        "journal",
    ],
)
def test_real_recovery_reader_still_rejects_safety_failures(change: str) -> None:
    api, aws, args = recovery_wire()
    lock = api.tables["locks"]["minecraft-control"]
    if change == "lease":
        lock["lease_expires_at"] = {"N": str(int(args["now"].timestamp()) + 1)}
    elif change == "recent-expiry":
        lock["lease_expires_at"] = {"N": str(int(args["now"].timestamp()) - 1)}
    elif change == "journal":
        row = restore_journal()
        api.tables["states"][row["system_id"]] = encode(row)
    elif change == "quiescence":
        aws.terminal = args["now"] - timedelta(seconds=100)
    elif change == "identity":
        aws.revision = "other-revision"
    elif change == "reference":
        args["reads"].holds[args["record"].snapshot_id] = ("new-hold",)
    elif change == "owner":
        lock["owner_operation_id"] = {"S": "op-other"}
    elif change == "snapshot":
        lock["retention_delete_pending"] = {"S": "snap-fffffffffffffffff"}
    else:
        aws.status = "RUNNING"
    with pytest.raises(ValueError, match="MANUAL_REVIEW_REQUIRED"):
        read_recovery(**args)
    assert "retention_delete_pending" in lock


@pytest.mark.parametrize("value", BAD_WIRE + [{"N": "901"}, {"N": "120.5"}])
def test_dispatcher_timeout_invalid_wire(value: dict[str, Any]) -> None:
    wire = encode(recovery().record.item())
    wire["dispatcher_timeout"] = value
    with pytest.raises((ValueError, ArithmeticError)):
        decoded = {k: TypeDeserializer().deserialize(v) for k, v in wire.items()}
        DeletionRecord.parse(decoded)


@pytest.mark.parametrize("number,expected", [("1", 1), ("120.0", 120), ("900", 900)])
def test_dispatcher_integral_wire_boundaries(number: str, expected: int) -> None:
    wire = encode(recovery().record.item())
    wire["dispatcher_timeout"] = {"N": number}
    restored = DeletionRecord.parse({k: TypeDeserializer().deserialize(v) for k, v in wire.items()})
    assert type(restored.dispatcher_timeout) is int and restored.dispatcher_timeout == expected


@pytest.mark.parametrize("field", ["dispatcher_timeout", "lease_expires_at"])
@pytest.mark.parametrize("value", [120.0, 120.5, True, float("nan"), float("inf"), "120", None])
def test_direct_invalid_types_are_not_coerced(field: str, value: Any) -> None:
    from wishicraft.retention_recovery_reads import _lease_expiry

    with pytest.raises(ValueError):
        if field == "dispatcher_timeout":
            DeletionRecord.parse({**recovery().record.item(), field: value})
        else:
            _lease_expiry(value)
