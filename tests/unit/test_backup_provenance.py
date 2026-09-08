from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from wishicraft.backup import SnapshotRecord
from wishicraft.backup_provenance import (
    BackupOperationEvidence,
    BackupProvenanceRecord,
    BackupProvenanceRepository,
    build_verified_provenance,
)

NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)


class Dynamo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {}

    def get_item(self, **kwargs: object) -> object:
        key = kwargs["Key"]
        assert isinstance(key, dict)
        value = key["provenance_key"]
        assert isinstance(value, dict)
        item = self.items.get(str(value["S"]))
        return {"Item": item} if item is not None else {}

    def transact_write_items(self, **kwargs: object) -> object:
        writes = kwargs["TransactItems"]
        assert isinstance(writes, list)
        for write in writes:
            put = write["Put"]
            key = str(put["Item"]["provenance_key"]["S"])
            if key in self.items:
                raise RuntimeError("conditional conflict")
        for write in writes:
            put = write["Put"]
            self.items[str(put["Item"]["provenance_key"]["S"])] = put["Item"]
        return {}


def record(**changes: object) -> BackupProvenanceRecord:
    values: dict[str, object] = {
        "snapshot_id": "snap-0123456789abcdef0",
        "operation_id": "op-01234567-89ab-cdef-0123-456789abcdef",
        "game_id": "game-vanilla-main",
        "source_volume_id": "vol-03ac9f534326c345c",
        "stage": "dev",
        "project": "wishicraft",
        "category": "backup",
        "protected": False,
        "snapshot_start_time": NOW,
        "operation_requested_at": NOW - timedelta(seconds=6),
        "wishicraft_created_at": NOW - timedelta(milliseconds=250),
        "provenance_recorded_at": NOW + timedelta(seconds=3),
        "verified_owner_id": "123456789012",
        "metadata": {
            "Project": "wishicraft",
            "Stage": "dev",
            "WishicraftCategory": "backup",
            "WishicraftGameId": "game-vanilla-main",
            "WishicraftOperationId": "op-01234567-89ab-cdef-0123-456789abcdef",
            "WishicraftSourceVolumeId": "vol-03ac9f534326c345c",
            "WishicraftSchemaVersion": "1",
            "WishicraftProtected": "false",
            "WishicraftCreatedAt": (NOW - timedelta(milliseconds=250))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    }
    values.update(changes)
    return BackupProvenanceRecord(**values)  # type: ignore[arg-type]


def test_create_is_two_conditional_non_ttl_uniqueness_records() -> None:
    writes = BackupProvenanceRepository(Dynamo(), table_name="backups").transactional_puts(record())
    assert len(writes) == 2
    puts = [cast(dict[str, object], item["Put"]) for item in writes]
    assert all(
        item["ConditionExpression"] == "attribute_not_exists(provenance_key)" for item in puts
    )
    encoded = str(writes)
    assert "expires_at" not in encoded
    assert "SNAPSHOT#snap-0123456789abcdef0" in encoded
    assert "OPERATION#op-01234567-89ab-cdef-0123-456789abcdef" in encoded


def test_empty_store_is_createable() -> None:
    assert BackupProvenanceRepository(Dynamo(), table_name="backups").assert_createable_or_exact(
        record()
    )


def test_partial_or_conflicting_record_fails_closed() -> None:
    api = Dynamo()
    repository = BackupProvenanceRepository(api, table_name="backups")
    put = cast(dict[str, object], repository.transactional_puts(record())[0]["Put"])
    api.items["SNAPSHOT#snap-0123456789abcdef0"] = cast(dict[str, object], put["Item"])
    with pytest.raises(ValueError, match="conflicting or partial"):
        repository.assert_createable_or_exact(record())


def test_exact_rerun_is_idempotent_even_if_attempt_time_changes() -> None:
    api = Dynamo()
    repository = BackupProvenanceRepository(api, table_name="backups")
    original = record()
    for write in repository.transactional_puts(original):
        put = cast(dict[str, object], write["Put"])
        item = cast(dict[str, object], put["Item"])
        key = cast(dict[str, object], item["provenance_key"])
        api.items[str(key["S"])] = item
    retry = record(provenance_recorded_at=datetime(2026, 9, 8, 1, 3, tzinfo=UTC))
    assert repository.assert_createable_or_exact(retry) is False


def test_existing_pair_recovers_fixed_recorded_at_for_batch_replay() -> None:
    api = Dynamo()
    repository = BackupProvenanceRepository(api, table_name="backups")
    original = record()
    for write in repository.transactional_puts(original):
        put = cast(dict[str, object], write["Put"])
        item = cast(dict[str, object], put["Item"])
        key = cast(dict[str, object], item["provenance_key"])
        api.items[str(key["S"])] = item

    assert (
        repository.existing_recorded_at(original.snapshot_id, original.operation_id)
        == original.provenance_recorded_at
    )


def test_existing_recorded_at_rejects_partial_pair() -> None:
    api = Dynamo()
    repository = BackupProvenanceRepository(api, table_name="backups")
    original = record()
    put = cast(dict[str, object], repository.transactional_puts(original)[0]["Put"])
    api.items[f"SNAPSHOT#{original.snapshot_id}"] = cast(dict[str, object], put["Item"])

    with pytest.raises(ValueError, match="conflicting or partial"):
        repository.existing_recorded_at(original.snapshot_id, original.operation_id)


def test_business_evidence_conflict_is_never_merged() -> None:
    api = Dynamo()
    repository = BackupProvenanceRepository(api, table_name="backups")
    original = record()
    for write in repository.transactional_puts(original):
        put = cast(dict[str, object], write["Put"])
        item = cast(dict[str, object], put["Item"])
        key = cast(dict[str, object], item["provenance_key"])
        api.items[str(key["S"])] = item
    with pytest.raises(ValueError, match="conflicting"):
        repository.assert_createable_or_exact(record(verified_owner_id="999999999999"))


def test_registration_is_atomic_create_and_exact_replay_noop() -> None:
    repository = BackupProvenanceRepository(Dynamo(), table_name="backups")
    assert repository.register(record()) is True
    assert (
        repository.register(record(provenance_recorded_at=datetime(2026, 9, 8, 2, tzinfo=UTC)))
        is False
    )


def test_backfill_requires_exact_snapshot_and_succeeded_operation_evidence() -> None:
    operation_id = "op-01234567-89ab-cdef-0123-456789abcdef"
    tags = {
        "Project": "wishicraft",
        "Stage": "dev",
        "WishicraftCategory": "backup",
        "WishicraftGameId": "game-vanilla-main",
        "WishicraftOperationId": operation_id,
        "WishicraftSourceVolumeId": "vol-03ac9f534326c345c",
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
        "WishicraftCreatedAt": "2026-09-08T01:02:03+00:00",
    }
    snapshot = SnapshotRecord(
        "snap-0123456789abcdef0",
        "vol-03ac9f534326c345c",
        "completed",
        tags,
        "123456789012",
        NOW,
        "standard",
        f"Wishicraft backup {operation_id}",
    )
    result: dict[str, object] = {
        "kind": "BACKUP",
        "backup_id": "backup-01234567-89ab-cdef-0123-456789abcdef",
        "snapshot_id": snapshot.snapshot_id,
        "source_volume_id": snapshot.source_volume_id,
        "game_id": "game-vanilla-main",
        "category": "backup",
    }
    operation = BackupOperationEvidence(
        operation_id, "BACKUP", "SUCCEEDED", NOW - timedelta(seconds=6), result
    )
    built = build_verified_provenance(
        snapshot=snapshot,
        operation=operation,
        project="wishicraft",
        stage="dev",
        game_id="game-vanilla-main",
        source_volume_id=snapshot.source_volume_id,
        owner_id=snapshot.owner_id,
        provenance_recorded_at=NOW + timedelta(seconds=3),
    )
    assert built.operation_id == operation_id
    assert built.operation_requested_at != built.wishicraft_created_at
    with pytest.raises(ValueError, match="incomplete or inconsistent"):
        build_verified_provenance(
            snapshot=snapshot,
            operation=BackupOperationEvidence(operation_id, "BACKUP", "FAILED", NOW, result),
            project="wishicraft",
            stage="dev",
            game_id="game-vanilla-main",
            source_volume_id=snapshot.source_volume_id,
            owner_id=snapshot.owner_id,
            provenance_recorded_at=NOW,
        )


def test_terminalization_builder_accepts_distinct_operation_and_create_intent_times() -> None:
    operation_id = "op-01234567-89ab-cdef-0123-456789abcdef"
    created_at = NOW - timedelta(milliseconds=250)
    tags = {
        "Project": "wishicraft",
        "Stage": "dev",
        "WishicraftCategory": "backup",
        "WishicraftGameId": "game-vanilla-main",
        "WishicraftOperationId": operation_id,
        "WishicraftSourceVolumeId": "vol-03ac9f534326c345c",
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
        "WishicraftCreatedAt": created_at.isoformat().replace("+00:00", "Z"),
    }
    snapshot = SnapshotRecord(
        "snap-0123456789abcdef0",
        "vol-03ac9f534326c345c",
        "completed",
        tags,
        "123456789012",
        NOW,
        "standard",
        f"Wishicraft backup {operation_id}",
    )
    built = build_verified_provenance(
        snapshot=snapshot,
        operation=BackupOperationEvidence(
            operation_id, "BACKUP", "RUNNING", NOW - timedelta(seconds=6), {}
        ),
        project="wishicraft",
        stage="dev",
        game_id="game-vanilla-main",
        source_volume_id=snapshot.source_volume_id,
        owner_id=snapshot.owner_id,
        provenance_recorded_at=NOW + timedelta(seconds=3),
        require_succeeded_operation=False,
    )
    assert built.operation_requested_at == NOW - timedelta(seconds=6)
    assert built.wishicraft_created_at == created_at
    assert built.snapshot_start_time == NOW
