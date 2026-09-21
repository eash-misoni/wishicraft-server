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
            "description": "対応Gameのworldを新しくして同じGameでRESETします",
            "options": [
                {
                    "type": 3,
                    "name": "game",
                    "description": "現在稼働中のRESET対応Gameを選択します",
                    "required": True,
                    "choices": [{"name": game, "value": game} for game in enabled_games],
                },
                {
                    "type": 5,
                    "name": "confirm",
                    "description": "worldを新しくすることを確認します",
                    "required": True,
                },
                {
                    "type": 3,
                    "name": "seed",
                    "description": "固定seedまたは新しいseedを選択します",
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
