"""Freeze the two ends before any save/stop. Execution uses existing host actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from wishicraft.runtime_catalog import configured_catalog
from wishicraft.runtime_contract import validate_target


def prepare_switch(runtime: Any, proof: Any, state: dict[str, object], now: datetime) -> None:
    runtime.coordinator.leases.verify_owned(proof, now=now)
    catalog = configured_catalog()
    if catalog is None:
        raise ValueError("SWITCH is not configured")
    raw = runtime.targets.api.get_item(
        TableName=runtime.targets.table,
        Key={"operation_id": {"S": proof.owner_operation_id}},
        ConsistentRead=True,
    )["Item"]
    if raw["operation_type"] != {"S": "SWITCH"} or raw["lease_id"] != {"S": proof.lease_id}:
        raise ValueError("SWITCH ownership mismatch")
    if "switch_source" in raw or "runtime_target" in raw:
        # A retry must never recapture an already replaced runtime as its source.
        source = validate_target({k: v["S"] for k, v in raw["switch_source"]["M"].items()})
        target = validate_target({k: v["S"] for k, v in raw["runtime_target"]["M"].items()})
        if target["run_id"] != proof.owner_operation_id or source["game_id"] == target["game_id"]:
            raise ValueError("SWITCH pair mismatch")
        return
    observation = state.get("observation")
    if (
        state.get("health") != "HEALTHY"
        or state.get("desired_state") != "RUNNING"
        or state.get("observation_errors") != []
        or state.get("discrepancies") != []
        or not isinstance(observation, dict)
        or observation.get("ec2_state") != "running"
        or observation.get("runtime_ready") is not True
        or isinstance(observation.get("player_count"), bool)
        or observation.get("player_count") != 0
    ):
        raise ValueError("SWITCH requires a healthy, observed empty running Game")
    execution = observation.get("execution")
    if not isinstance(execution, dict) or execution.get("phase") != "running":
        raise ValueError("SWITCH source unknown")
    source = validate_target(execution.get("target"))
    game_id = raw["target_game_id"]["S"]
    if source["data_source"] != catalog.data_source(source["game_id"]):
        raise ValueError("SWITCH source outside catalog")
    target = {
        "instance_id": runtime.resolver.resolve(),
        "game_id": game_id,
        "data_source": catalog.data_source(game_id),
        "config_digest": runtime.config_digest,
        "run_id": proof.owner_operation_id,
    }
    if source["config_digest"] != target["config_digest"]:
        raise ValueError("SWITCH configuration mismatch")
    runtime.targets.freeze_switch(
        operation_id=proof.owner_operation_id,
        lease_id=proof.lease_id,
        source=source,
        target=target,
    )
