"""Value-minimized local inventory projection, never a deletion authorization."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from tools.retention_references import SNAPSHOT, identifier
from wishicraft.backup import REQUIRED_TAG_KEYS
from wishicraft.backup_recovery import SHARED_TAG_KEYS
from wishicraft.retention import (
    BackupProvenance,
    RetentionContext,
    _parse_inventory_snapshot,
    classify_inventory,
)
from wishicraft.retention_provenance import provenance_pairs as provenance_pairs


def timestamp(value: Any) -> str | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            return dt.astimezone(UTC).isoformat()
    except (ValueError, TypeError):
        pass
    return None


def project_snapshots(
    raw: list[dict[str, Any]],
    provenances: dict[str, BackupProvenance],
    *,
    context: RetentionContext,
    region: str,
    now: datetime,
    holds: dict[str, list[str]],
    locks: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    counts = Counter(str(r.get("SnapshotId")) for r in raw)
    for value in raw:
        sid = identifier(value.get("SnapshotId"), SNAPSHOT)
        volume = identifier(value.get("VolumeId"), r"vol-[0-9a-f]{8,17}")
        owner = identifier(value.get("OwnerId"), r"[0-9]{12}")
        row: dict[str, Any] = dict(
            snapshot_id=sid,
            owner_id=owner,
            region=region,
            source_volume_id=volume,
            target_volume=volume == context.source_volume_id and owner == context.owner_id,
            acquired_at_utc=timestamp(value.get("StartTime")),
            acquired_at_jst=None,
            age_seconds=None,
            encrypted=value.get("Encrypted") is True,
            state=value.get("State")
            if value.get("State") in {"pending", "completed", "error", "recoverable", "recovering"}
            else "UNKNOWN",
            storage_tier=value.get("StorageTier", "standard")
            if value.get("StorageTier", "standard") in {"standard", "archive"}
            else "UNKNOWN",
            lock_state=locks.get(sid or "", "none-observed"),
            category="UNKNOWN",
            scope="UNKNOWN",
            provenance_pair_valid=sid in provenances,
            holds=list(holds.get(sid or "", [])),
            integrity_issues=[],
            reasons=[],
            normal_eligible=False,
            classification="ANOMALY",
        )
        try:
            item = _parse_inventory_snapshot(value)
            tags = item.tags
            row["category"] = (
                tags.get("WishicraftCategory")
                if tags.get("WishicraftCategory") in {"backup", "migration"}
                else "unclaimed-or-unknown"
            )
            row["scope"] = (
                "shared-volume"
                if tags.get("WishicraftBackupScope") == "shared-volume"
                else "legacy-or-unknown"
            )
            # No arbitrary descriptions/tag values, recovery content or its hashes are stored.
            row["description_matches_operation"] = item.description == (
                "Wishicraft backup " + tags.get("WishicraftOperationId", "")
            )
            prov = provenances.get(sid or "")
            if prov and (
                set(tags)
                != (
                    REQUIRED_TAG_KEYS | SHARED_TAG_KEYS
                    if prov.schema_version == 2
                    else REQUIRED_TAG_KEYS
                )
                or tags.get("WishicraftProtected") != "false"
                or tags.get("Project") != context.project
                or tags.get("WishicraftCategory") != "backup"
                or tags.get("WishicraftSchemaVersion") != str(prov.schema_version)
                or timestamp(tags.get("WishicraftCreatedAt"))
                != prov.wishicraft_created_at.isoformat()
                or item.state != "completed"
                or not row["description_matches_operation"]
                or item.owner_id != context.owner_id
                or prov.snapshot_start_time != item.start_time
                or prov.operation_id != tags.get("WishicraftOperationId")
                or prov.source_volume_id != volume
                or prov.stage != tags.get("Stage")
                or prov.game_id != tags.get("WishicraftGameId")
                or (
                    prov.schema_version == 2
                    and prov.recovery_digest != tags.get("WishicraftRecoveryDigest")
                )
            ):
                row["integrity_issues"].append("actual-snapshot-provenance-mismatch")
            classified = classify_inventory([item], provenances, context=context)[0]
            row["reasons"].append(classified.reason)
            row["classification"] = str(classified.disposition)
            if row["acquired_at_utc"] is None or item.start_time > now:
                row["integrity_issues"].append("invalid-or-future-acquisition-time")
            else:
                row["acquired_at_jst"] = item.start_time.astimezone(
                    timezone(timedelta(hours=9))
                ).isoformat()
                row["age_seconds"] = (now - item.start_time).total_seconds()
            if sid is None or counts[str(sid)] != 1:
                row["integrity_issues"].append("invalid-or-duplicate-snapshot-id")
            if not row["target_volume"]:
                row["classification"] = "EXCLUDED"
                row["reasons"].append("outside-canonical-owner-volume")
            elif tags.get("Project") != context.project or tags.get("Stage") != context.stage:
                row["classification"] = "EXCLUDED"
                row["reasons"].append("unclaimed-or-other-project-stage")
            else:
                if tags.get("WishicraftCategory") == "backup" and sid not in provenances:
                    row["integrity_issues"].append("missing-or-invalid-provenance-pair")
                if classified.disposition == "ANOMALY":
                    row["integrity_issues"].append(classified.reason)
                if value.get("Encrypted") is not True:
                    row["integrity_issues"].append("encryption-not-confirmed")
                if tags.get("WishicraftProtected") == "true":
                    row["holds"].append("explicit-protected-tag")
                if tags.get("WishicraftCategory") == "migration":
                    row["holds"].append("migration-anchor")
                if row["lock_state"] != "none-observed":
                    row["holds"].append("snapshot-lock")
                row["normal_eligible"] = (
                    classified.disposition == "KEEP"
                    and not row["holds"]
                    and not row["integrity_issues"]
                )
            if row["holds"]:
                row["classification"] = "PROTECTED"
            if row["integrity_issues"]:
                row["classification"] = "ANOMALY"
        except (ValueError, TypeError, KeyError):
            row["integrity_issues"].append("strict-snapshot-parser-rejected")
        rows.append(row)
    return rows


def policy_projection(rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Arithmetic only on recorded validated normal cohort; does not assert completeness."""
    normal = sorted(
        (r for r in rows if r["normal_eligible"]),
        key=lambda r: datetime.fromisoformat(r["acquired_at_utc"]),
        reverse=True,
    )
    times = [datetime.fromisoformat(r["acquired_at_utc"]) for r in normal]
    tie = len(times) > 7 and times[6] == times[7]
    old, new = [], []
    for row in rows:
        row.update(
            normal_rank=None,
            within_14_days=(0 <= row["age_seconds"] <= 14 * 86400)
            if isinstance(row.get("age_seconds"), (int, float))
            else None,
            newest_seven=None,
            old_policy_projection="NOT_NORMAL",
            new_policy_projection="NOT_NORMAL",
        )
    for index, row in enumerate(normal):
        recent = now - times[index] <= timedelta(days=14)
        newest = index < 7
        old_candidate = not newest and not tie
        new_candidate = old_candidate and not recent
        row.update(
            normal_rank=index + 1,
            within_14_days=recent,
            newest_seven=newest,
            old_policy_projection="OUTSIDE_SEVEN" if old_candidate else "KEEP",
            new_policy_projection="OUTSIDE_14D_OR_SEVEN" if new_candidate else "KEEP",
        )
        if tie:
            row["reasons"].append("ambiguous-seventh-boundary-no-projected-candidates")
        if old_candidate:
            old.append(row["snapshot_id"])
        if new_candidate:
            new.append(row["snapshot_id"])
    return dict(
        label="UNAPPROVED_POLICY_PROJECTION_NOT_SAFE_DELETE_CANDIDATES",
        cohort="validated normal shared-volume; separate holds do not consume seven",
        old_newest_seven_outside_ids=old,
        new_14d_or_seven_outside_ids=new,
        boundary_tie=tie,
        normal_count=len(normal),
    )
