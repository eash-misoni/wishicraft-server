from __future__ import annotations

import base64
import json
from collections.abc import Iterable

import pytest
from nacl.signing import SigningKey

from wishicraft.discord_interactions import (
    DiscordIngressConfig,
    InteractionKind,
    MalformedInteraction,
    SignatureRejected,
    UnauthorizedInteraction,
    parse_and_authorize,
    raw_body_from_event,
    verify_signature,
)

APPLICATION_ID = "1531887197433757768"
GUILD_ID = "1251169327554625757"
OPERATION_CHANNEL_ID = "1531883129525244015"
ADMIN_CHANNEL_ID = "1531883269639897098"
PLAYER_ROLE_ID = "1531883392205983765"
ADMIN_ROLE_ID = "1531883595113697410"
INTERACTION_ID = "1532000000000000001"
COMMAND_ID = "1532000000000000002"
TIMESTAMP = "1788060000"


def configuration(signing_key: SigningKey) -> DiscordIngressConfig:
    return DiscordIngressConfig(
        application_id=APPLICATION_ID,
        guild_id=GUILD_ID,
        operation_channel_id=OPERATION_CHANNEL_ID,
        player_role_id=PLAYER_ROLE_ID,
        admin_role_id=ADMIN_ROLE_ID,
        public_key=signing_key.verify_key.encode().hex(),
    )


def command_payload(
    subcommand: str = "status",
    *,
    application_id: str = APPLICATION_ID,
    guild_id: str = GUILD_ID,
    channel_id: str = OPERATION_CHANNEL_ID,
    roles: Iterable[str] | None = (PLAYER_ROLE_ID,),
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": INTERACTION_ID,
        "application_id": application_id,
        "type": 2,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "token": "non-production-test-token",
        "version": 1,
        "data": {
            "id": COMMAND_ID,
            "name": "mc",
            "type": 1,
            "options": [{"name": subcommand, "type": 1}],
        },
    }
    if roles is not None:
        payload["member"] = {"roles": list(roles), "user": {"id": "1532000000000000003"}}
    return payload


def signed_event(
    payload: object,
    signing_key: SigningKey,
    *,
    raw_body: bytes | None = None,
    base64_encoded: bool = False,
) -> dict[str, object]:
    body = raw_body if raw_body is not None else json.dumps(payload, separators=(",", ":")).encode()
    signature = signing_key.sign(TIMESTAMP.encode() + body).signature.hex()
    return {
        "version": "2.0",
        "headers": {
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": TIMESTAMP,
        },
        "body": base64.b64encode(body).decode() if base64_encoded else body.decode(),
        "isBase64Encoded": base64_encoded,
    }


def test_valid_signature_uses_exact_raw_body() -> None:
    key = SigningKey.generate()
    body = b'{ "type" : 1, "application_id" : "1531887197433757768" }\n'
    event = signed_event({}, key, raw_body=body)

    raw_body, headers = raw_body_from_event(event)
    verify_signature(raw_body, headers, public_key=key.verify_key.encode().hex())

    assert raw_body == body


def test_base64_body_is_decoded_before_signature_verification() -> None:
    key = SigningKey.generate()
    body = json.dumps(command_payload(), separators=(",", ":")).encode()
    event = signed_event({}, key, raw_body=body, base64_encoded=True)

    raw_body, headers = raw_body_from_event(event)
    verify_signature(raw_body, headers, public_key=key.verify_key.encode().hex())

    assert raw_body == body


@pytest.mark.parametrize(
    "mutation",
    [
        lambda event: event["headers"].pop("X-Signature-Ed25519"),
        lambda event: event["headers"].pop("X-Signature-Timestamp"),
        lambda event: event["headers"].update({"X-Signature-Ed25519": "not-hex"}),
        lambda event: event["headers"].update({"X-Signature-Timestamp": "bad timestamp"}),
        lambda event: event.update({"body": "tampered"}),
    ],
)
def test_missing_malformed_or_invalid_signature_is_rejected(mutation: object) -> None:
    key = SigningKey.generate()
    event = signed_event(command_payload(), key)
    assert callable(mutation)
    mutation(event)
    raw_body, headers = raw_body_from_event(event)

    with pytest.raises(SignatureRejected, match="invalid request"):
        verify_signature(raw_body, headers, public_key=key.verify_key.encode().hex())


