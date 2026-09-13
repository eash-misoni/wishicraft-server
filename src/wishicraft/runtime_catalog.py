"""Proposed two-Game allowlist, rendered from Git; never a mutable active pointer."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeCatalog:
    game_ids: tuple[str, ...]

    @classmethod
    def parse(cls, value: str) -> RuntimeCatalog:
        raw = json.loads(value)
        if (
            not isinstance(raw, list)
            or not raw
            or not all(isinstance(x, str) and re.fullmatch(r"game-[a-z0-9-]+", x) for x in raw)
            or len(set(raw)) != len(raw)
        ):
            raise ValueError("invalid Game catalog")
        return cls(tuple(raw))

    def data_source(self, game_id: str) -> str:
        if game_id not in self.game_ids:
            raise ValueError("Game is outside runtime allowlist")
        return f"/srv/minecraft/games/{game_id}/server"

    def serialize(self) -> str:
        return json.dumps(self.game_ids, separators=(",", ":"))


def configured_catalog() -> RuntimeCatalog | None:
    value = os.environ.get("RUNTIME_GAMES")
    if not value:
        return None
    catalog = RuntimeCatalog.parse(value)
    if os.environ.get("GAME_CREATION") == "1":
        import importlib

        from wishicraft.game_creation import registry_ids

        api = importlib.import_module("boto3").client("dynamodb")
        return RuntimeCatalog(registry_ids(api, os.environ["GAMES_TABLE"], catalog.game_ids))
    return catalog


def selected_game(api: Any, table: str, system_id: str, default_game: str) -> str:
    """Only the legacy unset selection falls back to A. Malformed state fails closed."""
    raw = api.get_item(TableName=table, Key={"system_id": {"S": system_id}}, ConsistentRead=True)[
        "Item"
    ]
    selected = raw.get("desired_game_id")
    if selected is None or selected == {"NULL": True}:
        return default_game
    if not isinstance(selected, dict) or set(selected) != {"S"}:
        raise ValueError("invalid selected Game")
    game_id = selected["S"]
    catalog = configured_catalog()
    if catalog is None or not isinstance(game_id, str):
        raise ValueError("missing Game catalog")
    catalog.data_source(game_id)
    return game_id


def bind_operation(runtime: Any, operation_id: str, *, action: str) -> None:
    """Resolve every invocation from its durable Operation, never cached Lambda selection."""
    catalog = configured_catalog()
    if catalog is None:
        return
    raw = runtime.targets.api.get_item(
        TableName=runtime.targets.table,
        Key={"operation_id": {"S": operation_id}},
        ConsistentRead=True,
    )["Item"]
    source = (
        action == "STOP"
        and raw["operation_type"] in ({"S": "SWITCH"}, {"S": "RESET"})
        and "switch_source" in raw
    )
    runtime.targets.field = "switch_source" if source else "runtime_target"
    if source:
        game_id = raw["switch_source"]["M"]["game_id"]["S"]
    else:
        game_id = raw["target_game_id"]["S"]
    runtime.game_id = game_id
    catalog.data_source(game_id)
    if os.environ.get("RESET_CONTRACT") == "1":
        from wishicraft.world_reference import selected_source

        if runtime.targets.field in raw:
            runtime.data_source = runtime.targets.read(operation_id)["data_source"]
        else:
            runtime.data_source = selected_source(
                runtime.targets.api, os.environ["GAMES_TABLE"], game_id
            )
    else:
        runtime.data_source = catalog.data_source(game_id)
