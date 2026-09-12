"""Keep the small human guide aligned with the actual current generated schema."""

from datetime import UTC, datetime
from pathlib import Path

from wishicraft.reset_commands import extend
from wishicraft.two_game_admin import declaration


def test_guide_covers_generated_current_commands_and_required_reset_options() -> None:
    root = Path(__file__).resolve().parents[2]
    commands = extend(
        declaration(root, now=datetime(2026, 9, 12, tzinfo=UTC))["discord_commands"],
        ("game-vanilla-secondary",),
    )
    guide = (root / "docs/discord_user_guide.md").read_text()
    options = {option["name"]: option for option in commands[0]["options"]}
    assert set(options) == {"status", "start", "stop", "backup", "switch", "reset"}
    for command in options:
        assert f"`/mc {command}" in guide
    assert {option["name"] for option in options["reset"]["options"] if option["required"]} == {
        "game",
        "confirm",
        "seed",
    }
    assert "seed 0" in guide and "seed:new" in guide and "confirm:true" in guide
    assert "EBS喪失" in guide and "race" in guide and "直近3個" in guide
