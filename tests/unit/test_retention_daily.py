from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.test_retention import CONTEXT, provenance, snapshot
from wishicraft.retention import BackupProvenance, InventorySnapshot, RetentionRunStatus
from wishicraft.retention_daily import ProtectionInventory, plan

NOW = datetime(2026, 10, 1, tzinfo=UTC)
CONTEXT_SHARED = replace(CONTEXT, shared_volume=True)


def inventory(ages: list[timedelta]) -> tuple[list[InventorySnapshot], dict[str, BackupProvenance]]:
    items = []
    proofs = {}
    for i, age in enumerate(ages):
        time = NOW - age
        item = snapshot(i, start_time=time)
        tags = {
            **item.tags,
            "WishicraftSchemaVersion": "2",
            "WishicraftBackupScope": "shared-volume",
            "WishicraftRecoveryDigest": "f" * 64,
            "WishicraftCreatedAt": time.isoformat().replace("+00:00", "Z"),
            "WishicraftGameId": "game-a" if i % 2 else "game-b",
        }
        item = replace(item, tags=tags)
        proofs[item.snapshot_id] = provenance(
            item, schema_version=2, recovery_digest="f" * 64, game_id=tags["WishicraftGameId"]
        )
        items.append(item)
    return items, proofs


def run(
    ages: list[timedelta],
    *,
    complete: bool = True,
    protected: dict[str, tuple[str, ...]] | None = None,
) -> object:
    items, proofs = inventory(ages)
    return plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory(protected or {}, complete=complete),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )


def test_fourteen_days_or_seven_shared_not_per_game() -> None:
    items, proofs = inventory([timedelta(days=i) for i in range(20)])
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert len(p.keep_ids) == 15 and len(p.candidate_ids) == 5
    assert p.planned_delete_ids == ()
    assert p.status == RetentionRunStatus.DRY_RUN


@pytest.mark.parametrize("count", [0, 1, 6, 7])
def test_at_least_seven_even_when_older(count: int) -> None:
    items, proofs = inventory([timedelta(days=20 + i) for i in range(count)])
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert len(p.keep_ids) == count and not p.candidate_ids


@pytest.mark.parametrize(
    "age,kept", [(timedelta(days=14), True), (timedelta(days=14, microseconds=1), False)]
)
def test_utc_exact_boundary_kept(age: timedelta, kept: bool) -> None:
    items, proofs = inventory([timedelta(hours=i) for i in range(7)] + [age])
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert (items[-1].snapshot_id in p.keep_ids) is kept


def test_seventh_tie_still_blocks_entire_plan() -> None:
    items, proofs = inventory([timedelta(days=20)] * 8)
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert p.status == RetentionRunStatus.NO_DELETE and not p.candidate_ids
    assert p.reason == "keep-delete-boundary-tie"


@pytest.mark.parametrize(
    "kind",
    ["reference-incomplete", "inventory-incomplete", "provenance-incomplete", "future", "naive"],
)
def test_uncertainty_never_certifies_candidates(kind: str) -> None:
    items, proofs = inventory([timedelta(days=20 + i) for i in range(10)])
    if kind == "provenance-incomplete":
        proofs.pop(items[0].snapshot_id)
    if kind == "future":
        items[0] = replace(items[0], start_time=NOW + timedelta(seconds=1))
    if kind == "naive":
        items[0] = replace(items[0], start_time=NOW.replace(tzinfo=None))
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, kind != "reference-incomplete"),
        inventory_complete=kind != "inventory-incomplete",
        recycle_bin_preflight_complete=True,
    )
    assert p.status == RetentionRunStatus.NO_DELETE and not p.candidate_ids


def test_external_journal_protection_does_not_reduce_seven_normal() -> None:
    items, proofs = inventory([timedelta(days=20 + i) for i in range(10)])
    holds: dict[str, tuple[str, ...]] = {
        items[0].snapshot_id: ("RESTORE_SOURCE:unfinished",),
        items[1].snapshot_id: ("historical-proof-hold",),
    }
    p = plan(
        items,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory(holds, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert len(p.protected_ids) == 2 and len(p.keep_ids) == 7 and len(p.candidate_ids) == 1


def test_legacy_migration_manual_protected_remain_separate() -> None:
    items, proofs = inventory([timedelta(days=20 + i) for i in range(10)])
    legacy = snapshot(40)
    others = [
        legacy,
        replace(snapshot(41), tags={"WishicraftCategory": "migration"}),
        replace(snapshot(42), tags={}),
        replace(snapshot(43), tags={"WishicraftProtected": "true"}),
    ]
    proofs[legacy.snapshot_id] = provenance(legacy)
    p = plan(
        items + others,
        proofs,
        context=CONTEXT_SHARED,
        now=NOW,
        protections=ProtectionInventory({}, True),
        inventory_complete=True,
        recycle_bin_preflight_complete=True,
    )
    assert len(p.keep_ids) == 7 and len(p.candidate_ids) == 3
    assert all(p.classifications[s.snapshot_id].startswith("EXCLUDED:") for s in others)
