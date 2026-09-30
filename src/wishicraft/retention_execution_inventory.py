"""In-memory, fresh execution predicates. Not an offline-file authorization parser."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from wishicraft.retention import (
    BackupProvenance,
    InventorySnapshot,
    RetentionContext,
    _parse_inventory_snapshot,
    classify_inventory,
)
from wishicraft.retention_daily import DailyRetentionPlan, ProtectionInventory, plan
from wishicraft.retention_deletion import classify_absence, split_deletion_records
from wishicraft.retention_provenance import provenance_pairs
from wishicraft.retention_references import (
    GAME,
    OPERATION,
    SNAPSHOT,
    game_references,
    identifier,
    journal_references,
    protection_references,
)

MAX_READ_AGE = timedelta(seconds=30)


@dataclass(frozen=True)
class FreshInventory:
    """Produced under an admitted RETENTION lock, never deserialized from operator JSON.

    Raw recovery is validated before minimization; no raw object is persisted or hashed.
    Completeness failures are a tuple of fixed issues from the trusted reader, not a
    caller-supplied complete flag. No production reader/factory is enabled in this slice.
    """

    context: RetentionContext
    region: str
    system_id: str
    observed_at: datetime
    snapshots: tuple[InventorySnapshot, ...]
    proofs: dict[str, BackupProvenance]
    holds: dict[str, tuple[str, ...]]
    reference_revision: str
    aws_revision: str
    issues: tuple[str, ...]
    management_findings: tuple[tuple[str | None, str, bool], ...] = ()

    def policy(self, now: datetime) -> DailyRetentionPlan:
        return plan(
            list(self.snapshots),
            self.proofs,
            context=self.context,
            now=now,
            protections=ProtectionInventory(self.holds, complete=not self.issues),
            inventory_complete=not self.issues,
            recycle_bin_preflight_complete=not self.issues,
        )

    def identity(self, now: datetime) -> str:
        if (
            now.tzinfo is None
            or self.observed_at.tzinfo is None
            or not timedelta(0) <= now - self.observed_at <= MAX_READ_AGE
            or self.issues
        ):
            raise ValueError("RETENTION_READ_UNKNOWN_OR_STALE")
        # Only public validated attributes. No descriptions, recovery body, Game package,
        # environment/hash, access/players, exception body or arbitrary tags are persisted.
        entries = []
        for s in sorted(self.snapshots, key=lambda s: s.snapshot_id):
            p = self.proofs.get(s.snapshot_id)
            entries.append(
                [
                    s.snapshot_id,
                    s.source_volume_id,
                    s.owner_id,
                    s.state,
                    s.start_time.isoformat(),
                    s.storage_tier,
                    s.lock_state,
                    p.operation_id if p else None,
                    p.recovery_digest if p else None,
                ]
            )
        return digest(
            [
                self.context.project,
                self.context.stage,
                self.context.owner_id,
                self.context.source_volume_id,
                self.region,
                self.system_id,
                entries,
                sorted(self.holds.items()),
                self.reference_revision,
                self.aws_revision,
                sorted(self.policy(now).candidate_ids),
            ]
        )


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_inventory(
    *,
    context: RetentionContext,
    region: str,
    system_id: str,
    operation_id: str,
    now: datetime,
    snapshots: list[dict[str, Any]],
    provenance_wire: list[dict[str, Any]],
    provenance_rows: list[dict[str, Any]],
    state: dict[str, Any],
    journals: list[dict[str, Any]],
    games: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    special_holds: dict[str, tuple[str, ...]],
    hold_revision: str,
    aws_revision: str,
    read_issues: tuple[str, ...],
    historical_authority: bool = False,
    recovery_snapshot_id: str | None = None,
    authority_snapshots: list[dict[str, Any]] | None = None,
) -> FreshInventory:
    """Trusted reader's raw responses in memory. Every missing domain must be an issue.

    The future binding must acquire all pages, validate exact caller/region/volume and
    AWS constraints and supply only reviewed server-owned holds. Arbitrary input files
    cannot construct this through any deployed handler or operator CLI.
    """
    sid: str | None
    issues = list(read_issues)
    if not context.shared_volume or state.get("system_id") != system_id:
        issues.append("invalid-scope")
    if state.get("current_operation_id") != operation_id:
        issues.append("operation-ownership-changed")
    if state.get("maintenance") is not None and state["maintenance"].get("status") != "ENDED":
        issues.append("maintenance-open")
    if not hold_revision or not aws_revision:
        issues.append("missing-reviewed-authority")
    try:
        _, deletes = split_deletion_records(provenance_rows)
    except ValueError:
        deletes = {}
        issues.append("invalid-deletion-pair")
    pairs = [
        (w, r)
        for w, r in zip(provenance_wire, provenance_rows, strict=True)
        if r.get("record_type") not in {"RETENTION_DELETION", "RETENTION_DELETION_UNIQUENESS"}
    ]
    proofs, _, pair_issues = provenance_pairs([w for w, _ in pairs], [r for _, r in pairs], context)
    issues.extend(pair_issues)
    game_view, gi = game_references(games)
    issues.extend(gi)
    holds, journal_view, ji = journal_references(
        journals,
        system=system_id,
        stage=context.stage,
        project=context.project,
        volume=context.source_volume_id,
        games={g["game_id"] for g in games if identifier(g.get("game_id"), GAME)},
    )
    issues.extend(ji)
    ph, pi = protection_references(state)
    issues.extend(pi)
    for refs in (special_holds, ph):
        for sid, reasons in refs.items():
            if not identifier(sid, SNAPSHOT) or not reasons:
                issues.append("invalid-hold")
            holds.setdefault(sid, []).extend(reasons)
    bp = state.get("backup_protection", {})
    bp_view = []
    for key in ("last_success", "intent"):
        value = bp.get(key) or {}
        op = identifier(value.get("operation_id"), OPERATION)
        boundary = value.get("boundary")
        if boundary is not None and (type(boundary) is not int or boundary < 0):
            issues.append("invalid-protection-boundary")
            boundary = None
        status = value.get("status")
        if status not in {None, "SUCCEEDED", "FAILED", "UNKNOWN", "ADMITTED", "RESERVED"}:
            issues.append("invalid-protection-status")
            status = "UNKNOWN"
        bp_view.append(
            [
                key,
                op,
                identifier(value.get("snapshot_id"), SNAPSHOT),
                boundary,
                status,
            ]
        )
        for sid, proof in proofs.items():
            if op and proof.operation_id == op:
                holds.setdefault(sid, []).append("backup_protection." + key)
    # Unknown management outcomes remain blockers. Adopted historical explanations are
    # not an ID-only waiver; no resolution-file consumer is introduced.
    op_view: list[tuple[str | None, str, bool]] = []
    for row in operations:
        if row.get("operation_id") == operation_id:
            continue
        if row.get("operation_type") in {"BACKUP", "RETENTION", "RESTORE", "IMPORT"}:
            reviewed = False
            if row.get("status") != "SUCCEEDED" and historical_authority:
                from wishicraft.retention_authority import reviewed_failure

                reviewed = reviewed_failure(
                    row,
                    context=context,
                    region=region,
                    system=system_id,
                    snapshots=snapshots if authority_snapshots is None else authority_snapshots,
                    provenance=provenance_rows,
                    references=[state, *journals, *games],
                )
            if row.get("status") != "SUCCEEDED" and not reviewed:
                issues.append("unresolved-management-operation")
            op_status = row.get("status")
            if op_status not in {
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                "CANCELLED",
            }:
                issues.append("unknown-management-status")
                op_status = "UNKNOWN"
            op_view.append(
                (identifier(row.get("operation_id"), OPERATION), str(op_status), reviewed)
            )
            for key in ("source_snapshot_id", "backup_snapshot_id", "snapshot_id"):
                sid = identifier(row.get(key), SNAPSHOT)
                if sid:
                    holds.setdefault(sid, []).append("management-reference")

    # Only typed snapshot references; archive paths and file digests are not snapshots.
    def game_snapshot_refs(value: object) -> None:
        if isinstance(value, dict):
            for key, v in value.items():
                if key == "snapshot_id" or str(key).endswith("_snapshot_id"):
                    sid = identifier(v, SNAPSHOT)
                    if sid:
                        holds.setdefault(sid, []).append("game-import-reference")
                    elif v is not None:
                        issues.append("invalid-game-snapshot-reference")
                elif key not in {"runtime_env", "env", "recovery_json", "compose"}:
                    game_snapshot_refs(v)
        elif isinstance(value, list):
            for v in value:
                game_snapshot_refs(v)

    game_snapshot_refs(games)
    items: list[InventorySnapshot] = []
    for raw in snapshots:
        try:
            item = _parse_inventory_snapshot(raw)
            if not identifier(item.snapshot_id, SNAPSHOT):
                raise ValueError("identity")
            if raw.get("Encrypted") is not True:
                issues.append("snapshot-encryption-unconfirmed")
            if item.snapshot_id in proofs and (
                item.tags.get("Project") != context.project
                or item.tags.get("Stage") != context.stage
            ):
                issues.append("provenance-scope-tag-mismatch")
            classified = classify_inventory([item], proofs, context=context)[0]
            # Held entries still undergo validation. A hold does not hide corrupt provenance.
            if classified.disposition == "ANOMALY":
                issues.append("snapshot-anomaly")
            items.append(item)
        except (ValueError, TypeError):
            issues.append("invalid-snapshot")
    present = {s.snapshot_id for s in items}
    if len(present) != len(items):
        issues.append("duplicate-snapshot")
    if set(holds) - present:
        issues.append("held-snapshot-missing")
    for sid, proof in proofs.items():
        result = classify_absence(
            proof,
            deletes.get(sid),
            account=context.owner_id,
            region=region,
            system_id=system_id,
            now=now,
            referenced=sid in holds,
            present=sid in present,
        )
        own_pending = (
            sid in deletes
            and deletes[sid].retention_operation_id == operation_id
            and (sid in present or sid == recovery_snapshot_id)
            and result == "DELETION_OUTCOME_UNKNOWN"
        )
        if result in {"ANOMALY", "DELETION_OUTCOME_UNKNOWN"} and not own_pending:
            issues.append("unreconciled-snapshot-absence-or-deletion")
    if set(deletes) - set(proofs):
        issues.append("deletion-without-provenance")
    reference_revision = digest(
        [
            journal_view,
            game_view,
            bp_view,
            op_view,
            hold_revision,
            sorted((k, sorted(v)) for k, v in holds.items()),
        ]
    )
    return FreshInventory(
        context,
        region,
        system_id,
        now,
        tuple(items),
        proofs,
        {k: tuple(v) for k, v in holds.items()},
        reference_revision,
        aws_revision,
        tuple(issues),
        tuple(op_view),
    )
