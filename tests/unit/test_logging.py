from __future__ import annotations

import json

from wishicraft.logging import structured_log


def test_structured_log_includes_required_fields_and_redacts_secrets() -> None:
    rendered = structured_log(
        operation_id="op-example",
        game_id="game-vanilla-main",
        component="config-loader",
        step="VALIDATE",
        result="succeeded",
        extra={"rcon_password": "must-not-appear", "nested": {"bot_token": "must-not-appear"}},
    )

    event = json.loads(rendered)
    assert event["operation_id"] == "op-example"
    assert event["game_id"] == "game-vanilla-main"
    assert event["component"] == "config-loader"
    assert event["step"] == "VALIDATE"
    assert event["result"] == "succeeded"
    assert "must-not-appear" not in rendered
    assert event["extra"] == {"nested": {"bot_token": "[REDACTED]"}, "rcon_password": "[REDACTED]"}
