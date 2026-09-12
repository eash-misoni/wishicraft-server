"""Proposed Reset ownership, immutable source/destination and selected-world CAS."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from wishicraft.reset_policy import configured, seed
from wishicraft.runtime_contract import validate_target
from wishicraft.world_reference import data_source, selected_source


def operation(runtime: Any, proof: Any) -> dict[str, Any]:
    return dict(
        runtime.targets.api.get_item(
            TableName=runtime.targets.table,
            Key={"operation_id": {"S": proof.owner_operation_id}},
            ConsistentRead=True,
        )["Item"]
    )


def prepare(runtime: Any, proof: Any, state: dict[str, object], now: datetime) -> None:
    runtime.coordinator.leases.verify_owned(proof, now=now)
    raw = operation(runtime, proof)
    if raw["operation_type"] != {"S": "RESET"} or raw["lease_id"] != {"S": proof.lease_id}:
        raise ValueError("RESET ownership mismatch")
    game = raw["target_game_id"]["S"]
    policy = configured().get(game)
    if policy is None:
        raise ValueError("Game does not support RESET")
    if "reset_plan" in raw:
        plan = json.loads(raw["reset_plan"]["S"])
        if plan["target"]["run_id"] != proof.owner_operation_id or plan["policy"] != policy:
            raise ValueError("RESET immutable plan mismatch")
        validate_target(plan["source"])
        validate_target(plan["target"])
        return
    obs = state.get("observation")
    if (
        state.get("game_id") != game
        or state.get("health") != "HEALTHY"
        or state.get("desired_state") != "RUNNING"
        or state.get("observation_errors") != []
        or state.get("discrepancies") != []
        or not isinstance(obs, dict)
        or obs.get("ec2_state") != "running"
        or obs.get("runtime_ready") is not True
        or isinstance(obs.get("player_count"), bool)
        or obs.get("player_count") != 0
    ):
        raise ValueError("RESET requires the selected running healthy empty Game")
    execution = obs.get("execution")
    if not isinstance(execution, dict) or execution.get("phase") != "running":
        raise ValueError("RESET source runtime is unknown")
    source = validate_target(execution.get("target"))
    if (
        source["game_id"] != game
        or source["instance_id"] != runtime.resolver.resolve()
        or source["config_digest"] != runtime.config_digest
        or source["data_source"]
        != selected_source(runtime.targets.api, os.environ["GAMES_TABLE"], game)
    ):
        raise ValueError("RESET selected source mismatch")
    target = validate_target(
        {
            **source,
            "data_source": data_source(game, proof.owner_operation_id),
            "run_id": proof.owner_operation_id,
        }
    )
    plan = {
        "schema_version": 1,
        "source": source,
        "target": target,
        "policy": policy,
        "seed": seed(proof.owner_operation_id, raw["reset_seed_mode"]["S"], policy),
    }
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    values = {
        ":plan": {"S": encoded},
        ":source": {"M": {k: {"S": v} for k, v in source.items()}},
        ":target": {"M": {k: {"S": v} for k, v in target.items()}},
        ":lease": {"S": proof.lease_id},
        ":kind": {"S": "RESET"},
        ":running": {"S": "RUNNING"},
    }
    try:
        runtime.targets.api.update_item(
            TableName=runtime.targets.table,
            Key={"operation_id": {"S": proof.owner_operation_id}},
            UpdateExpression=(
                "SET reset_plan = :plan, switch_source = :source, runtime_target = :target"
            ),
            ConditionExpression="lease_id = :lease AND operation_type = :kind AND #s = :running "
            "AND attribute_not_exists(reset_plan) AND attribute_not_exists(runtime_target) "
            "AND attribute_not_exists(switch_source)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=values,
        )
    except Exception:
        current = operation(runtime, proof)
        if any(
            current.get(key) != values[value]
            for key, value in [
                ("reset_plan", ":plan"),
                ("switch_source", ":source"),
                ("runtime_target", ":target"),
            ]
        ):
            raise ValueError("RESET plan freeze conflict") from None


def commit_selection(runtime: Any, proof: Any, now: datetime) -> None:
    """Only after the durable host preparation proof. Operation remains owner across CAS."""
    runtime.coordinator.leases.verify_owned(proof, now=now)
    raw = operation(runtime, proof)
    plan = json.loads(raw["reset_plan"]["S"])
    game, target = plan["target"]["game_id"], plan["target"]["run_id"]
    api, table = runtime.targets.api, os.environ["GAMES_TABLE"]
    current = selected_source(api, table, game)
    if current == plan["target"]["data_source"]:
        return
    if current != plan["source"]["data_source"]:
        raise ValueError("RESET current world changed")
    values = {":new": {"S": target}}
    condition = "attribute_not_exists(#world.current_id)"
    if current != data_source(game):
        values[":old"] = {"S": current.split("/")[-2]}
        condition = "#world.current_id = :old"
    try:
        api.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": os.environ["LOCKS_TABLE"],
                        "Key": {"lock_name": {"S": os.environ["GLOBAL_LOCK_NAME"]}},
                        "ConditionExpression": (
                            "owner_operation_id = :operation AND lease_id = :lease "
                            "AND lease_expires_at > :now"
                        ),
                        "ExpressionAttributeValues": {
                            ":operation": {"S": proof.owner_operation_id},
                            ":lease": {"S": proof.lease_id},
                            ":now": {"N": str(int(now.timestamp()))},
                        },
                    }
                },
                {
                    "ConditionCheck": {
                        "TableName": runtime.targets.table,
                        "Key": {"operation_id": {"S": proof.owner_operation_id}},
                        "ConditionExpression": (
                            "lease_id = :lease AND #s = :running AND reset_plan = :plan "
                            "AND operation_type = :kind"
                        ),
                        "ExpressionAttributeNames": {"#s": "status"},
                        "ExpressionAttributeValues": {
                            ":lease": {"S": proof.lease_id},
                            ":running": {"S": "RUNNING"},
                            ":plan": raw["reset_plan"],
                            ":kind": {"S": "RESET"},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": table,
                        "Key": {"game_id": {"S": game}},
                        "UpdateExpression": "SET #world.current_id = :new",
                        "ConditionExpression": condition,
                        "ExpressionAttributeNames": {"#world": "world"},
                        "ExpressionAttributeValues": values,
                    }
                },
            ]
        )
    except Exception:
        # An exact consistent selected reference establishes committed response loss.
        if selected_source(api, table, game) != plan["target"]["data_source"]:
            raise
