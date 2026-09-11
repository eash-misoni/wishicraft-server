"""Proposed targeted execution contract; the Operation owns the frozen request."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, cast

FIELDS = {"instance_id", "game_id", "data_source", "config_digest", "run_id"}


def validate_target(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("invalid runtime target")
    if not all(isinstance(v, str) for v in value.values()):
        raise ValueError("invalid runtime target value")
    patterns = {
        "instance_id": r"i-[0-9a-f]{17}",
        "game_id": r"game-[a-z0-9-]+",
        "data_source": r"/srv/minecraft/games/[a-z0-9-]+/server",
        "config_digest": r"[0-9a-f]{64}",
        "run_id": r"op-[a-z0-9-]+",
    }
    for key, pattern in patterns.items():
        if re.fullmatch(pattern, value[key]) is None:
            raise ValueError("invalid runtime target " + key)
    if value["data_source"] != "/srv/minecraft/games/" + value["game_id"] + "/server":
        raise ValueError("runtime data binding mismatch")
    return dict(value)


def command(*, operation_id: str, lease_id: str, action: str) -> str:
    if action not in {"START", "STOP"}:
        raise ValueError("invalid runtime action")
    for value in (operation_id, lease_id):
        if re.fullmatch(r"[a-z0-9-]{1,128}", value) is None:
            raise ValueError("invalid operation identity")
    payload = {
        "schema_version": 2,
        "operation_id": operation_id,
        "lease_id": lease_id,
        "action": action,
    }
    encoded = base64.b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    return "sudo /usr/local/libexec/wishicraft/operation-v2 " + encoded


class RuntimeTargetRepository:
    def __init__(self, api: Any, table: str) -> None:
        self.api, self.table = api, table
        self.field = "runtime_target"

    def read(self, operation_id: str) -> dict[str, str]:
        item = self.api.get_item(
            TableName=self.table, Key={"operation_id": {"S": operation_id}}, ConsistentRead=True
        )["Item"]
        return validate_target({k: v["S"] for k, v in item[self.field]["M"].items()})

    def freeze(self, *, operation_id: str, lease_id: str, target: dict[str, str]) -> dict[str, str]:
        if self.field != "runtime_target":
            raise ValueError("SWITCH source must be frozen with destination")
        target = validate_target(target)
        try:
            self.api.update_item(
                TableName=self.table,
                Key={"operation_id": {"S": operation_id}},
                UpdateExpression="SET runtime_target = :target",
                ConditionExpression="lease_id = :lease AND #s IN (:pending, :running) "
                "AND attribute_not_exists(runtime_target)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":target": {"M": {k: {"S": v} for k, v in target.items()}},
                    ":lease": {"S": lease_id},
                    ":pending": {"S": "PENDING"},
                    ":running": {"S": "RUNNING"},
                },
            )
        except Exception:
            # Includes response loss: only a consistent exact read can authorize reuse.
            if self.read(operation_id) != target:
                raise ValueError("frozen runtime target conflict") from None
        return self.read(operation_id)

    def freeze_switch(
        self, *, operation_id: str, lease_id: str, source: dict[str, str], target: dict[str, str]
    ) -> None:
        source, target = validate_target(source), validate_target(target)
        if source["game_id"] == target["game_id"] or source["instance_id"] != target["instance_id"]:
            raise ValueError("invalid SWITCH pair")
        values = {
            ":source": {"M": {k: {"S": v} for k, v in source.items()}},
            ":target": {"M": {k: {"S": v} for k, v in target.items()}},
            ":lease": {"S": lease_id},
            ":switch": {"S": "SWITCH"},
            ":pending": {"S": "PENDING"},
            ":running": {"S": "RUNNING"},
            ":game": {"S": target["game_id"]},
        }
        try:
            self.api.update_item(
                TableName=self.table,
                Key={"operation_id": {"S": operation_id}},
                UpdateExpression="SET switch_source = :source, runtime_target = :target",
                ConditionExpression="lease_id = :lease AND operation_type = :switch "
                "AND target_game_id = :game AND #s IN (:pending, :running) "
                "AND attribute_not_exists(runtime_target) AND attribute_not_exists(switch_source)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues=values,
            )
        except Exception:
            raw = self.api.get_item(
                TableName=self.table,
                Key={"operation_id": {"S": operation_id}},
                ConsistentRead=True,
            )["Item"]
            if (
                raw.get("runtime_target") != values[":target"]
                or raw.get("switch_source") != values[":source"]
            ):
                raise ValueError("frozen SWITCH pair conflict") from None


def select_target(
    runtime: Any, proof: Any, state: dict[str, object], *, action: str
) -> dict[str, str] | None:
    try:
        return cast(dict[str, str], runtime.targets.read(proof.owner_operation_id))
    except KeyError:
        pass
    observation = state.get("observation", {})
    if not isinstance(observation, dict):
        raise ValueError("missing runtime observation")
    if action == "STOP" and observation.get("ec2_state") == "stopped":
        return None
    execution = observation.get("execution")
    target = None
    if isinstance(execution, dict) and (action == "STOP" or execution.get("phase") != "stopped"):
        target = validate_target(execution.get("target"))
    if target is None:
        if action == "STOP" and observation.get("ec2_state") != "stopped":
            raise ValueError("STOP requires observed runtime target")
        target = {
            "instance_id": runtime.resolver.resolve(),
            "game_id": runtime.game_id,
            "data_source": runtime.data_source,
            "config_digest": runtime.config_digest,
            "run_id": proof.owner_operation_id,
        }
    if (
        target["instance_id"] != runtime.resolver.resolve()
        or target["game_id"] != runtime.game_id
        or target["data_source"] != runtime.data_source
        or target["config_digest"] != runtime.config_digest
    ):
        raise ValueError("selected target mismatch")
    return validate_target(
        runtime.targets.freeze(
            operation_id=proof.owner_operation_id, lease_id=proof.lease_id, target=target
        )
    )


def bound_instance(runtime: Any, operation_id: str) -> str:
    target = runtime.targets.read(operation_id)
    if runtime.resolver.resolve() != target["instance_id"]:
        raise ValueError("target instance changed")
    return str(target["instance_id"])


def assert_observed(runtime: Any, operation_id: str, state: dict[str, object]) -> None:
    observation = state.get("observation")
    execution = observation.get("execution") if isinstance(observation, dict) else None
    if (
        not isinstance(execution, dict)
        or execution.get("phase") != "running"
        or execution.get("target") != runtime.targets.read(operation_id)
    ):
        raise ValueError("runtime execution observation mismatch")
