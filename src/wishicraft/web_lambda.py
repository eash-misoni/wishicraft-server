"""AWS initialization is lazy: public guide requests do not retrieve secrets or state."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from wishicraft.system_state import _to_attribute
from wishicraft.web_app import AuthApp, WebApp, response, utc_now
from wishicraft.web_auth import DiscordOAuth, Policy, Sessions
from wishicraft.web_status import StatusReader, decode


class DynamoSessions:
    def __init__(self, api: Any, table: str) -> None:
        self.api, self.table = api, table

    def _read(self, response: dict[str, Any], field: str) -> dict[str, Any] | None:
        item = response.get(field)
        return {k: decode(v) for k, v in item.items()} if item else None

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
        origin=os.environ.get("WEB_CANONICAL_ORIGIN", ""),
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


def operations() -> Any:
    from wishicraft.reset_policy import policies
    from wishicraft.runtime_catalog import RuntimeCatalog
    from wishicraft.web_operations import Operations

    catalog = RuntimeCatalog.parse(os.environ["WEB_RUNTIME_GAMES"])
    return Operations(
        client("dynamodb"),
        client("lambda"),
        {**status_reader().tables, "idempotency": os.environ["WEB_IDEMPOTENCY_TABLE"]},
        os.environ["WEB_SYSTEM_ID"],
        policy(),
        catalog.game_ids,
        policies(os.environ["WEB_RESET_POLICIES"], catalog),
        os.environ["WEB_ADMISSION_FUNCTION"],
    )


@lru_cache
def web_app() -> WebApp:
    return WebApp(
        assets=Path(__file__).resolve().parents[1] / "site",
        sessions=sessions,
        status=lambda now: status_reader().read(now),
        operations=operations,
        origin=os.environ.get("WEB_CANONICAL_ORIGIN", ""),
    )


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    del context
    try:
        guard = canonical_guard(event)
        if guard is not None:
            return guard
        return web_app().handle(event, utc_now())
    except Exception:
        return response(503, "一時的に利用できません。")


def auth_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    del context
    try:
        guard = canonical_guard(event)
        if guard is not None:
            return guard
        origin = os.environ["WEB_ORIGIN"]
        if os.environ.get("WEB_CANONICAL_ORIGIN", origin) != origin:
            raise ValueError("canonical OAuth origin mismatch")
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


def canonical_guard(event: dict[str, Any]) -> dict[str, Any] | None:
    """Use API Gateway's domain, never a forwarded/Host header or callback query."""
    origin = os.environ.get("WEB_CANONICAL_ORIGIN")
    if not origin:
        return None  # Explicit pre-cutover phase; local harness never uses this handler.
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.netloc != parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid canonical origin")
    context = event.get("requestContext", {})
    if context.get("domainName") == parsed.hostname:
        return None
    path = event.get("rawPath", "")
    method = context.get("http", {}).get("method")
    if (
        method != "GET"
        or path.startswith("/api/")
        or path.startswith("/auth/")
        and path != "/auth/login"
    ):
        return response(
            421, '{"error":"canonical_origin_required"}', content_type="application/json"
        )
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return response(400)
    return response(308, location=origin + quote(path, safe="/-._~"))
