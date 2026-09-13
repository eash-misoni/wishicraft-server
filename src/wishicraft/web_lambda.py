"""AWS initialization is lazy: public guide requests do not retrieve secrets or state."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from wishicraft.operation import _decode_attribute
from wishicraft.system_state import _to_attribute
from wishicraft.web_app import AuthApp, WebApp, response, utc_now
from wishicraft.web_auth import DiscordOAuth, Policy, Sessions
from wishicraft.web_status import StatusReader


class DynamoSessions:
    def __init__(self, api: Any, table: str) -> None:
        self.api, self.table = api, table

    def _read(self, response: dict[str, Any], field: str) -> dict[str, Any] | None:
        item = response.get(field)
        return {k: _decode_attribute(v) for k, v in item.items()} if item else None

    def get(self, key: str) -> dict[str, Any] | None:
        return self._read(
            self.api.get_item(TableName=self.table, Key={"id": {"S": key}}, ConsistentRead=True),
            "Item",
        )

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.api.put_item(
            TableName=self.table,
            Item={k: _to_attribute(v) for k, v in {"id": key, **value}.items()},
            ConditionExpression="attribute_not_exists(id)",
        )

    def delete(self, key: str) -> dict[str, Any] | None:
        return self._read(
            self.api.delete_item(
                TableName=self.table, Key={"id": {"S": key}}, ReturnValues="ALL_OLD"
            ),
            "Attributes",
        )


@lru_cache
def client(service: str) -> Any:
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    return boto3.client(
        service, config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1})
    )


def secret(parameter: str) -> str:
    result = client("ssm").get_parameter(Name=parameter, WithDecryption=True)
    value = result["Parameter"]["Value"]
    if not isinstance(value, str) or not value:
        raise ValueError("secret unavailable")
    return value


def policy() -> Policy:
    return Policy(
        *(
            os.environ[key]
            for key in (
                "WEB_APPLICATION_ID",
                "WEB_GUILD_ID",
                "WEB_PLAYER_ROLE_ID",
                "WEB_ADMIN_ROLE_ID",
            )
        )
    )


# Secrets deliberately have no warm-container cache: rotation applies to the next request.
def sessions() -> Sessions:
    return Sessions(
        DynamoSessions(client("dynamodb"), os.environ["WEB_SESSIONS_TABLE"]),
        secret(os.environ["WEB_SIGNING_PARAMETER"]).encode(),
        policy(),
    )


def status_reader() -> StatusReader:
    return StatusReader(
        client("dynamodb"),
        {
            name: os.environ["WEB_" + name.upper() + "_TABLE"]
            for name in ("system", "heartbeat", "games", "operation")
        },
        os.environ["WEB_SYSTEM_ID"],
        int(os.environ["WEB_OBSERVATION_SECONDS"]),
    )


@lru_cache
def web_app() -> WebApp:
    return WebApp(
        assets=Path(__file__).resolve().parents[1] / "site",
        sessions=sessions,
        status=lambda now: status_reader().read(now),
    )


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    del context
    try:
        return web_app().handle(event, utc_now())
    except Exception:
        return response(503, "一時的に利用できません。")


def auth_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    del context
    try:
        origin = os.environ["WEB_ORIGIN"]
        app = AuthApp(
            sessions(),
            DiscordOAuth(
                policy(), secret(os.environ["WEB_OAUTH_PARAMETER"]), origin + "/auth/callback"
            ),
            origin,
        )
        return app.handle(event, utc_now())
    except Exception:
        return response(503, "認証サービスを一時的に利用できません。")
