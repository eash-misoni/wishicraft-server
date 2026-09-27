from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from tests.unit.test_retention_daily import NOW
from tests.unit.test_retention_execution import CANARY, PROOF, Harness
from tests.unit.test_retention_inventory import Pages
from wishicraft.maintenance_repository import encode
from wishicraft.operation import _decode_attribute
from wishicraft.retention import DeleteRequestOutcome
from wishicraft.retention_aws_checks import inspect_candidate, pages
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord, split_deletion_records
from wishicraft.retention_deletion_repository import DeletionRepository


class Dynamo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.transactions: list[list[dict[str, Any]]] = []
        self.lose_reply = False
        self.conflict = False

    def get_item(self, **kw: Any) -> dict[str, Any]:
        assert kw["ConsistentRead"] is True
        key = kw["Key"]["provenance_key"]["S"]
        return {"Item": encode(self.rows[key])} if key in self.rows else {}

    def transact_write_items(self, **kw: Any) -> dict[str, Any]:
        tx = kw["TransactItems"]
        self.transactions.append(tx)
        if self.conflict:
            raise RuntimeError(CANARY)
        for action in tx:
            if "Put" in action:
                row = {k: _decode_attribute(v) for k, v in action["Put"]["Item"].items()}
                self.rows[str(row["provenance_key"])] = row
        if self.lose_reply:
            raise RuntimeError(CANARY)
        return {}


def repository(api: Dynamo) -> DeletionRepository:
    return DeletionRepository(
        api,
        backups_table="backups",
        locks_table="locks",
        state_table="states",
        operations_table="operations",
        lock_name="minecraft-control",
    )


def initial_record() -> DeletionRecord:
    h = Harness()
    r = h.execute()
    assert r
    return replace(r, phase=DeletionPhase.DISPATCHED, request_outcome="NOT_RECORDED", revision=1)


def test_atomic_claim_durable_unique_pair_and_no_provenance_overwrite() -> None:
    api = Dynamo()
    api.rows["SNAPSHOT#old"] = {"immutable": True}
    repo = repository(api)
    r = initial_record()
    assert repo.claim(r, PROOF, NOW)
    tx = api.transactions[0]
    assert len(tx) == 5
    lock = tx[0]["Update"]
    assert "attribute_not_exists(retention_delete_pending)" in lock["ConditionExpression"]
    assert "lease_expires_at >= :now" in lock["ConditionExpression"]
    assert lock["UpdateExpression"] == "SET retention_delete_pending = :snapshot"
    assert tx[1]["ConditionCheck"]["TableName"] == "states"
    assert "current_operation_id = :op" in tx[1]["ConditionCheck"]["ConditionExpression"]
    assert "requested_by = :actor" in tx[2]["ConditionCheck"]["ConditionExpression"]
    assert repo.read_operation(PROOF.owner_operation_id) == r
    assert not repo.claim(r, PROOF, NOW)
    assert len(api.transactions) == 1
    assert api.rows["SNAPSHOT#old"] == {"immutable": True}
    assert all("ttl" not in key.lower() for key in r.item())
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        repo.claim(replace(r, snapshot_id="snap-fffffffffffffffff"), PROOF, NOW)
    _, found = split_deletion_records([v for k, v in api.rows.items() if k != "SNAPSHOT#old"])
    assert found[r.snapshot_id] == r


def test_lost_claim_reply_never_authorizes_dispatch_and_save_reply_is_read_back() -> None:
    api = Dynamo()
    repo, r = repository(api), initial_record()
    api.lose_reply = True
    with pytest.raises(ValueError, match="CLAIM_UNKNOWN") as error:
        repo.claim(r, PROOF, NOW)
    assert CANARY not in str(error.value)
    assert not repo.claim(r, PROOF, NOW)
    after = r.advance(
        phase=DeletionPhase.NO_MUTATION,
        request_outcome=DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED,
        reconciliation="ACCESS_DENIED",
    )
    repo.save(r, after, PROOF, NOW)
    assert repo.read_operation(PROOF.owner_operation_id) == after
    tx = api.transactions[-1]
    assert tx[0]["Update"]["UpdateExpression"] == "REMOVE retention_delete_pending"
    assert "retention_delete_pending = :snapshot" in tx[0]["Update"]["ConditionExpression"]
    assert "#revision = :revision" in tx[1]["Put"]["ConditionExpression"]


