"""API Gateway v2 adapter for the Phase 7B Discord ingress boundary."""

from __future__ import annotations

import importlib
import json
import os
from typing import Protocol, cast

from wishicraft.discord_interactions import (
    DiscordIngressConfig,
    InteractionKind,
    MalformedInteraction,
    SignatureRejected,
    UnauthorizedInteraction,
    deferred_ephemeral_response,
    parse_and_authorize,
    phase7b_response,
    pong_response,
    raw_body_from_event,
    status_admission_failure_response,
    unauthorized_response,
    verify_signature,
)


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class PayloadStream(Protocol):
    def read(self) -> bytes: ...


class StatusAdmission(Protocol):
    def admit(self, *, interaction_id: str) -> str: ...


class LambdaStatusAdmission:
    def __init__(self, api: LambdaApi, *, function_name: str) -> None:
        self._api = api
        self._function_name = function_name

    def admit(self, *, interaction_id: str) -> str:
        response = self._api.invoke(
            FunctionName=self._function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "schema_version": 1,
                    "operation": "admit",
                    "operation_type": "STATUS",
                    "idempotency_key": f"discord:{interaction_id}",
                    "requested_by": "DISCORD",
                },
                separators=(",", ":"),
            ).encode(),
        )
        return _parse_admission_response(response)


_status_admission: StatusAdmission | None = None


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
    if interaction.kind is InteractionKind.PING:
        return _http_response(200, pong_response())
    if interaction.kind is InteractionKind.STATUS:
        try:
            _get_status_admission().admit(interaction_id=interaction.interaction_id)
        except Exception:  # noqa: BLE001 - AWS boundary returns only a fixed safe response.
            return _http_response(200, status_admission_failure_response())
        return _http_response(200, deferred_ephemeral_response())
    return _http_response(200, phase7b_response())


def _get_status_admission() -> StatusAdmission:
    global _status_admission
    if _status_admission is None:
        boto3 = importlib.import_module("boto3")
        _status_admission = LambdaStatusAdmission(
            cast(LambdaApi, boto3.client("lambda")),
            function_name=_required_environment("ADMISSION_FUNCTION_NAME"),
        )
    return _status_admission


def _parse_admission_response(response: object) -> str:
    if not isinstance(response, dict) or response.get("StatusCode") != 200:
        raise RuntimeError("STATUS admission failed")
    if response.get("FunctionError") is not None:
        raise RuntimeError("STATUS admission failed")
    payload = response.get("Payload")
    if not hasattr(payload, "read"):
        raise RuntimeError("STATUS admission failed")
    raw = cast(PayloadStream, payload).read()
    if not isinstance(raw, bytes):
        raise RuntimeError("STATUS admission failed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("STATUS admission failed") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("STATUS admission failed")
    operation_id = value.get("operation_id")
    created = value.get("created")
    if not isinstance(operation_id, str) or not operation_id or not isinstance(created, bool):
        raise RuntimeError("STATUS admission failed")
    if value.get("lease_id") is not None:
        raise RuntimeError("STATUS admission created a lease")
    return operation_id


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
