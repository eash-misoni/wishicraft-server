"""Proposed D-098 policy; an empty declaration enables no Game."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from wishicraft.runtime_catalog import RuntimeCatalog


def policies(value: str, catalog: RuntimeCatalog) -> dict[str, dict[str, int]]:
    raw: Any = json.loads(value)
    if not isinstance(raw, dict):
        raise ValueError("invalid Reset declaration")
    for game, policy in raw.items():
        catalog.data_source(game)
        if not isinstance(policy, dict) or set(policy) != {
            "fixed_seed",
            "retain_previous",
            "minimum_free_bytes",
        }:
            raise ValueError("invalid Reset policy")
        if any(not isinstance(v, int) or isinstance(v, bool) for v in policy.values()):
            raise ValueError("invalid Reset policy number")
        if not -(2**63) <= policy["fixed_seed"] < 2**63:
            raise ValueError("invalid fixed seed")
        if not 1 <= policy["retain_previous"] <= 20 or policy["minimum_free_bytes"] < 2**30:
            raise ValueError("unsafe Reset capacity/retention declaration")
    return dict(raw)


def configured() -> dict[str, dict[str, int]]:
    catalog = RuntimeCatalog.parse(os.environ["RUNTIME_GAMES"])
    result = policies(os.environ.get("RESET_POLICIES", "{}"), catalog)
    if os.environ.get("GAME_CREATION") == "1":
        import importlib

        from wishicraft.runtime_catalog import configured_catalog
        from wishicraft.web_status import decode

        api = importlib.import_module("boto3").client("dynamodb")
        dynamic = configured_catalog()
        assert dynamic is not None
        for game in dynamic.game_ids:
            if game in catalog.game_ids:
                continue
            raw = api.get_item(
                TableName=os.environ["GAMES_TABLE"],
                Key={"game_id": {"S": game}},
                ConsistentRead=True,
            )["Item"]
            if raw.get("materialization_state") != {"S": "MATERIALIZED"}:
                continue
            creation = decode(raw["creation"])
            policy = creation.get("reset_policy")
            if policy is not None:
                result.update(policies(json.dumps({game: policy}), dynamic))
    return result


def seed(operation_id: str, mode: str, policy: dict[str, int]) -> int:
    if mode == "fixed":
        return policy["fixed_seed"]
    if mode != "new":
        raise ValueError("invalid Reset seed mode")
    # UUID-backed Operation identity supplies entropy once, without a second mutable seed source.
    return int.from_bytes(hashlib.sha256(operation_id.encode()).digest()[:8], "big", signed=True)
