"""Observe an exact Reset and optionally resume its failed Task while ownership is valid.

No world/ref/receipt/lease repair. Default execution is read-only.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wishicraft.config import load_configuration
from wishicraft.operation import LeaseProof, LeaseRepository
from wishicraft.runtime_contract import validate_target


def observe(
    ddb: Any,
    sfn: Any,
    *,
    operation_id: str,
    system_id: str,
    lock_name: str,
    tables: dict[str, str],
    now: datetime,
) -> dict[str, Any]:
    from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

    decode = TypeDeserializer().deserialize
    raw = ddb.get_item(
        TableName=tables["operations"],
        Key={"operation_id": {"S": operation_id}},
        ConsistentRead=True,
    )["Item"]
    op = {k: decode(v) for k, v in raw.items()}
    if op["operation_type"] != "RESET" or op["operation_id"] != operation_id:
        raise ValueError("not the requested RESET")
    plan = json.loads(op["reset_plan"])
    validate_target(plan["source"])
    validate_target(plan["target"])
    execution = sfn.describe_execution(executionArn=op["workflow_execution_arn"])
    if (
        execution.get("name") != operation_id
        or execution.get("executionArn") != op["workflow_execution_arn"]
    ):
        raise ValueError("RESET execution identity mismatch")
    if not op["workflow_execution_arn"].endswith(
        ":execution:" + tables["operations"].removesuffix("operations") + "reset:" + operation_id
    ):
        raise ValueError("RESET workflow identity mismatch")
    proof = LeaseProof(system_id, operation_id, op["lease_id"], 0)
    owned = False
    try:
        LeaseRepository(ddb, table_name=tables["locks"], lock_name=lock_name).verify_owned(
            proof, now=now
        )
        owned = True
    except Exception:
        pass  # Report observation, but do not authorize resume on unknown or lost ownership.
    current = ddb.get_item(
        TableName=tables["games"], Key={"game_id": {"S": op["target_game_id"]}}, ConsistentRead=True
    )["Item"]["world"]
    from wishicraft.world_reference import data_source

    world = decode(current)
    current_path = data_source(op["target_game_id"], world.get("current_id"))
    if current_path not in {plan["source"]["data_source"], plan["target"]["data_source"]}:
        raise ValueError("RESET selection changed")
    eligible = (
        owned
        and op["status"] == "RUNNING"
        and execution["status"] == "FAILED"
        and datetime.fromisoformat(op["timeout_at"].replace("Z", "+00:00")) > now
        and execution.get("redriveStatus") == "REDRIVABLE"
    )
    return {
        "operation_id": operation_id,
        "operation_status": op["status"],
        "execution_arn": op["workflow_execution_arn"],
        "execution_status": execution["status"],
        "owned_lease": owned,
        "resume_eligible": eligible,
        "current_world": decode(current),
        "plan": plan,
        "commands": {
            k: v for k, v in op.items() if k.startswith(("reset_prepare_", "reset_cleanup_"))
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--resume-token")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute and not args.resume_token:
        parser.error("--execute requires a fixed --resume-token")
    import boto3  # type: ignore[import-untyped]

    cfg = load_configuration(Path(__file__).resolve().parents[2], "dev")
    session = boto3.Session(profile_name="wishicraft-dev", region_name=cfg.stage.aws_region)
    if session.client("sts").get_caller_identity()["Account"] != cfg.stage.aws_account_id:
        raise ValueError("caller account mismatch")
    ddb, sfn = session.client("dynamodb"), session.client("stepfunctions")
    prefix = cfg.project.resource_prefix + "-dev-"
    result = observe(
        ddb,
        sfn,
        operation_id=args.operation_id,
        system_id=cfg.project.system_id,
        lock_name=cfg.stage.global_lock_name,
        tables={k: prefix + k for k in ("operations", "locks", "games")},
        now=datetime.now(UTC),
    )
    if args.execute:
        if not result["resume_eligible"]:
            raise ValueError(
                "RESET is not safely resumable; keep data and inspect recovery conditions"
            )
        # Same definition/input and successful steps remain intact. Caller fixes the token once.
        sfn.redrive_execution(executionArn=result["execution_arn"], clientToken=args.resume_token)
        result["resume_requested"] = True
        result["completion_verified"] = False
    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
