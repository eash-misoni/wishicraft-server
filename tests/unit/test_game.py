from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from wishicraft.game import Game, GameLifecycle, GameRepository, MaterializationState


class FakeDynamo:
    def __init__(self) -> None:
        self.puts: list[dict[str, object]] = []

    def put_item(self, **kwargs: object) -> object:
        self.puts.append(kwargs)
        return {}


def game() -> Game:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    return Game(
        game_id="game-vanilla-main",
        display_name="Wishicraft Vanilla",
        normalized_display_name="wishicraft-vanilla",
        lifecycle_state=GameLifecycle.ACTIVE,
        materialization_state=MaterializationState.MATERIALIZED,
        package_id="vanilla",
        package_version="initial-fixed-version",
        runtime_class="default",
        idle_shutdown_minutes=30,
        world_generation=1,
        created_at=now,
        updated_at=now,
    )


def test_game_registration_is_unique_and_contains_logical_state_only() -> None:
    api = FakeDynamo()
    GameRepository(api, table_name="games").register(game())
    request = api.puts[0]
    assert request["ConditionExpression"] == "attribute_not_exists(game_id)"
    item = cast(dict[str, object], request["Item"])
    rendered = str(item).lower()
    assert "default" in rendered
    for physical in ("image", "java", "memory", "docker", "compose", "xmx", "xms"):
        assert physical not in rendered


def test_game_contract_rejects_invalid_identity_and_policy() -> None:
    with pytest.raises(ValueError, match="game identity"):
        Game(**{**game().__dict__, "game_id": "world-directory"})
    with pytest.raises(ValueError, match="numeric policy"):
        Game(**{**game().__dict__, "idle_shutdown_minutes": 0})
