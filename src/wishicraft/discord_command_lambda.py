"""API Gateway v2 adapter for the Phase 7B Discord ingress boundary."""

from __future__ import annotations

import json
import os

from wishicraft.discord_interactions import (
    DiscordIngressConfig,
    MalformedInteraction,
    SignatureRejected,
    UnauthorizedInteraction,
    parse_and_authorize,
    phase7b_response,
    pong_response,
    raw_body_from_event,
    unauthorized_response,
    verify_signature,
)


def handler(event: object, context: object) -> dict[str, object]:
    del context
    try:
        config = _configuration()
        raw_body, headers = raw_body_from_event(event)
        verify_signature(raw_body, headers, public_key=config.public_key)
        interaction = parse_and_authorize(raw_body, config=config)
    except SignatureRejected:
        return _http_response(401, {"error": "invalid request"})
    except UnauthorizedInteraction:
        return _http_response(200, unauthorized_response())
    except MalformedInteraction:
        return _http_response(400, {"error": "invalid interaction"})
    except ValueError:
        return _http_response(500, {"error": "service unavailable"})
    if interaction.kind.value == "PING":
        return _http_response(200, pong_response())
    return _http_response(200, phase7b_response())


def _configuration() -> DiscordIngressConfig:
    return DiscordIngressConfig(
        application_id=_required_environment("DISCORD_APPLICATION_ID"),
        guild_id=_required_environment("DISCORD_GUILD_ID"),
        operation_channel_id=_required_environment("DISCORD_OPERATION_CHANNEL_ID"),
        player_role_id=_required_environment("DISCORD_PLAYER_ROLE_ID"),
        admin_role_id=_required_environment("DISCORD_ADMIN_ROLE_ID"),
        public_key=_required_environment("DISCORD_PUBLIC_KEY"),
    )


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise ValueError("invalid Discord ingress configuration")
    return value


def _http_response(status_code: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(body, separators=(",", ":")),
        "isBase64Encoded": False,
    }
