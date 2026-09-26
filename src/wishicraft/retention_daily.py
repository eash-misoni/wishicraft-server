"""Explicit days14-or-newest7-v1 offline dry-run policy; no deletion adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from wishicraft.retention import (
    BackupProvenance,
    InventorySnapshot,
    RetentionContext,
    RetentionRunStatus,
    classify_inventory,
    plan_retention,
)

POLICY = "days14-or-newest7-v1"


@dataclass(frozen=True)
class ProtectionInventory:
    """Reviewed references from journals AND explicit historical retention evidence.

    Completeness is an external operator proof, never inferred from protected tags.
    A snapshot is protected by any reason; these entries do not consume seven slots.
    """

    reasons: dict[str, tuple[str, ...]]
    complete: bool = False


@dataclass(frozen=True)
class DailyRetentionPlan:
    policy: str
    status: RetentionRunStatus
    reason: str
    classifications: dict[str, str]
    keep_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]
    # This policy cannot produce executable deletion plans.
    planned_delete_ids: tuple[str, ...] = ()


def plan(
    snapshots: list[InventorySnapshot],
    provenances: dict[str, BackupProvenance],
    *,
    context: RetentionContext,
    now: datetime,
    protections: ProtectionInventory,
    inventory_complete: bool,
    recycle_bin_preflight_complete: bool,
) -> DailyRetentionPlan:
    reasons: dict[str, str] = {}
    protected: list[str] = []
    normal: list[InventorySnapshot] = []
    blocked = ""
    if now.tzinfo is None:
        raise ValueError("UTC-aware evaluation time required")
    if not context.shared_volume:
        blocked = "shared-volume-required"
    if not inventory_complete or not protections.complete:
        blocked = "protection-or-snapshot-inventory-incomplete"
    if len({s.snapshot_id for s in snapshots}) != len(snapshots):
        blocked = "duplicate-snapshot"
    for item in snapshots:
        try:
            if item.start_time.tzinfo is None or item.start_time > now:
                raise ValueError("invalid time")
            classified = classify_inventory([item], provenances, context=context)[0]
        except (ValueError, TypeError):
            reasons[item.snapshot_id] = "ANOMALY:invalid-acquisition-time"
            blocked = "inventory-anomaly"
            continue
        refs = protections.reasons.get(item.snapshot_id)
        if refs:
            protected.append(item.snapshot_id)
            reasons[item.snapshot_id] = "PROTECTED:" + ",".join(refs)
        elif classified.disposition == "KEEP":
            normal.append(item)
        else:
            reasons[item.snapshot_id] = classified.disposition + ":" + classified.reason
            if classified.disposition == "ANOMALY":
                blocked = "inventory-anomaly"
    # Preserve the deployed policy's ambiguous seventh-place rule without weakening it.
    baseline = plan_retention(
        normal,
        provenances,
        context=context,
        recycle_bin_preflight_complete=recycle_bin_preflight_complete,
    )
    if baseline.status == RetentionRunStatus.NO_DELETE:
        blocked = baseline.reason
    cutoff = now - timedelta(days=14)
    keep = []
    candidates = []
    for item in normal:
        newest = item.snapshot_id in baseline.keep_ids
        recent = item.start_time >= cutoff
        if newest or recent or blocked:
            keep.append(item.snapshot_id)
            reasons[item.snapshot_id] = "KEEP:" + (
                "safety-hold:" + blocked
                if blocked
                else "within-14-days-and-newest-seven"
                if newest and recent
                else "within-14-days"
                if recent
                else "newest-seven"
            )
        else:
            candidates.append(item.snapshot_id)
            reasons[item.snapshot_id] = "CANDIDATE:older-than-14-days-and-outside-newest-seven"
    return DailyRetentionPlan(
        POLICY,
        RetentionRunStatus.NO_DELETE if blocked else RetentionRunStatus.DRY_RUN,
        blocked or "dry-run-only",
        reasons,
        tuple(keep),
        tuple(candidates),
        tuple(protected),
    )
