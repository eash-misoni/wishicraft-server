"""Release-owned exact historical reconciliation. No operator-file input or ID waiver."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from wishicraft.backup_recovery import recovery_digest
from wishicraft.retention import RetentionContext, parse_rfc3339

REVISION = "c6845d2a565c644be3b73ef9a5760f669444e2e343fc3e6eee1a287dcd370d18"
HOLD_REVISION = "live-journals-protection-classifier-v1"


def _authority() -> dict[str, Any]:
    raw = Path(__file__).with_name("retention_historical_authority.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != REVISION:
        raise ValueError("HISTORICAL_AUTHORITY_CHANGED")
    return json.loads(raw)  # type: ignore[no-any-return]


def reviewed_failure(
    row: dict[str, Any],
    *,
    context: RetentionContext,
    region: str,
    system: str,
    snapshots: list[dict[str, Any]],
    provenance: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> bool:
    """Raw FAILED findings remain in the collector. Only this exact execution is reviewed.

    All arguments are fresh in-memory service reads, not serialized completeness claims.
    The source table account binding is independently checked by ExecutionReads.
    """
    try:
        authority = _authority()
        if [context.owner_id, region, system, context.source_volume_id, context.stage] != [
            authority[k] for k in ("account", "region", "system", "volume", "stage")
        ]:
            return False
        expected = next(
            r for r in authority["operations"] if r["operation_id"] == row.get("operation_id")
        )
        op = expected["operation_id"]
        for key in (
            "operation_id",
            "operation_type",
            "status",
            "target_game_id",
            "workflow_execution_arn",
            "backup_create_intent",
        ):
            if row.get(key) != expected[key]:
                return False
        for key in ("requested_at", "completed_at"):
            if parse_rfc3339(row[key]) != parse_rfc3339(expected[key]):
                return False
        if row.get("workflow_execution_name") != op or row.get("error") != {
            "code": expected["error_code"],
            "message": None,
            "detail_ref": None,
            "retryable": None,
        }:
            return False
        # Unexpected result or even an unknown snapshot-reference field fails closed.
        if row.get("result") is not None or row.get("system_id", system) != system:
            return False

        def contains_reference(value: Any) -> bool:
            if isinstance(value, dict):
                return any(
                    ((k == "snapshot_id" or k.endswith("_snapshot_id")) and v is not None)
                    or (
                        k not in {"backup_recovery_json", "runtime_env", "compose"}
                        and contains_reference(v)
                    )
                    for k, v in value.items()
                )
            if isinstance(value, list):
                return any(contains_reference(v) for v in value)
            return False

        if contains_reference(row):
            return False
        intent = expected["backup_create_intent"]
        if intent is not None:
            if recovery_digest(row["backup_recovery_json"]) != intent["WishicraftRecoveryDigest"]:
                return False
        elif row.get("backup_recovery_json") is not None:
            return False
        if any(
            any(
                t.get("Key") == "WishicraftOperationId" and t.get("Value") == op
                for t in s.get("Tags", [])
            )
            for s in snapshots
        ):
            return False

        # Any new provenance/deletion/reference mentioning this operation requires review.
        def mentions(value: Any) -> bool:
            if isinstance(value, str):
                return value == op or value in {"OPERATION#" + op, "RETENTION#" + op}
            if isinstance(value, dict):
                return any(mentions(v) for v in value.values())
            if isinstance(value, list):
                return any(mentions(v) for v in value)
            return False

        return not mentions(provenance) and not mentions(references)
    except Exception:
        return False
