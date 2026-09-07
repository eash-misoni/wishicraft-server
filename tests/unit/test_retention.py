from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wishicraft.operation import OperationType
from wishicraft.retention import (
    BackupProvenance,
    DeleteReconciliation,
    DeleteRequestOutcome,
    FakeSnapshotDeleteAdapter,
    InventorySnapshot,
    RecycleBinState,
    RetentionContext,
    RetentionRunStatus,
    SnapshotDisposition,
    classify_inventory,
    load_complete_inventory,
    parse_rfc3339,
    plan_retention,
    reconcile_delete_outcome,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
CONTEXT = RetentionContext("Wishicraft", "dev", "game-vanilla-main", "vol-data", "123")


def snapshot(index: int, **changes: object) -> InventorySnapshot:
    operation_id = f"op-{index}"
    created = NOW + timedelta(hours=index)
    values: dict[str, object] = {
        "snapshot_id": f"snap-{index:017x}",
        "source_volume_id": "vol-data",
        "state": "completed",
        "owner_id": "123",
        "start_time": created,
        "description": f"Wishicraft backup {operation_id}",
        "tags": {
            "Project": "Wishicraft",
            "Stage": "dev",
            "WishicraftCategory": "backup",
            "WishicraftGameId": "game-vanilla-main",
            "WishicraftOperationId": operation_id,
            "WishicraftSourceVolumeId": "vol-data",
            "WishicraftSchemaVersion": "1",
            "WishicraftProtected": "false",
            "WishicraftCreatedAt": created.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
    }
    values.update(changes)
    return InventorySnapshot(**values)  # type: ignore[arg-type]


def provenance(item: InventorySnapshot, **changes: object) -> BackupProvenance:
    values: dict[str, object] = {
        "snapshot_id": item.snapshot_id,
        "operation_id": item.tags["WishicraftOperationId"],
        "game_id": "game-vanilla-main",
        "stage": "dev",
        "source_volume_id": "vol-data",
        "requested_at": parse_rfc3339(item.tags["WishicraftCreatedAt"]),
        "verified_at": NOW,
    }
    values.update(changes)
    return BackupProvenance(**values)  # type: ignore[arg-type]


def proofs(items: list[InventorySnapshot]) -> dict[str, BackupProvenance]:
    return {item.snapshot_id: provenance(item) for item in items}


def test_retention_operation_is_independent_locking_type() -> None:
    assert OperationType.RETENTION.requires_lock is True


def test_operation_ttl_loss_is_replaced_by_durable_provenance_requirement() -> None:
    item = snapshot(1)
    result = classify_inventory([item], {}, context=CONTEXT)
    assert result[0].disposition is SnapshotDisposition.ANOMALY
    assert result[0].reason == "missing-durable-provenance"


def test_manual_migration_and_protected_are_excluded_not_anomalies() -> None:
    manual = snapshot(1, tags={})
    migration = snapshot(2, tags={**snapshot(2).tags, "WishicraftCategory": "migration"})
    protected = snapshot(3, tags={**snapshot(3).tags, "WishicraftProtected": "true"})
    result = classify_inventory([manual, migration, protected], {}, context=CONTEXT)
    assert [item.disposition for item in result] == [SnapshotDisposition.EXCLUDED] * 3


def test_malformed_claimed_backup_is_anomaly_and_blocks_entire_run() -> None:
    valid = [snapshot(i) for i in range(8)]
    malformed = snapshot(9, tags={**snapshot(9).tags, "WishicraftSchemaVersion": "2"})
    plan = plan_retention(
        [*valid, malformed], proofs(valid), context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert plan.status is RetentionRunStatus.NO_DELETE
    assert plan.planned_delete_ids == ()
    assert malformed.snapshot_id in plan.anomaly_ids


def test_excluded_only_inventory_is_normal_zero_candidate_dry_run() -> None:
    plan = plan_retention(
        [snapshot(1, tags={})], {}, context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert plan.status is RetentionRunStatus.DRY_RUN
    assert plan.reason == "within-retention-limit"
    assert plan.planned_delete_ids == ()


@pytest.mark.parametrize("count", range(8))
def test_zero_through_seven_backups_have_no_candidate(count: int) -> None:
    items = [snapshot(i) for i in range(count)]
    plan = plan_retention(
        items, proofs(items), context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert plan.candidate_ids == ()
    assert plan.planned_delete_ids == ()


def test_eight_backups_produce_one_candidate_and_one_delete_plan() -> None:
    items = [snapshot(i) for i in range(8)]
    plan = plan_retention(
        items, proofs(items), context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert plan.candidate_ids == (snapshot(0).snapshot_id,)
    assert plan.planned_delete_ids == plan.candidate_ids


def test_nine_backups_still_plan_at_most_one_oldest_delete() -> None:
    items = [snapshot(i) for i in range(9)]
    plan = plan_retention(
        items, proofs(items), context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert len(plan.candidate_ids) == 2
    assert plan.planned_delete_ids == (snapshot(0).snapshot_id,)


def test_keep_delete_boundary_tie_is_run_wide_no_delete() -> None:
    items = [snapshot(i) for i in range(8)]
    items[0] = snapshot(0, start_time=items[1].start_time)
    plan = plan_retention(
        items, proofs(items), context=CONTEXT, recycle_bin_preflight_complete=True
    )
    assert plan.status is RetentionRunStatus.NO_DELETE
    assert plan.reason == "keep-delete-boundary-tie"
    assert plan.planned_delete_ids == ()


def test_rfc3339_equivalent_instants_are_accepted() -> None:
    item = snapshot(
        1,
        tags={**snapshot(1).tags, "WishicraftCreatedAt": "2026-09-07T13:00:00+01:00"},
    )
    proof = provenance(item, requested_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC))
    result = classify_inventory([item], {item.snapshot_id: proof}, context=CONTEXT)
    assert result[0].disposition is SnapshotDisposition.KEEP


def test_recycle_bin_unknown_blocks_planning_and_states_are_explicit() -> None:
    items = [snapshot(i) for i in range(8)]
    plan = plan_retention(
        items, proofs(items), context=CONTEXT, recycle_bin_preflight_complete=False
    )
    assert plan.status is RetentionRunStatus.NO_DELETE
    assert plan.reason == "recycle-bin-unknown"
    assert plan.planned_delete_ids == ()
    assert set(RecycleBinState) == {
        RecycleBinState.NOT_APPLICABLE,
        RecycleBinState.ACTIVE_DELETED,
        RecycleBinState.RECYCLE_BIN_RETAINED,
        RecycleBinState.FULLY_PURGED_OR_NOT_RETAINED,
        RecycleBinState.OUTCOME_UNKNOWN,
    }


def test_unknown_delete_outcome_only_allows_same_target_bounded_retry_after_revalidation() -> None:
    assert (
        reconcile_delete_outcome(
            DeleteRequestOutcome.OUTCOME_UNKNOWN,
            exists_after_request=True,
            lock_owned=True,
            predicate_still_valid=True,
            membership_still_valid=True,
            retry_count=0,
        )
        is DeleteReconciliation.STILL_PRESENT_RETRY_ELIGIBLE
    )
    assert (
        reconcile_delete_outcome(
            DeleteRequestOutcome.OUTCOME_UNKNOWN,
            exists_after_request=True,
            lock_owned=True,
            predicate_still_valid=True,
            membership_still_valid=True,
            retry_count=1,
        )
        is DeleteReconciliation.STILL_PRESENT_STOPPED
    )
    assert (
        reconcile_delete_outcome(
            DeleteRequestOutcome.OUTCOME_UNKNOWN,
            exists_after_request=False,
            lock_owned=True,
            predicate_still_valid=True,
            membership_still_valid=True,
            retry_count=0,
        )
        is DeleteReconciliation.ACTIVE_ABSENT
    )


def test_fake_delete_adapter_has_no_aws_dependency() -> None:
    adapter = FakeSnapshotDeleteAdapter(DeleteRequestOutcome.EXPLICIT_SUCCESS, [])
    assert (
        adapter.delete_once(snapshot_id="snap-00000000000000001")
        is DeleteRequestOutcome.EXPLICIT_SUCCESS
    )
    assert adapter.calls == ["snap-00000000000000001"]


class Pages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def describe_snapshots(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        item = snapshot(len(self.calls))
        raw = {
            "SnapshotId": item.snapshot_id,
            "VolumeId": item.source_volume_id,
            "State": item.state,
            "OwnerId": item.owner_id,
            "StartTime": item.start_time,
            "Description": item.description,
            "Tags": [{"Key": key, "Value": value} for key, value in item.tags.items()],
        }
        return {"Snapshots": [raw], **({"NextToken": "page-2"} if len(self.calls) == 1 else {})}


def test_inventory_consumes_all_pages_with_owner_scope() -> None:
    api = Pages()
    result = load_complete_inventory(api, owner_id="123")
    assert len(result) == 2
    assert api.calls == [
        {"OwnerIds": ["123"], "MaxResults": 1000},
        {"OwnerIds": ["123"], "MaxResults": 1000, "NextToken": "page-2"},
    ]


def test_duplicate_operation_metadata_blocks_run() -> None:
    items = [snapshot(i) for i in range(8)]
    items[0] = snapshot(
        0,
        description="Wishicraft backup op-1",
        tags={**snapshot(0).tags, "WishicraftOperationId": "op-1"},
    )
    p = proofs(items)
    p[items[0].snapshot_id] = provenance(items[0])
    plan = plan_retention(items, p, context=CONTEXT, recycle_bin_preflight_complete=True)
    assert plan.status is RetentionRunStatus.NO_DELETE
    assert plan.reason == "duplicate-operation-provenance"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"state": "pending"}, "aws-attribute-mismatch"),
        ({"owner_id": "other"}, "aws-attribute-mismatch"),
        ({"source_volume_id": "vol-other"}, "aws-attribute-mismatch"),
    ],
)
def test_relevant_inventory_attribute_anomalies_block(
    change: dict[str, object], reason: str
) -> None:
    item = snapshot(1, **change)
    result = classify_inventory([item], {item.snapshot_id: provenance(item)}, context=CONTEXT)
    assert result[0].disposition is SnapshotDisposition.ANOMALY
    assert result[0].reason == reason
