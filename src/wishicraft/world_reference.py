"""Game world selection. Missing current means the unchanged legacy data directory."""

from __future__ import annotations

import re
from typing import Any


def data_source(game_id: str, world_id: str | None = None) -> str:
    if re.fullmatch(r"game-[a-z0-9-]+", game_id) is None:
        raise ValueError("invalid Game identity")
    base = f"/srv/minecraft/games/{game_id}"
    if world_id is None:
        return base + "/server"
    if re.fullmatch(r"op-[a-z0-9-]{1,100}", world_id) is None:
        raise ValueError("invalid world identity")
    return base + "/worlds/" + world_id + "/server"


def validate_source(game_id: str, value: str) -> str:
    if value == data_source(game_id):
        return value
    prefix = f"/srv/minecraft/games/{game_id}/worlds/"
    if not value.startswith(prefix) or not value.endswith("/server"):
        raise ValueError("world data binding mismatch")
    if data_source(game_id, value[len(prefix) : -len("/server")]) != value:
        raise ValueError("world data binding mismatch")
    return value


def selected_source(api: Any, table: str, game_id: str) -> str:
    record = api.get_item(TableName=table, Key={"game_id": {"S": game_id}}, ConsistentRead=True)[
        "Item"
    ]
    if (
        record["game_id"] != {"S": game_id}
        or record["lifecycle_state"] != {"S": "ACTIVE"}
        or record["materialization_state"] != {"S": "MATERIALIZED"}
    ):
        raise ValueError("world Game is not active and materialized")
    world = record["world"]["M"]
    current = world.get("current_id")
    if current is None:
        return data_source(game_id)
    if not isinstance(current, dict) or set(current) != {"S"}:
        raise ValueError("invalid selected world")
    return data_source(game_id, current["S"])