@pytest.mark.parametrize(
    "event",
    [
        {"headers": {}, "body": "@@", "isBase64Encoded": True},
        {"headers": {"content-encoding": "gzip"}, "body": "{}"},
        {"headers": {}, "body": {}, "isBase64Encoded": False},
        {"headers": {}, "body": "{}", "isBase64Encoded": "false"},
    ],
)
def test_unsupported_http_body_encoding_is_rejected(event: object) -> None:
    with pytest.raises(SignatureRejected, match="invalid request"):
        raw_body_from_event(event)


def test_invalid_public_key_configuration_is_rejected() -> None:
    key = SigningKey.generate()
    event = signed_event(command_payload(), key)
    raw_body, headers = raw_body_from_event(event)

    with pytest.raises(SignatureRejected, match="invalid request"):
        verify_signature(raw_body, headers, public_key="invalid")


def test_ping_is_parsed_after_signature_boundary() -> None:
    key = SigningKey.generate()
    body = json.dumps(
        {
            "id": INTERACTION_ID,
            "application_id": APPLICATION_ID,
            "type": 1,
            "token": "non-production-test-token",
            "version": 1,
        }
    ).encode()

    interaction = parse_and_authorize(body, config=configuration(key))

    assert interaction.kind is InteractionKind.PING


@pytest.mark.parametrize(
    ("subcommand", "expected"),
    [
        ("status", InteractionKind.STATUS),
        ("start", InteractionKind.START),
        ("stop", InteractionKind.STOP),
    ],
)
def test_mvp_commands_are_strictly_parsed(subcommand: str, expected: InteractionKind) -> None:
    key = SigningKey.generate()
    body = json.dumps(command_payload(subcommand)).encode()

    interaction = parse_and_authorize(body, config=configuration(key))

    assert interaction.kind is expected


@pytest.mark.parametrize(
    "payload",
    [
        command_payload("restart"),
        {**command_payload(), "type": 3},
        {**command_payload(), "data": {"id": COMMAND_ID, "name": "other", "type": 1}},
        {
            **command_payload(),
            "data": {
                "id": COMMAND_ID,
                "name": "mc",
                "type": 1,
                "options": [
                    {"name": "status", "type": 1},
                    {"name": "stop", "type": 1},
                ],
            },
        },
        {
            **command_payload(),
            "data": {
                "id": COMMAND_ID,
                "name": "mc",
                "type": 1,
                "options": [{"name": "status", "type": 1, "options": []}],
            },
        },
    ],
)
def test_unknown_or_malformed_commands_are_rejected(payload: object) -> None:
    key = SigningKey.generate()
    with pytest.raises(MalformedInteraction):
        parse_and_authorize(json.dumps(payload).encode(), config=configuration(key))


def test_duplicate_json_keys_are_rejected() -> None:
    key = SigningKey.generate()
    body = (
        f'{{"id":"{INTERACTION_ID}","id":"{INTERACTION_ID}",'
        f'"application_id":"{APPLICATION_ID}","type":1,"version":1}}'
    ).encode()
    with pytest.raises(MalformedInteraction):
        parse_and_authorize(body, config=configuration(key))


@pytest.mark.parametrize(
    "roles",
    [
        (PLAYER_ROLE_ID,),
        (ADMIN_ROLE_ID,),
        (PLAYER_ROLE_ID, ADMIN_ROLE_ID),
    ],
)
def test_player_or_admin_role_is_authorized(roles: tuple[str, ...]) -> None:
    key = SigningKey.generate()
    interaction = parse_and_authorize(
        json.dumps(command_payload(roles=roles)).encode(), config=configuration(key)
    )
    assert interaction.kind is InteractionKind.STATUS


@pytest.mark.parametrize(
    "payload",
    [
        command_payload(roles=()),
        command_payload(roles=("1532000000000000999",)),
        command_payload(roles=None),
        command_payload(application_id="1532000000000000999"),
        command_payload(guild_id="1532000000000000999"),
        command_payload(channel_id="1532000000000000999"),
        command_payload(channel_id=ADMIN_CHANNEL_ID, roles=(ADMIN_ROLE_ID,)),
    ],
)
def test_missing_role_or_wrong_application_guild_channel_is_rejected(payload: object) -> None:
    key = SigningKey.generate()
    with pytest.raises(UnauthorizedInteraction):
        parse_and_authorize(json.dumps(payload).encode(), config=configuration(key))
