"""D-115 local read-only collector. No service mutation methods are exposed."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from tools.retention_projection import (
    policy_projection,
    project_snapshots,
    provenance_pairs,
    timestamp,
)
from tools.retention_references import (
    GAME,
    OPERATION,
    SNAPSHOT,
    game_references,
    identifier,
    journal_references,
    manifest_references,
    protection_references,
)
from wishicraft.config import load_configuration
from wishicraft.daily_backup import read_protection
from wishicraft.retention import RetentionContext
from wishicraft.retention_workflow_lambda import _rule_matches, _validate_recycle_bin_rule

ALLOWED = {
    "sts": {"get_caller_identity"},
    "cloudformation": {"list_stack_resources"},
    "ec2": {
        "describe_volumes",
        "describe_snapshots",
        "describe_locked_snapshots",
        "list_snapshots_in_recycle_bin",
    },
    "dynamodb": {"scan", "describe_table"},
    "rbin": {"list_rules", "get_rule"},
}


def utc() -> str:
    return datetime.now(UTC).isoformat()


class Reader:
    def __init__(self, clients: dict[str, Any]) -> None:
        self.clients = clients
        self.audit: list[dict[str, Any]] = []

    def pages(
        self,
        service: str,
        method: str,
        request: dict[str, Any],
        *,
        items: str | None = None,
        incoming: str = "NextToken",
        outgoing: str = "NextToken",
        identity: str | None = None,
    ) -> list[dict[str, Any]]:
        if method not in ALLOWED.get(service, set()):
            raise ValueError("read-only allowlist rejected call")
        audit: dict[str, Any] = dict(
            api=service + "." + method,
            started_at=utc(),
            ended_at=None,
            pages=0,
            final_page=False,
            issues=[],
            target={
                k: v
                for k, v in request.items()
                if k
                in {"OwnerIds", "VolumeIds", "TableName", "StackName", "ResourceType", "Identifier"}
            },
            consistent_read=request.get("ConsistentRead") is True,
        )
        self.audit.append(audit)
        result: list[dict[str, Any]] = []
        seen_tokens: set[str] = set()
        seen_ids: set[str] = set()
        args = dict(request)
        try:
            for _ in range(1000):
                response = getattr(self.clients[service], method)(**args)
                audit["pages"] += 1
                batch = response.get(items) if items else [response]
                if not isinstance(batch, list) or not all(isinstance(r, dict) for r in batch):
                    audit["issues"].append("invalid-page")
                    break
                result.extend(batch)
                if identity:
                    for row in batch:
                        key = row.get(identity)
                        marker = json.dumps(key, sort_keys=True, default=str)
                        if key is None or marker in seen_ids:
                            audit["issues"].append("missing-or-duplicate-identity")
                        seen_ids.add(marker)
                token = response.get(outgoing)
                if token is None:
                    audit["final_page"] = True
                    break
                marker = json.dumps(token, sort_keys=True, default=str)
                if not token or marker in seen_tokens:
                    audit["issues"].append("invalid-or-cyclic-token")
                    break
                seen_tokens.add(marker)
                args[incoming] = token
            else:
                audit["issues"].append("page-limit")
        except Exception as exc:
            # Neither str(exc), traceback, raw response nor request tokens cross storage boundary.
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            audit["issues"].append(
                code
                if code
                in {
                    "AccessDenied",
                    "AccessDeniedException",
                    "UnauthorizedOperation",
                    "ExpiredToken",
                    "ExpiredTokenException",
                    "UnsupportedOperation",
                }
                else "read-failed"
            )
        finally:
            audit["ended_at"] = utc()
            audit["item_count"] = len(result)
        return result


def decode(value: Any) -> Any:
    """DynamoDB wire decoding in memory, including nested JSON strings left opaque."""
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("invalid wire value")
    key, data = next(iter(value.items()))
    if key == "S" and isinstance(data, str):
        return data
    if key == "N" and isinstance(data, str):
        return int(data)
    if key == "BOOL" and type(data) is bool:
        return data
    if key == "NULL" and data is True:
        return None
    if key == "M" and isinstance(data, dict):
        return {k: decode(v) for k, v in data.items()}
    if key == "L" and isinstance(data, list):
        return [decode(v) for v in data]
    if key == "SS" and isinstance(data, list) and all(isinstance(v, str) for v in data):
        return sorted(data)
    raise ValueError("unsupported wire value")


def decoded(rows: list[dict[str, Any]], issues: list[str]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        try:
            out.append({k: decode(v) for k, v in row.items()})
        except (ValueError, TypeError):
            issues.append("invalid-dynamodb-record")
            out.append({})  # Preserve pair alignment without saving original data.
    return out


def collect_round(reader: Reader, tables: dict[str, str], account: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, table in tables.items():
        data[key] = reader.pages(
            "dynamodb",
            "scan",
            {"TableName": table, "ConsistentRead": True},
            items="Items",
            incoming="ExclusiveStartKey",
            outgoing="LastEvaluatedKey",
            identity={
                "state": "system_id",
                "games": "game_id",
                "backups": "provenance_key",
                "operations": "operation_id",
            }[key],
        )
    data["snapshots"] = reader.pages(
        "ec2",
        "describe_snapshots",
        {"OwnerIds": [account], "MaxResults": 1000},
        items="Snapshots",
        identity="SnapshotId",
    )
    data["locks"] = reader.pages(
        "ec2",
        "describe_locked_snapshots",
        {"MaxResults": 1000},
        items="Snapshots",
        identity="SnapshotId",
    )
    summaries = reader.pages(
        "rbin",
        "list_rules",
        {"ResourceType": "EBS_SNAPSHOT", "MaxResults": 100},
        items="Rules",
        identity="Identifier",
    )
    data["rules"] = []
    for summary in summaries:
        rid = identifier(summary.get("Identifier"), r"[A-Za-z0-9-]{1,100}")
        if rid:
            data["rules"].extend(reader.pages("rbin", "get_rule", {"Identifier": rid}))
        else:
            data["rules"].append({})
    data["recycle_bin"] = reader.pages(
        "ec2",
        "list_snapshots_in_recycle_bin",
        {"MaxResults": 1000},
        items="Snapshots",
        identity="SnapshotId",
    )
    return data


# Periodic observer fields are omitted; authority/intent/maintenance and all journal fields stay.
STATE_KEYS = {
    "system_id",
    "record_type",
    "desired_state",
    "desired_revision",
    "current_game_id",
    "current_operation_id",
    "maintenance",
    "maintenance_lease",
    "backup_protection",
    "selected_game_id",
    "desired_game_id",
    "game_id",
    "status",
    "health",
    "data_volume_id",
}


def needs_operation_review(row: dict[str, Any]) -> bool:
    if row.get("status") == "SUCCEEDED":
        return False
    if row.get("status") in {"FAILED", "TIMED_OUT", "REJECTED", "CANCELLED"}:
        return row.get("operation_type") in {"BACKUP", "RESTORE", "IMPORT", "RETENTION"}
    return True


def stability_view(data: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    state = decoded(data["state"], issues)
    operations = decoded(data["operations"], issues)
    return dict(
        snapshots=sorted(data["snapshots"], key=lambda r: str(r.get("SnapshotId"))),
        locks=sorted(data["locks"], key=lambda r: str(r.get("SnapshotId"))),
        rules=sorted(
            [{k: v for k, v in r.items() if k != "ResponseMetadata"} for r in data["rules"]],
            key=lambda r: str(r.get("Identifier")),
        ),
        recycle_bin=sorted(data["recycle_bin"], key=lambda r: str(r.get("SnapshotId"))),
        backups=sorted(data["backups"], key=lambda r: str(r.get("provenance_key"))),
        games=sorted(data["games"], key=lambda r: str(r.get("game_id"))),
        state=sorted(
            [
                r
                if r.get("record_type") == "RESTORE"
                or str(r.get("system_id")).startswith("restore#")
                else {k: v for k, v in r.items() if k in STATE_KEYS}
                for r in state
            ],
            key=lambda r: str(r.get("system_id")),
        ),
        operations=sorted(
            [r for r in operations if needs_operation_review(r)],
            key=lambda r: str(r.get("operation_id")),
        ),
        issues=issues,
    )


def bounded_capture(
    reader: Reader, tables: dict[str, str], account: str, attempts: int = 2
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    comparisons = []
    for attempt in range(attempts):
        before = collect_round(reader, tables, account)
        after = collect_round(reader, tables, account)
        a, b = stability_view(before), stability_view(after)
        changed = [key for key in a if a[key] != b[key]]
        comparisons.append(dict(attempt=attempt + 1, equal=not changed, changed_domains=changed))
        if not changed:
            return after, comparisons
    return after, comparisons


def report(
    data: dict[str, Any],
    *,
    context: RetentionContext,
    region: str,
    system: str,
    manifest: dict[str, Any],
    now: datetime,
    audit: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    sid: str | None
    issues = [
        "collector-and-manifest-not-reviewed",
        "future-deletion-requires-fresh-fenced-check",
        "additional-aws-deletion-references-not-assessed",
    ]
    records = decoded(data["state"], issues)
    games = decoded(data["games"], issues)
    backup_rows = decoded(data["backups"], issues)
    operations = decoded(data["operations"], issues)
    states = [r for r in records if r.get("system_id") == system]
    state = states[0] if len(states) == 1 else {}
    if len(states) != 1:
        issues.append("system-authority-missing-or-duplicate")
    game_ids = {r["game_id"] for r in games if identifier(r.get("game_id"), GAME)}
    game_view, game_issues = game_references(games)
    issues.extend(game_issues)
    holds, journals, journal_issues = journal_references(
        records,
        system=system,
        stage=context.stage,
        project=context.project,
        volume=context.source_volume_id,
        games=game_ids,
    )
    issues.extend(journal_issues)
    mh, mi = manifest_references(
        manifest,
        account=context.owner_id,
        region=region,
        snapshot_ids={str(r.get("SnapshotId")) for r in data["snapshots"]},
    )
    ph, pi = protection_references(state)
    for extra in (mh, ph):
        for hold_id, reasons in extra.items():
            holds.setdefault(hold_id, []).extend(reasons)
    issues.extend(mi + pi)
    protection: dict[str, Any] = {}
    try:
        p = read_protection(state, context.source_volume_id, now)
        protection = {k: p[k] for k in ("boundary", "protected_boundary", "attempts")}

        for k in ("oldest_at", "unknown_since", "stopped_at"):
            protection[k] = timestamp(p.get(k))
        for k in ("intent", "last_success"):
            v = p.get(k) or {}
            protection[k] = dict(
                operation_id=identifier(v.get("operation_id"), OPERATION),
                snapshot_id=identifier(v.get("snapshot_id"), SNAPSHOT),
                boundary=v.get("boundary") if type(v.get("boundary")) is int else None,
                acquired_at=timestamp(v.get("acquired_at")),
                verified_at=timestamp(v.get("verified_at")),
                status=v.get("status")
                if v.get("status") in {"SUCCEEDED", "FAILED", "UNKNOWN", "ADMITTED"}
                else None,
            )
    except (ValueError, TypeError, KeyError):
        issues.append("invalid-protection-authority")
    unresolved = []
    for op in operations:
        if not needs_operation_review(op):
            continue
        oid = identifier(op.get("operation_id"), OPERATION)
        unresolved.append(
            dict(
                operation_id=oid,
                unresolved=True,
                operation_type=op.get("operation_type")
                if op.get("operation_type")
                in {
                    "START",
                    "STOP",
                    "BACKUP",
                    "RETENTION",
                    "RESTORE",
                    "IMPORT",
                    "RESET",
                    "SWITCH",
                    "CREATE",
                    "STATUS",
                }
                else "UNKNOWN",
                requested_at=timestamp(op.get("requested_at")),
                completed_at=timestamp(op.get("completed_at")),
                status=op.get("status")
                if op.get("status") in {"PENDING", "RUNNING", "FAILED", "TIMED_OUT", "CANCELLED"}
                else "UNKNOWN",
            )
        )
        issues.append("unresolved-management-or-other-operation")
        for field in ("backup_snapshot_id", "source_snapshot_id", "snapshot_id"):
            sid = identifier(op.get(field), SNAPSHOT)
            if sid:
                holds.setdefault(sid, []).append("unresolved-operation:" + (oid or "invalid"))
    provenances, provenance_audit, prov_issues = provenance_pairs(
        data["backups"], backup_rows, context
    )
    issues.extend(prov_issues)
    for field in ("last_success", "intent"):
        opid = protection.get(field, {}).get("operation_id")
        if opid:
            for proof_id, prov in provenances.items():
                if prov.operation_id == opid:
                    holds.setdefault(proof_id, []).append("backup_protection." + field)
    last = protection.get("last_success", {})
    if last.get("snapshot_id"):
        proof = provenances.get(last["snapshot_id"])
        if (
            proof is None
            or proof.operation_id != last.get("operation_id")
            or proof.snapshot_start_time.isoformat() != last.get("acquired_at")
        ):
            issues.append("last-success-provenance-mismatch")
    present = {r.get("SnapshotId") for r in data["snapshots"]}
    absent_refs = sorted(set(holds) - present)
    issues.extend("referenced-snapshot-not-in-active-inventory:" + sid for sid in absent_refs)
    orphan_provenance = sorted(set(provenances) - present)
    issues.extend("provenance-without-active-snapshot:" + sid for sid in orphan_provenance)
    locks = {}
    for lock in data["locks"]:
        sid = identifier(lock.get("SnapshotId"), SNAPSHOT)
        ls = lock.get("LockState")
        if sid and ls in {"compliance", "governance", "compliance-cooloff", "expired"}:
            locks[sid] = ls
        else:
            issues.append("invalid-snapshot-lock")
    rows = project_snapshots(
        data["snapshots"],
        provenances,
        context=context,
        region=region,
        now=now,
        holds=holds,
        locks=locks,
    )
    rules = []
    for raw in data["rules"]:
        rid = identifier(raw.get("Identifier"), r"[A-Za-z0-9-]{1,100}")
        try:
            rule = _validate_recycle_bin_rule(raw, rid or "")
            matched = []
            for snap in data["snapshots"]:
                tags = {t["Key"]: t["Value"] for t in snap.get("Tags", [])}
                if _rule_matches(rule, tags):
                    sid = identifier(snap.get("SnapshotId"), SNAPSHOT)
                    if sid:
                        matched.append(sid)
            rules.append(
                dict(
                    identifier=rid,
                    status=rule["Status"],
                    retention_days=cast(dict[str, Any], rule["RetentionPeriod"])[
                        "RetentionPeriodValue"
                    ],
                    tag_predicate_matches=matched,
                    guarantee="tag matching only; not proof of future recoverability",
                )
            )
        except (ValueError, TypeError, KeyError):
            issues.append("invalid-recycle-bin-rule")
    if not comparisons or not comparisons[-1]["equal"]:
        issues.append("unstable-collection")
    for event in audit:
        if not event["final_page"] or event["issues"]:
            issues.append("incomplete-or-invalid-read:" + event["api"])
    lock_reads = [a for a in audit if a["api"] == "ec2.describe_locked_snapshots"]
    locks_confirmed = bool(lock_reads) and all(
        a["final_page"] and not a["issues"] for a in lock_reads
    )
    for row in rows:
        row["missing_checks"] = ["collector/hold-manifest review and fresh deletion fencing"]
        if not locks_confirmed:
            row["lock_state"] = "UNKNOWN"
            row["missing_checks"].append("snapshot-lock inventory unconfirmed")
        row["holds"] = sorted(set(row["holds"]))
        if row["integrity_issues"]:
            issues.append("snapshot-integrity:" + (row["snapshot_id"] or "invalid-id"))
    projection = policy_projection(rows, now)
    historical_rows = deepcopy(rows)
    for row in historical_rows:
        row["normal_eligible"] = (
            "retention-owned" in row["reasons"]
            and row["target_volume"]
            and row["provenance_pair_valid"]
            and not row["integrity_issues"]
            and row["lock_state"] == "none-observed"
        )
    historical_projection = policy_projection(historical_rows, now)
    deployed_reference = dict(
        label="HISTORICAL_DEPLOYED_NEWEST_SEVEN_ARITHMETIC_ONLY_NOT_AN_EXECUTION_PLAN",
        normal_count=historical_projection["normal_count"],
        outside_ids=historical_projection["old_newest_seven_outside_ids"],
        boundary_tie=historical_projection["boundary_tie"],
        limitation="old classifier predates journal/manifest holds; not deletion recommendations",
    )
    return dict(
        schema_version=1,
        evaluated_at=now.isoformat(),
        account_id=context.owner_id,
        region=region,
        stage=context.stage,
        system_id=system,
        volume_id=context.source_volume_id,
        deletion_authorized=False,
        planned_delete_ids=[],
        delete_action_count=0,
        status="NO_DELETE",
        completeness=dict(
            api_pages=bool(audit) and all(a["final_page"] for a in audit),
            api_content_valid=all(not a["issues"] for a in audit),
            stable=bool(comparisons and comparisons[-1]["equal"]),
            provenance_pairs_valid=not prov_issues,
            journals_valid=not journal_issues,
            hold_manifest_reviewed=False,
            deletion_safety_complete=False,
        ),
        missing_checks=sorted(set(issues)),
        api_audit=audit,
        comparisons=comparisons,
        snapshots=rows,
        snapshot_count=len(rows),
        target_volume_count=sum(r["target_volume"] for r in rows),
        provenance=provenance_audit,
        orphan_provenance_ids=orphan_provenance,
        games=game_view,
        journals=journals,
        protection=protection,
        unresolved_operations=unresolved,
        absent_reference_ids=absent_refs,
        recycle_bin_rules=rules,
        recycle_bin_snapshot_ids=[
            identifier(r.get("SnapshotId"), SNAPSHOT) for r in data["recycle_bin"]
        ],
        policy_projection=projection,
        deployed_old_policy_reference=deployed_reference,
        evidence_contract="original recovery verified in memory; persisted projections cannot "
        "revalidate recovery digests. Replay only arithmetic, never deletion authorization.",
    )


def save(path: Path, value: dict[str, Any]) -> None:
    # Input must already be the allowlisted report, not arbitrary AWS JSON.
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def run(args: argparse.Namespace) -> dict[str, Any]:
    import boto3  # type: ignore[import-untyped]

    cfg = load_configuration(Path(args.repository), args.stage)
    account, region = cfg.stage.aws_account_id, cfg.stage.aws_region
    volume = cast(Any, cfg.stage.values)["host_runtime"]["target_host"]["existing_data_volume_id"]
    if not identifier(volume, r"vol-[0-9a-f]{8,17}"):
        raise ValueError("canonical volume missing")
    session = boto3.Session(profile_name=args.profile, region_name=region)
    reader = Reader({name: session.client(name) for name in ALLOWED})
    caller = reader.pages("sts", "get_caller_identity", {})
    if len(caller) != 1 or caller[0].get("Account") != account:
        raise ValueError("caller identity not confirmed")
    resources = reader.pages(
        "cloudformation",
        "list_stack_resources",
        {"StackName": "WishicraftControlPlaneStack-" + args.stage},
        items="StackResourceSummaries",
        identity="LogicalResourceId",
    )
    tables = {}
    for key, suffix in [
        ("state", "system-state"),
        ("games", "games"),
        ("backups", "backups"),
        ("operations", "operations"),
    ]:
        name = cfg.project.resource_prefix + "-" + args.stage + "-" + suffix
        if (
            sum(
                r.get("ResourceType") == "AWS::DynamoDB::Table"
                and r.get("PhysicalResourceId") == name
                for r in resources
            )
            != 1
        ):
            raise ValueError("canonical table identity not confirmed")
        detail = reader.pages("dynamodb", "describe_table", {"TableName": name})
        if len(detail) != 1 or detail[0].get("Table", {}).get("TableArn") != (
            f"arn:aws:dynamodb:{region}:{account}:table/{name}"
        ):
            raise ValueError("table ARN not confirmed")
        tables[key] = name
    vols = reader.pages("ec2", "describe_volumes", {"VolumeIds": [volume]}, items="Volumes")
    if (
        len(vols) != 1
        or vols[0].get("VolumeId") != volume
        or vols[0].get("AvailabilityZone") != cfg.stage.availability_zone
    ):
        raise ValueError("canonical volume identity not confirmed")
    context = RetentionContext(
        cfg.project.project_slug,
        args.stage,
        cfg.project.initial_game_id,
        volume,
        account,
        shared_volume=True,
    )
    data, comparisons = bounded_capture(reader, tables, account)
    result = report(
        data,
        context=context,
        region=region,
        system=cfg.project.system_id,
        manifest=json.loads(Path(args.manifest).read_text()),
        now=datetime.now(UTC),
        audit=reader.audit,
        comparisons=comparisons,
    )
    result["tables"] = tables
    result["volume_identity_confirmed"] = True
    return result


def main(argv: list[str] | None = None, execute: Callable[..., Any] = run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=".")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = execute(args)
        save(args.output, value)
        print(
            json.dumps(
                {
                    k: value[k]
                    for k in (
                        "status",
                        "snapshot_count",
                        "target_volume_count",
                        "deletion_authorized",
                        "delete_action_count",
                    )
                }
            )
        )
        return 0
    except Exception:
        print(
            "Read-only collection failed; no raw exception or response persisted.", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
