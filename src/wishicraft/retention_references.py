"""D-115 reference validation; never changes journals or releases holds."""

from __future__ import annotations

import re
from typing import Any

from wishicraft.restore_source import request_operation

SNAPSHOT = r"snap-[0-9a-f]{8,17}"
OPERATION = r"op-[A-Za-z0-9._:-]{1,124}"
GAME = r"game-[a-z0-9-]{1,100}"


def identifier(value: object, pattern: str) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else None


def journal_references(
    records: list[dict[str, Any]],
    *,
    system: str,
    stage: str,
    project: str,
    volume: str,
    games: set[str],
) -> tuple[dict[str, list[str]], list[dict[str, Any]], list[str]]:
    holds: dict[str, list[str]] = {}
    projections: list[dict[str, Any]] = []
    issues: list[str] = []
    for row in records:
        key = row.get("system_id")
        if row.get("record_type") != "RESTORE" and not str(key).startswith("restore#"):
            continue
        plan = row.get("plan")
        plan = plan if isinstance(plan, dict) else {}
        op = identifier(plan.get("operation_id"), OPERATION)
        phase = row.get("phase") if isinstance(row.get("phase"), str) else "UNKNOWN"
        source = identifier(plan.get("source_snapshot_id"), SNAPSHOT)
        protection = row.get("pre_restore_backup")
        protection = protection if isinstance(protection, dict) else {}
        pre = identifier(protection.get("snapshot_id"), SNAPSHOT)
        request = plan.get("request_id")
        valid = (
            row.get("record_type") == "RESTORE"
            and op is not None
            and key == "restore#" + op
            and type(plan.get("schema_version")) is int
            and plan.get("schema_version") == 1
            and plan.get("kind") == "RESTORE"
            and plan.get("system_id") == system
            and plan.get("stage") == stage
            and plan.get("project") == project
            and plan.get("source_volume_id") == volume
            and identifier(plan.get("game_id"), GAME) in games
            and source is not None
            and pre is not None
            and type(row.get("revision")) is int
            and row["revision"] >= 1
            and phase in {"PLANNED", "PREPARED", "COMMITTED", "ROLLED_BACK"}
            and isinstance(request, str)
        )
        if valid and isinstance(request, str):
            try:
                valid = request_operation(system, stage, request) == op
            except (ValueError, TypeError):
                valid = False
        label = "restore#" + op if op else "invalid-journal-identity"
        if not valid:
            issues.append("invalid-restore-journal:" + label)
        # Even malformed records' syntactically valid references remain tentative holds.
        for sid, role in [(source, "source"), (pre, "pre-restore-protection")]:
            if sid:
                holds.setdefault(sid, []).append(
                    ("journal:" if valid else "unverified-journal:") + label + ":" + role
                )
        projections.append(
            {
                "journal_key": label,
                "operation_id": op,
                "revision": row.get("revision") if type(row.get("revision")) is int else None,
                "phase": phase
                if phase in {"PLANNED", "PREPARED", "COMMITTED", "ROLLED_BACK"}
                else "UNKNOWN",
                "identity_valid": valid,
                "game_id": identifier(plan.get("game_id"), GAME),
                "source_snapshot_id": source,
                "pre_restore_snapshot_id": pre,
                "release_condition": "no automatic release, including PLANNED and ROLLED_BACK",
            }
        )
    return holds, projections, issues