def test_conflict_unknown_record_and_partial_pair_fail_closed() -> None:
    api = Dynamo()
    repo, r = repository(api), initial_record()
    api.conflict = True
    with pytest.raises(ValueError) as error:
        repo.claim(r, PROOF, NOW)
    assert CANARY not in str(error.value)
    assert not api.rows
    with pytest.raises(ValueError, match="PARTIAL"):
        split_deletion_records([r.item()])
    with pytest.raises(ValueError, match="INVALID_DELETION"):
        DeletionRecord.parse({**r.item(), "recovery_json": CANARY})
    bad = deepcopy(r.item())
    bad["revision"] = True
    with pytest.raises(ValueError):
        DeletionRecord.parse(bad)


def test_pending_response_cannot_release_fence_and_illegal_transition_rejected() -> None:
    api = Dynamo()
    repo, r = repository(api), initial_record()
    repo.claim(r, PROOF, NOW)
    after = r.advance(
        phase=DeletionPhase.RESPONSE_RECORDED, request_outcome=DeleteRequestOutcome.OUTCOME_UNKNOWN
    )
    repo.save(r, after, PROOF, NOW)
    assert "ConditionCheck" in api.transactions[-1][0]
    with pytest.raises(ValueError):
        repo.save(
            after,
            replace(after, revision=after.revision + 1, phase=DeletionPhase.DISPATCHED, attempt=1),
            PROOF,
            NOW,
        )


