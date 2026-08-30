from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from nacl.signing import SigningKey

from wishicraft import discord_command_lambda

APPLICATION_ID = "1531887197433757768"
GUILD_ID = "1251169327554625757"
OPERATION_CHANNEL_ID = "1531883129525244015"
PLAYER_ROLE_ID = "1531883392205983765"
ADMIN_ROLE_ID = "1531883595113697410"
TIMESTAMP = "1788060000"


@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> SigningKey:
    key = SigningKey.generate()
    environment = {
        "DISCORD_APPLICATION_ID": APPLICATION_ID,
        "DISCORD_GUILD_ID": GUILD_ID,
        "DISCORD_OPERATION_CHANNEL_ID": OPERATION_CHANNEL_ID,
        "DISCORD_PLAYER_ROLE_ID": PLAYER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": ADMIN_ROLE_ID,
        "DISCORD_PUBLIC_KEY": key.verify_key.encode().hex(),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return key


def payload(*, interaction_type: int = 2) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "1532000000000000001",
        "application_id": APPLICATION_ID,
        "type": interaction_type,
        "token": "non-production-test-token",
        "version": 1,
    }
    if interaction_type == 2:
        value.update(
            {
                "guild_id": GUILD_ID,
                "channel_id": OPERATION_CHANNEL_ID,
                "member": {"roles": [PLAYER_ROLE_ID]},
                "data": {
                    "id": "1532000000000000002",
                    "name": "mc",
                    "type": 1,
                    "options": [{"name": "status", "type": 1}],
                },
            }
        )
    return value


def event(
    value: object,
    key: SigningKey,
    *,
    raw: bytes | None = None,
    encoded: bool = False,
) -> dict[str, object]:
    body = raw if raw is not None else json.dumps(value, separators=(",", ":")).encode()
    signature = key.sign(TIMESTAMP.encode() + body).signature.hex()
    return {
        "headers": {
            "x-signature-ed25519": signature,
            "x-signature-timestamp": TIMESTAMP,
        },
        "body": base64.b64encode(body).decode() if encoded else body.decode(),
        "isBase64Encoded": encoded,
    }


def response_body(response: dict[str, object]) -> dict[str, object]:
    body = response["body"]
    assert isinstance(body, str)
    result = json.loads(body)
    assert isinstance(result, dict)
    return result


def test_ping_returns_pong(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(interaction_type=1), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response) == {"type": 1}


def test_valid_command_is_honest_phase7b_ephemeral_response(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(), signing_key), None)
    assert response["statusCode"] == 200
    assert response_body(response) == {
        "type": 4,
        "data": {
            "content": "Discord ingress verified; no Minecraft operation was submitted.",
            "flags": 64,
            "allowed_mentions": {"parse": []},
        },
    }


def test_base64_command_uses_same_boundary(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event(payload(), signing_key, encoded=True), None)
    assert response["statusCode"] == 200


def test_invalid_signature_precedes_malformed_json(signing_key: SigningKey) -> None:
    signed = event({}, signing_key, raw=b"not-json")
    headers = signed["headers"]
    assert isinstance(headers, dict)
    headers["x-signature-ed25519"] = "0" * 128

    response = discord_command_lambda.handler(signed, None)

    assert response["statusCode"] == 401
    assert response_body(response) == {"error": "invalid request"}


def test_signed_malformed_json_is_safe_400(signing_key: SigningKey) -> None:
    response = discord_command_lambda.handler(event({}, signing_key, raw=b"not-json"), None)
    assert response["statusCode"] == 400
    assert response_body(response) == {"error": "invalid interaction"}


def test_unauthorized_request_has_no_role_or_internal_detail(signing_key: SigningKey) -> None:
    value = payload()
    value["member"] = {"roles": []}
    response = discord_command_lambda.handler(event(value, signing_key), None)
    rendered = json.dumps(response_body(response))
    assert response["statusCode"] == 200
    assert "not available" in rendered
    assert PLAYER_ROLE_ID not in rendered
    assert ADMIN_ROLE_ID not in rendered
    assert "arn:" not in rendered


def test_invalid_public_key_configuration_is_safe_500(
    signing_key: SigningKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", "invalid")
    response = discord_command_lambda.handler(event(payload(), signing_key), None)
    assert response["statusCode"] == 500
    assert response_body(response) == {"error": "service unavailable"}


def test_phase7b_handler_has_no_control_plane_clients() -> None:
    assert discord_command_lambda.__file__ is not None
    source = Path(discord_command_lambda.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "boto3",
        "OperationAdmission",
        "Reconcile",
        "StartExecution",
        "dynamodb",
        "ec2",
        "ssm",
        "route53",
    ):
        assert forbidden not in source
