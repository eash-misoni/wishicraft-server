"""Strict durable BACKUP pair validation shared by read-only and execution planning."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

from wishicraft.backup_provenance import BackupProvenanceRecord
from wishicraft.retention import BackupProvenance, RetentionContext
from wishicraft.retention_daily_operator import CapturedProvenance
from wishicraft.retention_references import OPERATION, SNAPSHOT, identifier
from wishicraft.retention_workflow_lambda import _load_complete_provenance


def provenance_pairs(
    wire: list[dict[str, Any]],
    decoded: list[dict[str, Any]],
    context: RetentionContext,
) -> tuple[dict[str, BackupProvenance], list[dict[str, Any]], list[str]]:
    result: dict[str, BackupProvenance] = {}
    audit: list[dict[str, Any]] = []
    issues: list[str] = []
    counts = Counter(str(r.get("provenance_key")) for r in decoded)
    used: set[int] = set()
    for i, row in enumerate(decoded):
        if row.get("record_type") != "BACKUP_PROVENANCE":
            continue
        sid = identifier(row.get("snapshot_id"), SNAPSHOT)
        op = identifier(row.get("operation_id"), OPERATION)
        matches = [
            j
            for j, r in enumerate(decoded)
            if r.get("record_type") == "BACKUP_OPERATION_UNIQUENESS" and r.get("operation_id") == op
        ]
        valid = False
        try:
            if (
                not sid
                or not op
                or row.get("provenance_key") != "SNAPSHOT#" + sid
                or counts["SNAPSHOT#" + sid] != 1
                or len(matches) != 1
            ):
                raise ValueError("pair identity")
            j = matches[0]
            reverse = decoded[j]
            expected = dict(
                provenance_key="OPERATION#" + op,
                record_type="BACKUP_OPERATION_UNIQUENESS",
                schema_version=row.get("schema_version"),
                snapshot_id=sid,
                operation_id=op,
            )
            if reverse != expected:
                raise ValueError("reverse identity")
            parsed = _load_complete_provenance(
                cast(Any, CapturedProvenance([wire[i], wire[j]])), "captured", context
            )
            proof = parsed[sid]
            record = BackupProvenanceRecord(
                sid,
                op,
                proof.game_id,
                context.source_volume_id,
                context.stage,
                context.project,
                "backup",
                False,
                proof.snapshot_start_time,
                proof.operation_requested_at,
                proof.wishicraft_created_at,
                proof.provenance_recorded_at,
                context.owner_id,
                row["metadata"],
                schema_version=proof.schema_version,
                recovery_json=row.get("recovery_json"),
            )
            if row != record.snapshot_item():
                raise ValueError("snapshot provenance identity or evidence mismatch")
            result.update(parsed)
            valid = True
            used.add(j)
        except (ValueError, TypeError, KeyError, AssertionError):
            issues.append("invalid-provenance-pair:" + (sid or "invalid-id"))
        used.add(i)
        audit.append(
            dict(
                snapshot_id=sid,
                operation_id=op,
                pair_valid=valid,
                schema_version=row.get("schema_version")
                if type(row.get("schema_version")) is int
                else None,
                validation="original values in memory; recovery not persisted",
            )
        )
    for i, row in enumerate(decoded):
        if i not in used:
            issues.append("orphan-or-unknown-provenance-record")
            audit.append(
                dict(
                    snapshot_id=identifier(row.get("snapshot_id"), SNAPSHOT),
                    operation_id=identifier(row.get("operation_id"), OPERATION),
                    pair_valid=False,
                    validation="orphan-or-unknown",
                )
            )
    return result, audit, issues
