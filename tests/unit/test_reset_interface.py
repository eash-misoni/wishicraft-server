from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nacl.signing import SigningKey

from tests.unit.test_discord_interactions import PLAYER_ROLE_ID, command_payload, configuration
from wishicraft.discord_interactions import MalformedInteraction, parse_and_authorize
from wishicraft.reset_commands import extend
from wishicraft.two_game_admin import declaration

GAME = "game-vanilla-secondary"


def payload() -> dict[str, Any]:
    value: dict[str, Any] = command_payload(subcommand="start", roles=[PLAYER_ROLE_ID])
    value["data"]["options"] = [
        {
            "type": 1,
            "name": "reset",
            "options": [
                {"type": 3, "name": "game", "value": GAME},
                {"type": 5, "name": "confirm", "value": True},
                {"type": 3, "name": "seed", "value": "new"},
            ],
        }
    ]
    return value


def test_player_reset_requires_explicit_enabled_game_and_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_GAMES", json.dumps(["game-vanilla-main", GAME]))
    monkeypatch.setenv(
        "RESET_POLICIES",
        json.dumps(
            {GAME: {"fixed_seed": 0, "retain_previous": 3, "minimum_free_bytes": 4 * 1024**3}}
        ),
    )
    config = configuration(SigningKey.generate())
    result = parse_and_authorize(json.dumps(payload()).encode(), config=config)
    assert result.kind.value == "RESET" and result.seed_mode == "new" and result.confirmed
    for name, changed in [("game", "game-vanilla-main"), ("confirm", False), ("seed", "unknown")]:
        value = payload()
        for option in value["data"]["options"][0]["options"]:
            if option["name"] == name:
                option["value"] = changed
        with pytest.raises(MalformedInteraction):
            parse_and_authorize(json.dumps(value).encode(), config=config)
    monkeypatch.setenv("RESET_POLICIES", "{}")
    with pytest.raises(MalformedInteraction):
        parse_and_authorize(json.dumps(payload()).encode(), config=config)


def test_command_extension_keeps_existing_commands_and_disabled_policy() -> None:
    old = declaration(Path(__file__).resolve().parents[2], now=datetime(2026, 9, 12, tzinfo=UTC))[
        "discord_commands"
    ]
    assert extend(old, ()) == old
    result = extend(old, (GAME,))
    assert result[0]["options"][:-1] == old[0]["options"]
    assert result[0]["options"][-1]["name"] == "reset"


def test_sdk_total_attempt_one_has_no_internal_send_retry() -> None:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]
    from botocore.exceptions import EndpointConnectionError  # type: ignore[import-untyped]

    client = boto3.client(
        "ssm",
        region_name="ap-northeast-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
        config=Config(retries={"total_max_attempts": 1}),
    )
    attempts = 0

    def failed_send(**kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        raise EndpointConnectionError(endpoint_url="synthetic-no-network")

    client.meta.events.register("before-send.ssm.SendCommand", failed_send)
    with pytest.raises(EndpointConnectionError):
        client.send_command(
            InstanceIds=["i-0123456789abcdef0"],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": ["synthetic"]},
        )
    assert attempts == client.meta.config.retries["total_max_attempts"] == 1
