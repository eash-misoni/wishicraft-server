"""Read-only projection of the current backend contract into per-Game Web records.

Current declarations still resolve the default Vanilla runtime for two Games.
No production lookup, Game registration or runtime expansion occurs here.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from wishicraft.game_admin import initial_game
from wishicraft.reset_commands import extend
from wishicraft.reset_policy import policies
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.two_game_admin import declaration


def sources(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Explicit projection; never serialize configuration or the full declaration."""
    document = declaration(root, now=datetime(2000, 1, 1, tzinfo=UTC))
    stage = yaml.safe_load((root / "config/stages/dev.yaml").read_text())
    catalog = RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text())
    reset = policies((root / "config/reset-dev.json").read_text(), catalog)
    runtime = stage["host_runtime"]["minecraft"]
    if runtime["type"] != "VANILLA" or not re.fullmatch(r"\d+(?:\.\d+)+", runtime["version"]):
        raise ValueError("runtime changed: review edition/client guidance before building")
    # This adapter reflects the current backend declarations, which still support two Games.
    # The public renderer consumes records keyed by ID, never catalog position.
    records = [
        initial_game(root, "dev", now=datetime(2000, 1, 1, tzinfo=UTC)).to_item(),
        document["game"],
    ]
    games = []
    for record in records:
        if record["runtime"]["class"] != "default" or record["package"]["package_id"] != "vanilla":
            raise ValueError(f"{record['game_id']}: unresolved runtime reference")
        games.append(
            {
                "id": record["game_id"],
                "name": record["display_name"],
                "edition": "Java Edition",
                "version": runtime["version"],
                "server": runtime["type"],
            }
        )
    commands = extend(document["discord_commands"], tuple(reset))
    for command in commands[0]["options"]:
        identifiers = [command["name"]]
        for option in command.get("options", []):
            identifiers.append(option["name"])
            identifiers.extend(choice["value"] for choice in option.get("choices", []))
        if any(not re.fullmatch(r"[a-z0-9-]+", value) for value in identifiers):
            raise ValueError("unsafe command schema text")
    return (
        commands,
        games,
        {
            "reset": reset,
        },
    )
