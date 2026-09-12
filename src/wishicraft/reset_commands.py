"""Pure command-body extension; registration remains an explicitly approved operator action."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def extend(commands: list[dict[str, Any]], enabled_games: tuple[str, ...]) -> list[dict[str, Any]]:
    result = deepcopy(commands)
    if len(result) != 1 or result[0].get("name") != "mc":
        raise ValueError("expected canonical mc command")
    names = {option["name"] for option in result[0]["options"]}
    if names != {"status", "start", "stop", "backup", "switch"}:
        raise ValueError("expected D-097 command predecessor")
    if not enabled_games:
        return result
    result[0]["options"].append(
        {
            "type": 1,
            "name": "reset",
            "description": "Replace the empty supported Game's world; no Snapshot on each reset",
            "options": [
                {
                    "type": 3,
                    "name": "game",
                    "description": "Currently running Reset-enabled Game",
                    "required": True,
                    "choices": [{"name": game, "value": game} for game in enabled_games],
                },
                {
                    "type": 5,
                    "name": "confirm",
                    "description": "Confirm resetting this empty Game",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "seed",
                    "description": "Use the declared fixed seed or a new seed",
                    "required": True,
                    "choices": [
                        {"name": "Fixed seed", "value": "fixed"},
                        {"name": "New seed", "value": "new"},
                    ],
                },
            ],
        }
    )
    return result