class AwsReads:
    def __init__(self) -> None:
        self.images: list[dict[str, Any]] = []
        self.permissions: list[dict[str, Any]] = []
        self.locks: list[dict[str, Any]] = []
        self.bin: list[dict[str, Any]] = []
        self.fail = ""
        self.calls: list[str] = []

    def answer(self, method: str, value: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(method)
        if method == self.fail:
            raise RuntimeError(CANARY)
        return value

    def describe_images(self, **kw: Any) -> dict[str, Any]:
        assert kw["IncludeDisabled"] and kw["IncludeDeprecated"]
        assert kw["Filters"][0]["Name"] == "block-device-mapping.snapshot-id"
        return self.answer("ami", {"Images": self.images})

    def describe_snapshot_attribute(self, **kw: Any) -> dict[str, Any]:
        assert kw["Attribute"] == "createVolumePermission"
        return self.answer(
            "sharing", {"SnapshotId": kw["SnapshotId"], "CreateVolumePermissions": self.permissions}
        )

    def describe_locked_snapshots(self, **kw: Any) -> dict[str, Any]:
        return self.answer("lock", {"Snapshots": self.locks})

    def list_snapshots_in_recycle_bin(self, **kw: Any) -> dict[str, Any]:
        return self.answer("bin", {"Snapshots": self.bin})

    def list_rules(self, **kw: Any) -> dict[str, Any]:
        return self.answer("rules", {"Rules": []})


@pytest.mark.parametrize("domain", ["ami", "sharing", "lock", "bin", "rules", ""])
def test_aws_checks_missing_domains_not_assumed_empty(domain: str) -> None:
    api = AwsReads()
    api.fail = domain
    result = inspect_candidate(
        api, api, snapshot_id="snap-0123456789abcdef0", account="123456789012", tags={}
    )
    assert bool(result.issues) == bool(domain)
    assert CANARY not in str(result)
    assert set(api.calls) == {"ami", "sharing", "lock", "rules", "bin"} - (
        {"bin"} if domain == "rules" else set()
    )


@pytest.mark.parametrize("kind", ["images", "permissions", "locks", "bin"])
def test_actual_aws_constraints_block(kind: str) -> None:
    api = AwsReads()
    setattr(
        api,
        kind,
        [
            {
                "ImageId": "ami-one",
                "SnapshotId": "snap-0123456789abcdef0",
                "LockState": "compliance",
                "Group": "all",
            }
        ],
    )
    assert inspect_candidate(
        api, api, snapshot_id="snap-0123456789abcdef0", account="123456789012", tags={}
    ).issues


def test_pagination_empty_middle_duplicates_cycles_and_no_mutation_method() -> None:
    api = Pages(
        [
            {"Snapshots": [], "NextToken": "a"},
            {"Snapshots": [], "NextToken": "b"},
            {"Snapshots": [{"SnapshotId": "one"}]},
        ]
    )
    assert pages(api, "describe_snapshots", {}, "Snapshots", "SnapshotId") == [
        {"SnapshotId": "one"}
    ]
    assert len(api.calls) == 3
    invalid_pages: list[list[Any]] = [
        [{"Snapshots": [], "NextToken": "a"}, {"Snapshots": [], "NextToken": "a"}],
        [
            {"Snapshots": [{"SnapshotId": "one"}], "NextToken": "a"},
            {"Snapshots": [{"SnapshotId": "one"}]},
        ],
    ]
    for responses in invalid_pages:
        with pytest.raises(ValueError):
            pages(Pages(responses), "describe_snapshots", {}, "Snapshots", "SnapshotId")
    with pytest.raises(ValueError, match="READ_ONLY"):
        pages(api, "delete_snapshot", {}, "Snapshots", "SnapshotId")
    assert CANARY not in json.dumps(api.calls)


def test_formal_lease_cleanup_and_restore_use_the_same_global_fence() -> None:
    from tests.unit.test_operation import FakeDynamo
    from wishicraft.operation import LeaseRepository
    from wishicraft.restore_repository import RestoreRepository

    api = FakeDynamo()
    leases = LeaseRepository(api, table_name="locks", lock_name="minecraft-control")
    leases.release(PROOF, now=NOW)
    assert "attribute_not_exists(retention_delete_pending)" in str(api.deletes)
    # Verify the formal RESTORE implementation's transaction fence; it does not treat
    # an expired retained lock as permission to create a new source reference.
    restore = RestoreRepository(
        api,
        state_table="states",
        games_table="games",
        locks_table="locks",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
    )
    lease = dict(
        schema_version=1,
        status="ACTIVE",
        started_at=int(NOW.timestamp()),
        expires_at=int(NOW.timestamp()) + 900,
        id="maint",
        actor="ADMIN",
        reason="RESTORE",
    )
    fence = restore.fences(lease, NOW)[1]["ConditionCheck"]
    assert fence["TableName"] == "locks"
    assert fence["Key"] == {"lock_name": {"S": "minecraft-control"}}
    assert fence["ConditionExpression"] == "attribute_not_exists(lock_name)"


def test_reader_account_region_and_error_projection_never_dispatch() -> None:
    from types import SimpleNamespace

    from wishicraft.retention_execution_reads import ExecutionReads

    class Denied:
        meta = SimpleNamespace(region_name="ap-northeast-1")

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": "WRONG"}

    h = Harness()
    api = Denied()
    reads = ExecutionReads(
        ec2=api,
        rbin=api,
        dynamodb=api,
        sts=api,
        context=h.inventory_value.context,
        region="ap-northeast-1",
        system_id="wishicraft-main",
        operation_id=PROOF.owner_operation_id,
        tables=dict(state="s", games="g", backups="b", operations="o"),
        holds={},
        hold_revision="review",
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="FRESH_READ_UNCONFIRMED"):
        reads.inventory()
    obs = reads.observe("snap-0123456789abcdef0")
    assert obs.active is None and obs.in_recycle_bin is None


def test_read_adapter_whole_owned_inventory_and_bin_are_independent() -> None:
    from types import SimpleNamespace

    from wishicraft.retention_execution_reads import ExecutionReads

    h = Harness()

    class Reader(AwsReads):
        meta = SimpleNamespace(region_name="ap-northeast-1")

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": h.inventory_value.context.owner_id}

        def describe_snapshots(self, **kw: Any) -> dict[str, Any]:
            assert kw["OwnerIds"] == [h.inventory_value.context.owner_id]
            assert "Filters" not in kw and "SnapshotIds" not in kw
            return {"Snapshots": []}

    api = Reader()
    reads = ExecutionReads(
        ec2=api,
        rbin=api,
        dynamodb=api,
        sts=api,
        context=h.inventory_value.context,
        region="ap-northeast-1",
        system_id="wishicraft-main",
        operation_id=PROOF.owner_operation_id,
        tables=dict(state="s", games="g", backups="b", operations="o"),
        holds={},
        hold_revision="review",
        clock=lambda: NOW,
    )
    assert reads.observe("snap-0123456789abcdef0").active is False
    api.fail = "bin"
    obs = reads.observe("snap-0123456789abcdef0")
    assert obs.active is None and obs.in_recycle_bin is None
