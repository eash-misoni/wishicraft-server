from datetime import UTC, datetime
from pathlib import Path

from wishicraft.game import GameLifecycle, MaterializationState
from wishicraft.game_admin import initial_game

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_initial_game_is_derived_from_canonical_logical_configuration_only() -> None:
    game = initial_game(REPOSITORY_ROOT, "dev", now=datetime(2026, 8, 29, tzinfo=UTC))
    assert game.game_id == "game-vanilla-main"
    assert game.display_name == "Wishicraft Vanilla"
    assert game.lifecycle_state is GameLifecycle.ACTIVE
    assert game.materialization_state is MaterializationState.MATERIALIZED
    assert game.runtime_class == "default"
    assert game.idle_shutdown_minutes == 30
    serialized = str(game.to_item()).lower()
    for physical in ("itzg", "java25", "2816", "xmx", "docker", "compose", "ami-"):
        assert physical not in serialized
