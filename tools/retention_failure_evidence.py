"""Scoped historical read evidence; never resolves a failure or authorizes deletion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from tools.retention_inventory import decode, save
from wishicraft.config import load_configuration

CASES = {
    "op-433438bf-d775-4799-8016-ff0bdcb361a7": "BACKUP",
    "op-7592d65c-3173-4b98-9036-a03a1ce8008a": "RETENTION",
    "op-d0383b17-8783-43fd-a7aa-b47fcd299a2a": "BACKUP",
}
ERRORS = {
    "UnauthorizedOperation",
    "AccessDenied",
    "AccessDeniedException",
    "ValueError",
    "TypeError",
    "States.TaskFailed",
    "BACKUP_SNAPSHOT_CREATE_FAILED",
    "RETENTION_FAILED",
    "RETENTION_DRY_RUN_FAILED",
    "RETENTION_WORKFLOW_FAILED",
    "BACKUP_FAILED",
    "RuntimeError",
    "BackupCreateRejected",
    "ClientError",
}


def project(value: Any) -> dict[str, Any]:
    """Only enumerated evidence crosses storage; opaque payloads stay in memory."""
    out: dict[str, Any] = {"errors": [], "snapshot_ids": [], "facts": [], "states": []}

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if item in {"CreateSnapshotOnce", "RunRetentionDryRun"}:
                out["states"].append(item)
            if item in ERRORS:
                out["errors"].append(item)
            # Exact diagnostic predicates disclose no surrounding message/stack/credentials.
            for text, fact in (
                (
                    "when calling the CreateSnapshot operation: You are not authorized",
                    "create-explicit-denial",
                ),
                ("UnauthorizedOperation", "unauthorized-error-present"),
                ("unsupported DynamoDB", "unsupported-dynamodb-value"),
                ("unsupported operation value", "unsupported-operation-value"),
                ("EC2 explicitly rejected creation", "create-explicit-denial"),
            ):
                if text in item:
                    out["facts"].append(fact)
            if item.startswith(("{", "[")):
                try:
                    visit(json.loads(item))
                except (ValueError, RecursionError):
                    pass
        elif isinstance(item, dict):
            for key, entry in item.items():
                if key in {
                    "snapshot_id",
                    "SnapshotId",
                    "snapshotId",
                    "backup_snapshot_id",
                } and isinstance(entry, str):
                    if re.fullmatch(r"snap-[0-9a-f]{8,17}", entry):
                        out["snapshot_ids"].append(entry)
                if key not in {
                    "runtime_env",
                    "Environment",
                    "Variables",
                    "credentials",
                    "recovery_json",
                    "compose",
                }:
                    visit(entry)
        elif isinstance(item, list):
            for entry in item:
                visit(entry)

    visit(value)
    return {key: sorted(set(entries)) for key, entries in out.items()}


def collect(session: Any, root: Path) -> dict[str, Any]:
    cfg = load_configuration(root, "dev")
    account, region = cfg.stage.aws_account_id, cfg.stage.aws_region
    if (
        session.region_name != region
        or session.client("sts").get_caller_identity()["Account"] != account
    ):
        raise ValueError("identity mismatch")
    ddb, states = session.client("dynamodb"), session.client("stepfunctions")
    table = cfg.project.resource_prefix + "-dev-operations"
    if (
        ddb.describe_table(TableName=table)["Table"]["TableArn"]
        != f"arn:aws:dynamodb:{region}:{account}:table/{table}"
    ):
        raise ValueError("table mismatch")
    result: dict[str, Any] = dict(
        schema_version=1,
        account_id=account,
        region=region,
        system_id=cfg.project.system_id,
        started_at=datetime.now(UTC).isoformat(),
        operations=[],
        status="NO_DELETE",
        deletion_authorized=False,
        planned_delete_ids=[],
        delete_action_count=0,
        review_status="PROPOSED",
        automatic_resolution=False,
    )
    for op, kind in CASES.items():
        record: dict[str, Any] = dict(operation_id=op, expected_type=kind, history=[], issues=[])
        result["operations"].append(record)
        try:
            raw = ddb.get_item(
                TableName=table, Key={"operation_id": {"S": op}}, ConsistentRead=True
            ).get("Item", {})
            row = {key: decode(value) for key, value in raw.items()}
            expected = f"arn:aws:states:{region}:{account}:execution:wc-dev-{kind.lower()}:{op}"
            record["identity_matches"] = (
                row.get("operation_id") == op
                and row.get("operation_type") == kind
                and row.get("workflow_execution_arn") == expected
                and row.get("status") == "FAILED"
            )
            record["terminal_failed"] = row.get("status") == "FAILED"
            record["operation_facts"] = project(row)
            record["backup_create_intent_present"] = "backup_create_intent" in row
            record["backup_snapshot_field_present"] = "backup_snapshot_id" in row
            game = row.get("target_game_id")
            record["target_game_id"] = (
                game if isinstance(game, str) and re.fullmatch(r"game-[a-z0-9-]+", game) else None
            )
            for key in ("requested_at", "completed_at"):
                raw_time = row.get(key)
                if isinstance(raw_time, str):
                    stamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                    if stamp.tzinfo is not None:
                        record[key] = stamp.astimezone(UTC).isoformat()
            if not record["identity_matches"]:
                record["issues"].append("operation-identity-or-terminal-mismatch")
                continue
            record["execution_arn"] = expected
            description = states.describe_execution(executionArn=expected)
            record["execution_failed"] = description.get("status") == "FAILED"
            record["execution_identity_matches"] = (
                description.get("executionArn") == expected and description.get("name") == op
            )
            record["execution_facts"] = project(description)
            token, seen, ids = None, set(), set()
            for page in range(1000):
                request = dict(executionArn=expected, includeExecutionData=True, maxResults=1000)
                if token:
                    request["nextToken"] = token
                response = states.get_execution_history(**request)
                for event in response["events"]:
                    event_id = event["id"]
                    if type(event_id) is not int or event_id in ids:
                        raise ValueError("invalid event identity")
                    ids.add(event_id)
                    event_type = event.get("type")
                    allowed_types = states.meta.service_model.shape_for("HistoryEventType").enum
                    record["history"].append(
                        dict(
                            id=event_id,
                            type=event_type if event_type in allowed_types else "UNKNOWN",
                            timestamp=event["timestamp"].astimezone(UTC).isoformat(),
                            **project(event),
                        )
                    )
                record["history_pages"] = page + 1
                token = response.get("nextToken")
                if not token:
                    record["history_complete"] = True
                    break
                if token in seen:
                    raise ValueError("token cycle")
                seen.add(token)
            else:
                raise ValueError("page limit")
        except Exception:
            record["issues"].append("read-or-validation-failed-no-raw-error-saved")
        record["finished_at"] = datetime.now(UTC).isoformat()
    trail = session.client("cloudtrail")
    for record in result["operations"]:
        record["cloudtrail"] = []
        if not record.get("identity_matches"):
            continue
        start = datetime.fromisoformat(record["requested_at"]) - timedelta(seconds=60)
        end = datetime.fromisoformat(record["completed_at"]) + timedelta(seconds=60)
        event_name = "CreateSnapshot" if record["expected_type"] == "BACKUP" else "DeleteSnapshot"
        audit: dict[str, Any] = dict(
            event_name=event_name,
            start=start.isoformat(),
            end=end.isoformat(),
            complete=False,
            pages=0,
            records=[],
            issues=[],
        )
        record["cloudtrail"].append(audit)
        try:
            token, seen = None, set()
            for page in range(1000):
                request = dict(
                    LookupAttributes=[dict(AttributeKey="EventName", AttributeValue=event_name)],
                    StartTime=start,
                    EndTime=end,
                    MaxResults=50,
                )
                if token:
                    request["NextToken"] = token
                response = trail.lookup_events(**request)
                audit["pages"] = page + 1
                for event in response["Events"]:
                    raw = json.loads(event["CloudTrailEvent"])
                    event_id = raw.get("eventID")
                    if not isinstance(event_id, str) or not re.fullmatch(
                        r"[0-9a-f-]{36}", event_id
                    ):
                        raise ValueError("invalid event identity")
                    audit["records"].append(
                        dict(
                            event_id=event_id,
                            event_time=datetime.fromisoformat(
                                raw["eventTime"].replace("Z", "+00:00")
                            )
                            .astimezone(UTC)
                            .isoformat(),
                            account_region_matches=raw.get("recipientAccountId") == account
                            and raw.get("awsRegion") == region,
                            operation_tag_matches=record["operation_id"]
                            in json.dumps(raw.get("requestParameters")),
                            explicit_denial=raw.get("errorCode")
                            in {
                                "Client.UnauthorizedOperation",
                                "UnauthorizedOperation",
                                "AccessDenied",
                            },
                            source_volume_matches=cast(Any, cfg.stage.values)["host_runtime"][
                                "target_host"
                            ]["existing_data_volume_id"]
                            in json.dumps(raw.get("requestParameters")),
                            **project(raw),
                        )
                    )
                token = response.get("NextToken")
                if not token:
                    audit["complete"] = True
                    break
                if token in seen:
                    raise ValueError("token cycle")
                seen.add(token)
        except Exception:
            audit["issues"].append("read-or-validation-failed-no-raw-error-saved")
    result["ended_at"] = datetime.now(UTC).isoformat()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        import boto3  # type: ignore[import-untyped]

        cfg = load_configuration(Path.cwd(), "dev")
        value = collect(
            boto3.Session(profile_name="wishicraft-dev", region_name=cfg.stage.aws_region),
            Path.cwd(),
        )
        save(args.output, value)
        print("Historical evidence saved; no automatic resolution or deletion authorized.")
        return 0
    except Exception:
        print("Read failed; no raw response or exception saved.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
