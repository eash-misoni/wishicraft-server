"""Fail-closed Discord Interaction trust boundary for Phase 7B."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

PING = 1
APPLICATION_COMMAND = 2
CHAT_INPUT = 1
SUB_COMMAND = 1
PONG = 1
CHANNEL_MESSAGE_WITH_SOURCE = 4
DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5
EPHEMERAL = 1 << 6
MAX_BODY_BYTES = 64 * 1024
SNOWFLAKE = re.compile(r"^[0-9]{1,20}$")
HEX_PUBLIC_KEY = re.compile(r"^[0-9a-fA-F]{64}$")
HEX_SIGNATURE = re.compile(r"^[0-9a-fA-F]{128}$")
TIMESTAMP = re.compile(r"^[0-9]{1,20}$")
MVP_SUBCOMMANDS = frozenset({"status", "start", "stop"})


class SignatureVerifier(Protocol):
    def verify(self, message: bytes, signature: bytes) -> object: ...


class DiscordRequestError(ValueError):
    """A public-safe request classification without internal detail."""


class SignatureRejected(DiscordRequestError):
    """The request authenticity could not be established."""


class MalformedInteraction(DiscordRequestError):
    """The signed payload does not match the Phase 7B contract."""


class UnauthorizedInteraction(DiscordRequestError):
    """The signed payload is outside the configured authorization boundary."""


class InteractionKind(StrEnum):
    PING = "PING"
    STATUS = "STATUS"
    START = "START"
    STOP = "STOP"


@dataclass(frozen=True)
class DiscordIngressConfig:
    application_id: str
    guild_id: str
    operation_channel_id: str
    player_role_id: str
    admin_role_id: str
    public_key: str

    def __post_init__(self) -> None:
        for value in (
            self.application_id,
            self.guild_id,
            self.operation_channel_id,
            self.player_role_id,
            self.admin_role_id,
        ):
            if SNOWFLAKE.fullmatch(value) is None:
                raise ValueError("invalid Discord public identifier configuration")
        if HEX_PUBLIC_KEY.fullmatch(self.public_key) is None:
            raise ValueError("invalid Discord Public Key configuration")


@dataclass(frozen=True)
class AuthorizedInteraction:
    interaction_id: str
    kind: InteractionKind


def raw_body_from_event(event: object) -> tuple[bytes, dict[str, str]]:
    """Recover API Gateway v2 raw bytes without JSON normalization."""
    if not isinstance(event, dict):
        raise SignatureRejected("invalid request")
    raw_headers = event.get("headers")
    body = event.get("body")
    encoded = event.get("isBase64Encoded", False)
    if (
        not isinstance(raw_headers, dict)
        or not isinstance(body, str)
        or not isinstance(encoded, bool)
    ):
        raise SignatureRejected("invalid request")
    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SignatureRejected("invalid request")
        normalized = key.lower()
        if normalized in headers:
            raise SignatureRejected("invalid request")
        headers[normalized] = value
    content_encoding = headers.get("content-encoding")
    if content_encoding is not None and content_encoding.lower() != "identity":
        raise SignatureRejected("invalid request")
    try:
        raw_body = base64.b64decode(body, validate=True) if encoded else body.encode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise SignatureRejected("invalid request") from error
    if len(raw_body) > MAX_BODY_BYTES:
        raise SignatureRejected("invalid request")
    return raw_body, headers


def verify_signature(
    raw_body: bytes,
    headers: dict[str, str],
    *,
    public_key: str,
    verifier: SignatureVerifier | None = None,
) -> None:
    signature_text = headers.get("x-signature-ed25519")
    timestamp = headers.get("x-signature-timestamp")
    if (
        signature_text is None
        or timestamp is None
        or HEX_SIGNATURE.fullmatch(signature_text) is None
        or TIMESTAMP.fullmatch(timestamp) is None
    ):
        raise SignatureRejected("invalid request")
    if HEX_PUBLIC_KEY.fullmatch(public_key) is None:
        raise SignatureRejected("invalid request")
    try:
        signature = bytes.fromhex(signature_text)
        verify_key = verifier if verifier is not None else VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(timestamp.encode("ascii") + raw_body, signature)
    except (BadSignatureError, ValueError, TypeError, UnicodeError) as error:
        raise SignatureRejected("invalid request") from error


def parse_and_authorize(raw_body: bytes, *, config: DiscordIngressConfig) -> AuthorizedInteraction:
    payload = _load_unique_json(raw_body)
    if not isinstance(payload.get("token"), str) or not payload["token"]:
        raise MalformedInteraction("invalid interaction")
    interaction_type = payload.get("type")
    interaction_id = _snowflake(payload.get("id"))
    if _snowflake(payload.get("application_id")) != config.application_id:
        raise UnauthorizedInteraction("request is not authorized")
    if payload.get("version") != 1:
        raise MalformedInteraction("invalid interaction")
    if interaction_type == PING:
        if "data" in payload:
            raise MalformedInteraction("invalid interaction")
        return AuthorizedInteraction(interaction_id, InteractionKind.PING)
    if interaction_type != APPLICATION_COMMAND:
        raise MalformedInteraction("unsupported interaction")
    if _snowflake(payload.get("guild_id")) != config.guild_id:
        raise UnauthorizedInteraction("request is not authorized")
    if _snowflake(payload.get("channel_id")) != config.operation_channel_id:
        raise UnauthorizedInteraction("request is not authorized")
    member = payload.get("member")
    if not isinstance(member, dict):
        raise UnauthorizedInteraction("request is not authorized")
    roles = member.get("roles")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise UnauthorizedInteraction("request is not authorized")
    if not ({config.player_role_id, config.admin_role_id} & set(roles)):
        raise UnauthorizedInteraction("request is not authorized")
    return AuthorizedInteraction(
        interaction_id,
        _parse_command(payload.get("data"), expected_guild_id=config.guild_id),
    )


def pong_response() -> dict[str, object]:
    return {"type": PONG}


def phase7b_response() -> dict[str, object]:
    return _ephemeral("Discord ingress verified; no Minecraft operation was submitted.")


def deferred_ephemeral_response() -> dict[str, object]:
    return {
        "type": DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE,
        "data": {"flags": EPHEMERAL},
    }


def status_admission_failure_response() -> dict[str, object]:
    return _ephemeral("Status could not be submitted. Please retry this command.")


def unauthorized_response() -> dict[str, object]:
    return _ephemeral("This command is not available here.")


def _ephemeral(content: str) -> dict[str, object]:
    return {
        "type": CHANNEL_MESSAGE_WITH_SOURCE,
        "data": {
            "content": content,
            "flags": EPHEMERAL,
            "allowed_mentions": {"parse": []},
        },
    }


def _load_unique_json(raw_body: bytes) -> dict[str, object]:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise MalformedInteraction("invalid interaction")
            value[key] = item
        return value

    try:
        decoded = raw_body.decode("utf-8")
        payload = json.loads(decoded, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MalformedInteraction("invalid interaction") from error
    if not isinstance(payload, dict):
        raise MalformedInteraction("invalid interaction")
    return payload


def _parse_command(raw_data: object, *, expected_guild_id: str) -> InteractionKind:
    if not isinstance(raw_data, dict):
        raise MalformedInteraction("invalid command")
    if set(raw_data) - {"id", "name", "type", "options", "guild_id"}:
        raise MalformedInteraction("invalid command")
    _snowflake(raw_data.get("id"))
    if "guild_id" in raw_data and _snowflake(raw_data["guild_id"]) != expected_guild_id:
        raise UnauthorizedInteraction("request is not authorized")
    if raw_data.get("name") != "mc" or raw_data.get("type") != CHAT_INPUT:
        raise MalformedInteraction("invalid command")
    options = raw_data.get("options")
    if not isinstance(options, list) or len(options) != 1:
        raise MalformedInteraction("invalid command")
    option = options[0]
    if not isinstance(option, dict) or set(option) != {"name", "type"}:
        raise MalformedInteraction("invalid command")
    name = option.get("name")
    if option.get("type") != SUB_COMMAND or not isinstance(name, str):
        raise MalformedInteraction("invalid command")
    if name not in MVP_SUBCOMMANDS:
        raise MalformedInteraction("invalid command")
    return InteractionKind(name.upper())


def _snowflake(value: object) -> str:
    if not isinstance(value, str) or SNOWFLAKE.fullmatch(value) is None:
        raise MalformedInteraction("invalid Discord identity")
    return value