def manifest_references(
    document: dict[str, Any],
    *,
    account: str,
    region: str,
    snapshot_ids: set[str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Only a proposed review artifact is accepted; it cannot authorize any deletion."""
    if (
        document.get("schema_version") != 1
        or document.get("review_status") != "PROPOSED"
        or document.get("account_id") != account
        or document.get("region") != region
        or not isinstance(document.get("entries"), list)
    ):
        raise ValueError("invalid proposed hold manifest")
    holds: dict[str, list[str]] = {}
    issues = ["historical-hold-manifest-unreviewed"]
    seen: set[str] = set()
    for entry in document["entries"]:
        if not isinstance(entry, dict):
            issues.append("invalid-hold-entry")
            continue
        sid = identifier(entry.get("snapshot_id"), SNAPSHOT)
        kind = entry.get("kind")
        evidence = entry.get("evidence", {})
        valid = (
            sid is not None
            and sid not in seen
            and kind
            in {
                "explicit-retention",
                "provisional-review",
                "historical-non-deletion",
                "ownership-only",
            }
            and isinstance(evidence, dict)
            and identifier(evidence.get("commit"), r"[0-9a-f]{40}") is not None
            and isinstance(evidence.get("path"), str)
            and evidence["path"].startswith("docs/")
            and bool(evidence.get("section"))
            and bool(entry.get("reason"))
            and "release_condition" in entry
        )
        if sid:
            seen.add(sid)
            if sid not in snapshot_ids:
                issues.append("manifest-snapshot-missing:" + sid)
            if not valid or kind in {"explicit-retention", "provisional-review"}:
                holds.setdefault(sid, []).append(
                    "proposed-historical-hold:" + (str(kind) if valid else "invalid-evidence")
                )
        if not valid:
            issues.append("invalid-hold-evidence" + (":" + sid if sid else ""))
    return holds, issues


def protection_references(state: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    holds: dict[str, list[str]] = {}
    issues: list[str] = []
    p = state.get("backup_protection")
    if p is None:
        return holds, ["backup-protection-unobserved"]
    if not isinstance(p, dict) or p.get("schema_version") != 1:
        return holds, ["invalid-backup-protection"]
    for field in ("last_success", "intent"):
        value = p.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            issues.append("invalid-backup-protection-" + field)
            continue
        sid = identifier(value.get("snapshot_id"), SNAPSHOT)
        if sid:
            holds.setdefault(sid, []).append("backup_protection." + field)
        if field == "last_success" and not sid:
            issues.append("invalid-last-success-reference")
        if field == "intent" and value.get("status") not in {"SUCCEEDED", "FAILED"}:
            issues.append("unresolved-backup-intent")
    return holds, issues


def game_references(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Preserve current world identity, not player/access/runtime payloads or archive hashes."""
    import json

    from wishicraft.artifacts import whitelist_policy
    from wishicraft.game_creation import REGISTRY_KEY
    from wishicraft.world_reference import data_source

    output: list[dict[str, Any]] = []
    issues: list[str] = []
    for row in records:
        key = row.get("game_id")
        if key == REGISTRY_KEY:
            ids = row.get("registered_ids")
            if (
                set(row) != {"game_id", "registered_ids"}
                or not isinstance(ids, list)
                or not ids
                or any(identifier(g, r"game-[0-9a-f]{64}") is None for g in ids)
            ):
                issues.append("invalid-game-registry")
            else:
                output.append(dict(record_kind="registry", registered_ids=ids))
            continue
        if isinstance(key, str) and (
            key == whitelist_policy.COMMON or key.startswith("policy-whitelist-game-v1:")
        ):
            try:
                target = None if key == whitelist_policy.COMMON else key.split(":", 1)[1]
                if key != whitelist_policy.policy_key(target) or set(row) != {
                    "game_id",
                    "policy_json",
                }:
                    raise ValueError("policy identity")
                policy = whitelist_policy.policy(json.loads(row["policy_json"]))
                output.append(
                    dict(
                        record_kind="whitelist-policy", game_id=target, revision=policy["revision"]
                    )
                )
            except (ValueError, TypeError, KeyError):
                issues.append("invalid-whitelist-policy-record")
            continue
        game = identifier(row.get("game_id"), GAME)
        world = row.get("world", {})
        if not game or not isinstance(world, dict):
            issues.append("invalid-game-reference")
            continue
        current = world.get("current_id")
        valid_current = current is None or identifier(current, OPERATION) is not None
        if not valid_current:
            issues.append("invalid-game-current-world")
        projection = dict(
            game_id=game,
            current_world=identifier(current, OPERATION),
            data_source=data_source(game, current) if valid_current else None,
            generation=world.get("generation") if type(world.get("generation")) is int else None,
            counter=world.get("generation_counter")
            if type(world.get("generation_counter")) is int
            else None,
            creation_record_present=isinstance(row.get("creation"), dict),
            import_record_present=isinstance(row.get("creation"), dict)
            and isinstance(row["creation"].get("import"), dict),
            snapshot_reference_policy="archive paths and hashes are not snapshot references",
        )
        output.append(projection)
    return output, issues
