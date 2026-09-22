"""D-084 command artifact: only Game options change; no registration side effect."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def autocomplete(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = deepcopy(commands)
    found = set()
    for command in result[0]["options"]:
        for option in command.get("options", []):
            if option["name"] == "game":
                if command["name"] not in {"start", "switch", "reset"}:
                    raise ValueError("unexpected Game consumer")
                option.pop("choices", None)
                option["autocomplete"] = True
                found.add(command["name"])
    if found != {"start", "switch", "reset"}:
        raise ValueError("incomplete Game discovery commands")
    return result
