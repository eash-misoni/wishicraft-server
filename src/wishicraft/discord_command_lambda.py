"""API Gateway v2 adapter for the Phase 7B Discord ingress boundary."""

from __future__ import annotations

import importlib
import json
import os
import time
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

if TYPE_CHECKING:
    from wishicraft.game_discovery import Discovery

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
        self,
        *,
        operation_type: str,
        interaction_id: str,
        guild_id: str,
        channel_id: str,
        target_game_id: str | None = None,
        confirmed: bool = False,
        seed_mode: str | None = None,
        user_id: str | None = None,
        display_name: str | None = None,
    ) -> str: ...


class GameSelection(TypedDict, total=False):
    target_game_id: str
    confirmed: bool
    seed_mode: str
    user_id: str
    display_name: str


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
        self,
        *,
        operation_type: str,
        interaction_id: str,
        guild_id: str,
        channel_id: str,
        target_game_id: str | None = None,
        confirmed: bool = False,
        seed_mode: str | None = None,
        user_id: str | None = None,
        display_name: str | None = None,
    ) -> str:
        if operation_type not in {"STATUS", "START", "STOP", "BACKUP", "SWITCH", "RESET"}:
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
                    **({"target_game_id": target_game_id} if target_game_id is not None else {}),
                    **({"confirmed": True} if confirmed else {}),
                    **({"seed_mode": seed_mode} if seed_mode is not None else {}),
                    "discord": {
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "interaction_id": interaction_id,
                        **({"user_id": user_id} if user_id is not None else {}),
                        **({"display_name": display_name} if display_name is not None else {}),
                    },
                },
                separators=(",", ":"),
            ).encode(),
        )
        return _parse_admission_response(response, operation_type=operation_type)


_operation_admission: OperationAdmission | None = None
_interaction_callback: InteractionCallback | None = None
_autocomplete_reader: Discovery | None = None


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
        if json.loads(raw_body).get("type") == 4:
            return _http_response(200, {"type": 8, "data": {"choices": []}})
        return _http_response(200, unauthorized_response())
    except MalformedInteraction:
        return _http_response(400, {"error": "invalid interaction"})
    except ValueError:
        return _http_response(500, {"error": "service unavailable"})
    if interaction.kind is InteractionKind.PING:
        return _http_response(200, pong_response())
    if interaction.autocomplete_query is not None:
        return _autocomplete_response(interaction.kind, interaction.autocomplete_query)
    callback = _get_interaction_callback()
    try:
        callback.defer(
            interaction_id=interaction.interaction_id,
            interaction_token=interaction.interaction_token,
        )
    except Exception:  # noqa: BLE001 - fail closed before Admission, with no credential detail.
        return _http_response(502, {"error": "interaction acknowledgement failed"})
    try:
        selection: GameSelection = {}
        if interaction.target_game_id is not None:
            selection = {
                "target_game_id": interaction.target_game_id,
                "confirmed": interaction.confirmed,
            }
        if interaction.seed_mode is not None:
            selection["seed_mode"] = interaction.seed_mode
        if interaction.user_id is not None:
            selection["user_id"] = interaction.user_id
        if interaction.display_name is not None:
            selection["display_name"] = interaction.display_name
        _get_operation_admission().admit(
            operation_type=interaction.kind.value,
            interaction_id=interaction.interaction_id,
            guild_id=config.guild_id,
            channel_id=config.operation_channel_id,
            **selection,
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
    if operation_type in {"START", "STOP", "BACKUP", "SWITCH", "RESET"} and (
        not isinstance(lease_id, str) or not lease_id
    ):
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


def _autocomplete_response(kind: InteractionKind, query: str) -> dict[str, object]:
    from wishicraft.game_discovery import choices

    started = time.monotonic()
    try:
        reader = _get_autocomplete_reader()
        result = choices(reader.read(deadline=started + 1.8), kind.value.lower(), query)
    except Exception as error:
        # Do not defer, call Admission or expose AWS/registry error details.
        _autocomplete_log("unavailable", started, error=error)
        result = []
    else:
        _autocomplete_log("ok", started, command=kind.value, count=len(result))
    return _http_response(200, {"type": 8, "data": {"choices": result}})


def _get_autocomplete_reader() -> Discovery:
    global _autocomplete_reader
    if _autocomplete_reader is None:
        from botocore.config import Config  # type: ignore[import-untyped]

        from wishicraft.game_discovery import Discovery
        from wishicraft.reset_policy import policies
        from wishicraft.runtime_catalog import RuntimeCatalog

        catalog = RuntimeCatalog.parse(_required_environment("RUNTIME_GAMES"))
        api = importlib.import_module("boto3").client(
            "dynamodb",
            config=Config(connect_timeout=0.3, read_timeout=0.3, retries={"max_attempts": 0}),
        )
        _autocomplete_reader = Discovery(
            api,
            _required_environment("GAMES_TABLE"),
            catalog.game_ids,
            policies(os.environ.get("RESET_POLICIES", "{}"), catalog),
        )
    return _autocomplete_reader


def _autocomplete_log(
    result: str,
    started: float,
    *,
    command: str | None = None,
    count: int | None = None,
    error: Exception | None = None,
) -> None:
    print(
        json.dumps(
            {
                "component": "discord-autocomplete",
                "result": result,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **({"command": command, "count": count} if command is not None else {}),
                **(
                    {"reason": "deadline" if isinstance(error, TimeoutError) else "read_failure"}
                    if error is not None
                    else {}
                ),
            }
        )
    )


# SDK/service-model initialization belongs in Lambda INIT, not Discord's response budget.
# Only the connection/configuration is reused: no registry read occurs before authorization.
if os.environ.get("GAMES_TABLE"):
    _init_started = time.monotonic()
    try:
        _get_autocomplete_reader()
    except Exception as _init_error:
        # Leave other commands available; a later autocomplete request can retry initialization.
        _autocomplete_log("initialization_failed", _init_started, error=_init_error)
