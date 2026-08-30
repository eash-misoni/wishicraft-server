from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase7_mvp_command_schema_is_exact_and_guild_only() -> None:
    schema = json.loads((ROOT / "config/discord/commands.v1.json").read_text(encoding="utf-8"))

    assert isinstance(schema, list)
    assert len(schema) == 1
    command = schema[0]
    assert command["type"] == 1
    assert command["name"] == "mc"
    assert command["integration_types"] == [0]
    assert command["contexts"] == [0]
    assert [(option["name"], option["type"]) for option in command["options"]] == [
        ("status", 1),
        ("start", 1),
        ("stop", 1),
    ]
    assert all(set(option) == {"type", "name", "description"} for option in command["options"])
