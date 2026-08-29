"""Minimal Phase 4 Game desired-state entity and repository."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from wishicraft.system_state import utc_timestamp


class GameLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETING = "DELETING"


class MaterializationState(StrEnum):
    UNMATERIALIZED = "UNMATERIALIZED"
    MATERIALIZING = "MATERIALIZING"
    MATERIALIZED = "MATERIALIZED"
    MATERIALIZATION_FAILED = "MATERIALIZATION_FAILED"


@dataclass(frozen=True)
class Game:
    game_id: str
    display_name: str
    normalized_display_name: str
    lifecycle_state: GameLifecycle
    materialization_state: MaterializationState
    package_id: str
    package_version: str
    runtime_class: str
    idle_shutdown_minutes: int
    world_generation: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if re.fullmatch(r"game-[a-z0-9]+(?:-[a-z0-9]+)*", self.game_id) is None:
            raise ValueError("invalid game identity")
        strings = (
            self.display_name,
            self.normalized_display_name,
            self.package_id,
            self.package_version,
            self.runtime_class,
        )
        if not all(strings):
            raise ValueError("game logical fields must be non-empty")
        if self.idle_shutdown_minutes <= 0 or self.world_generation <= 0:
            raise ValueError("invalid game numeric policy")
        utc_timestamp(self.created_at)
        utc_timestamp(self.updated_at)

    def to_item(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "schema_version": 1,
            "version": 1,
            "display_name": self.display_name,
            "normalized_display_name": self.normalized_display_name,
            "lifecycle_state": self.lifecycle_state.value,
            "materialization_state": self.materialization_state.value,
            "created_from": {"template_id": None, "template_version": None},
            "package": {"package_id": self.package_id, "package_version": self.package_version},
            "runtime": {
                "class": self.runtime_class,
                "idle_shutdown_minutes": self.idle_shutdown_minutes,
            },
            "world": {
                "seed": None,
                "difficulty": None,
                "hardcore": None,
                "generation": self.world_generation,
            },
            "created_at": utc_timestamp(self.created_at),
            "updated_at": utc_timestamp(self.updated_at),
            "last_started_at": None,
            "last_backup_at": None,
        }


class DynamoApi(Protocol):
    def put_item(self, **kwargs: object) -> object: ...


class GameRepository:
    def __init__(self, api: DynamoApi, *, table_name: str) -> None:
        self._api = api
        self._table = table_name

    def register(self, game: Game) -> None:
        self._api.put_item(
            TableName=self._table,
            Item=_attribute_map(game.to_item()),
            ConditionExpression="attribute_not_exists(game_id)",
        )


def _attribute(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": _attribute_map(value)}
    raise TypeError("unsupported game value")


def _attribute_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _attribute(item) for key, item in value.items()}
