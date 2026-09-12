"""Small Reset-specific tasks between the existing graceful STOP and START graphs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from wishicraft import reset_contract
from wishicraft.runtime_contract import command


class ResetPreparationFailed(RuntimeError):
    """Known exited preparation; source remains selected and stopped."""


def task(runtime: Any, proof: Any, payload: dict[str, Any], now: datetime) -> dict[str, object]:
    action = payload["action"]
    if action == "prepare_reset":
        reset_contract.prepare(runtime, proof, payload["state"], now)
        return {"prepared": True}
    runtime.coordinator.leases.verify_owned(proof, now=now)
    raw = reset_contract.operation(runtime, proof)
    if raw["operation_type"] != {"S": "RESET"} or raw["lease_id"] != {"S": proof.lease_id}:
        raise ValueError("RESET ownership mismatch")
    plan = json.loads(raw["reset_plan"]["S"])
    if action == "commit_reset":
        if raw.get("reset_prepare_complete") != {"BOOL": True}:
            raise ValueError("RESET preparation has not completed")
        reset_contract.commit_selection(runtime, proof, now)
        return {"selected": True}
    cleanup = "cleanup" in action
    field = "reset_cleanup" if cleanup else "reset_prepare"
    if action.startswith("run_reset_"):
        if cleanup:
            observation = payload["state"]["observation"]
            if (
                observation.get("runtime_ready") is not True
                or observation.get("execution", {}).get("target") != plan["target"]
                or observation.get("execution", {}).get("phase") != "running"
            ):
                raise ValueError("RESET destination READY is not confirmed")
        if field + "_command" in raw:
            return {"command_id": raw[field + "_command"]["S"]}
        if field + "_dispatched" in raw:
            # Recover a lost SendCommand reply only from a unique exact request, never absence.
            existing = find_command(runtime.ssm, proof, plan, field)
            runtime.targets.api.update_item(
                TableName=runtime.targets.table,
                Key={"operation_id": {"S": proof.owner_operation_id}},
                UpdateExpression="SET " + field + "_command = :command",
                ConditionExpression="lease_id = :lease AND attribute_not_exists("
                + field
                + "_command)",
                ExpressionAttributeValues={
                    ":command": {"S": existing},
                    ":lease": {"S": proof.lease_id},
                },
            )
            return {"command_id": existing}
        api = runtime.targets.api
        api.update_item(
            TableName=runtime.targets.table,
            Key={"operation_id": {"S": proof.owner_operation_id}},
            UpdateExpression="SET " + field + "_dispatched = :yes",
            ConditionExpression="lease_id = :lease AND #s = :running AND attribute_not_exists("
            + field
            + "_dispatched)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":yes": {"BOOL": True},
                ":lease": {"S": proof.lease_id},
                ":running": {"S": "RUNNING"},
            },
        )
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]

        sender = boto3.client(
            "ssm",
            region_name=os.environ["AWS_REGION"],
            config=Config(retries={"total_max_attempts": 1}),
        )
        response = sender.send_command(
            InstanceIds=[plan["target"]["instance_id"]],
            DocumentName="AWS-RunShellScript",
            Comment="Wishicraft " + field + " " + proof.owner_operation_id,
            TimeoutSeconds=360,
            Parameters={
                "commands": [
                    command(
                        operation_id=proof.owner_operation_id,
                        lease_id=proof.lease_id,
                        action="RESET_CLEANUP" if cleanup else "RESET_PREPARE",
                    )
                ],
                "executionTimeout": ["360"],
            },
        )
        command_id = response["Command"]["CommandId"]
        if not isinstance(command_id, str) or not command_id:
            raise RuntimeError("RESET_COMMAND_OUTCOME_UNKNOWN")
        api.update_item(
            TableName=runtime.targets.table,
            Key={"operation_id": {"S": proof.owner_operation_id}},
            UpdateExpression="SET " + field + "_command = :command",
            ConditionExpression="lease_id = :lease AND attribute_not_exists(" + field + "_command)",
            ExpressionAttributeValues={
                ":command": {"S": command_id},
                ":lease": {"S": proof.lease_id},
            },
        )
        return {"command_id": command_id}
    if action.startswith("check_reset_"):
        if raw.get(field + "_command") != {"S": payload["command_id"]}:
            raise ValueError("RESET command identity mismatch")
        response = runtime.ssm.get_command_invocation(
            CommandId=payload["command_id"], InstanceId=plan["target"]["instance_id"]
        )
        if response["Status"] in {"Pending", "InProgress", "Delayed"}:
            return {"complete": False}
        failed_exit = (
            response["Status"] == "Failed"
            and isinstance(response.get("ResponseCode"), int)
            and not isinstance(response["ResponseCode"], bool)
            and response["ResponseCode"] > 0
        )
        if failed_exit and not cleanup:
            # This foreground Python preparation has exited: no background runtime is launched.
            # Existing source remains selected, and partial destination is retained for diagnosis.
            raise ResetPreparationFailed("RESET_PREPARATION_EXITED_FAILED")
        if not failed_exit and (
            response["Status"] != "Success" or response.get("ResponseCode") != 0
        ):
            raise RuntimeError("RESET_HOST_TASK_OUTCOME_UNRESOLVED")
        if cleanup:
            summaries = []
            for line in response.get("StandardOutputContent", "").splitlines():
                try:
                    summary = json.loads(line)
                except ValueError:
                    continue
                if isinstance(summary, dict) and isinstance(summary.get("cleanup_pending"), bool):
                    summaries.append(summary)
            if failed_exit:
                summaries = [{"cleanup_pending": True}]
            if len(summaries) != 1:
                raise ValueError("RESET cleanup summary is unknown")
            runtime.targets.api.update_item(
                TableName=runtime.targets.table,
                Key={"operation_id": {"S": proof.owner_operation_id}},
                UpdateExpression="SET reset_cleanup_pending = :pending",
                ConditionExpression="lease_id = :lease AND reset_cleanup_command = :command",
                ExpressionAttributeValues={
                    ":pending": {"BOOL": summaries[0]["cleanup_pending"]},
                    ":lease": {"S": proof.lease_id},
                    ":command": {"S": payload["command_id"]},
                },
            )
        runtime.targets.api.update_item(
            TableName=runtime.targets.table,
            Key={"operation_id": {"S": proof.owner_operation_id}},
            UpdateExpression="SET " + field + "_complete = :yes",
            ConditionExpression="lease_id = :lease AND " + field + "_command = :command",
            ExpressionAttributeValues={
                ":yes": {"BOOL": True},
                ":lease": {"S": proof.lease_id},
                ":command": {"S": payload["command_id"]},
            },
        )
        return {"complete": True}
    raise ValueError("invalid RESET task")


def find_command(api: Any, proof: Any, plan: dict[str, Any], field: str) -> str:
    expected = command(
        operation_id=proof.owner_operation_id,
        lease_id=proof.lease_id,
        action="RESET_CLEANUP" if field == "reset_cleanup" else "RESET_PREPARE",
    )
    matches: list[str] = []
    pagination: dict[str, str] = {}
    tokens: set[str] = set()
    while True:
        response = api.list_commands(
            InstanceId=plan["target"]["instance_id"], MaxResults=50, **pagination
        )
        for item in response["Commands"]:
            if item.get("Comment") != "Wishicraft " + field + " " + proof.owner_operation_id:
                continue
            if (
                item.get("InstanceIds") != [plan["target"]["instance_id"]]
                or item.get("Targets") not in (None, [])
                or item.get("DocumentName") != "AWS-RunShellScript"
                or item.get("Parameters") != {"commands": [expected], "executionTimeout": ["360"]}
            ):
                raise ValueError("RESET command observation mismatch")
            matches.append(item["CommandId"])
        token = response.get("NextToken")
        if not token:
            break
        if token in tokens:
            raise ValueError("RESET command pagination incomplete")
        tokens.add(token)
        pagination = {"NextToken": token}
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise RuntimeError("RESET_COMMAND_OUTCOME_UNKNOWN")
    return matches[0]
