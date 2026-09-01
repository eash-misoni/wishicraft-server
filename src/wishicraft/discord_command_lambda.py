"""API Gateway v2 adapter for the Phase 7B Discord ingress boundary."""

from __future__ import annotations

import importlib
import json
import os
from typing import Protocol, cast

from wishicraft.discord_interaction_callback import DiscordInteractionCallbackClient
from wishicraft.discord_interactions import (
    DiscordIngressConfig,
    InteractionKind,
    MalformedInteraction,
    SignatureRejected,
    UnauthorizedInteraction,
    admission_result_content,
    parse_and_authorize,
    pong_response,
    raw_body_from_event,
    unauthorized_response,
    verify_signature,
)


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class PayloadStream(Protocol):
    def read(self) -> bytes: ...


class OperationAdmission(Protocol):
    def admit(
        self, *, operation_type: str, interaction_id: str, guild_id: str, channel_id: str
    ) -> str: ...


class InteractionCallback(Protocol):
    def defer(self, *, interaction_id: str, interaction_token: str) -> None: ...
    def edit_original(
        self, *, application_id: str, interaction_token: str, content: str
    ) -> None: ...


class LambdaOperationAdmission:
    def __init__(self, api: LambdaApi, *, function_name: str) -> None:
        self._api = api
        self._function_name = function_name

    def admit(
        self, *, operation_type: str, interaction_id: str, guild_id: str, channel_id: str
    ) -> str:
        if operation_type not in {"STATUS", "START", "STOP"}:
            raise ValueError("unsupported Discord admission type")
        response = self._api.invoke(
            FunctionName=self._function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "schema_version": 1,
                    "operation": "admit",
                    "operation_type": operation_type,
                    "idempotency_key": f"discord:{interaction_id}",
                    "requested_by": "DISCORD",
                    "discord": {
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "interaction_id": interaction_id,
                    },
                },
                separators=(",", ":"),
            ).encode(),
        )
        return _parse_admission_response(response, operation_type=operation_type)


_operation_admission: OperationAdmission | None = None
_interaction_callback: InteractionCallback | None = None


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
    callback = _get_interaction_callback()
    try:
        callback.defer(
            interaction_id=interaction.interaction_id,
            interaction_token=interaction.interaction_token,
        )
    except Exception:  # noqa: BLE001 - fail closed before Admission, with no credential detail.
        return _http_response(502, {"error": "interaction acknowledgement failed"})
    try:
        _get_operation_admission().admit(
            operation_type=interaction.kind.value,
            interaction_id=interaction.interaction_id,
            guild_id=config.guild_id,
            channel_id=config.operation_channel_id,
        )
        accepted = True
    except Exception:  # noqa: BLE001 - AWS boundary is projected without internal detail.
        accepted = False
    try:
        callback.edit_original(
            application_id=config.application_id,
            interaction_token=interaction.interaction_token,
            content=admission_result_content(interaction.kind, accepted=accepted),
        )
    except Exception:  # noqa: BLE001 - acknowledgement delivery does not rewrite Control Plane truth.
        pass
    return _empty_http_response(202)


def _get_operation_admission() -> OperationAdmission:
    global _operation_admission
    if _operation_admission is None:
        boto3 = importlib.import_module("boto3")
        _operation_admission = LambdaOperationAdmission(
            cast(LambdaApi, boto3.client("lambda")),
            function_name=_required_environment("ADMISSION_FUNCTION_NAME"),
        )
    return _operation_admission


def _get_interaction_callback() -> InteractionCallback:
    global _interaction_callback
    if _interaction_callback is None:
        _interaction_callback = DiscordInteractionCallbackClient()
    return _interaction_callback


def _parse_admission_response(response: object, *, operation_type: str) -> str:
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
    lease_id = value.get("lease_id")
    if operation_type == "STATUS" and lease_id is not None:
        raise RuntimeError("STATUS admission created a lease")
    if operation_type in {"START", "STOP"} and (not isinstance(lease_id, str) or not lease_id):
        raise RuntimeError(f"{operation_type} admission did not return a lease")
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


def _empty_http_response(status_code: int) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {"cache-control": "no-store"},
        "body": "",
        "isBase64Encoded": False,
    }
