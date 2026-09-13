"""HTTP boundary shared by deployed handlers and the isolated local harness."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from wishicraft.web_auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    AuthRejected,
    DiscordOAuth,
    Sessions,
    cookie,
    cookies,
)

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def response(
    status: int,
    body: str = "",
    *,
    content_type: str = "text/html; charset=utf-8",
    location: str | None = None,
    set_cookies: list[str] | None = None,
) -> dict[str, Any]:
    headers = {
        "content-type": content_type,
        "cache-control": "no-store",
        "content-security-policy": CSP,
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
        "strict-transport-security": "max-age=31536000",
    }
    if location:
        headers["location"] = location
    return {"statusCode": status, "headers": headers, "cookies": set_cookies or [], "body": body}


def login_page(message: str = "Discordでログインしてください。") -> str:
    return (
        '<!doctype html><html lang="ja"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>管理 | Wishicraft</title><link rel="stylesheet" href="/guide.css">'
        '<header><a class="brand" href="/">Wishicraft</a></header><main>'
        "<h1>管理</h1><p>" + message + "</p><p>指定GuildのPlayer / Adminが利用できます。</p>"
        '<a href="/auth/login">Discordでログイン</a>'
        '<p><a href="/">利用ガイドへ</a></p></main></html>'
    )


class WebApp:
    def __init__(
        self,
        *,
        assets: Path,
        sessions: Callable[[], Sessions],
        status: Callable[[datetime], dict[str, Any]],
        operations: Callable[[], Any] | None = None,
        origin: str = "",
    ) -> None:
        self.assets, self.sessions, self.status = assets, sessions, status
        self.operations, self.origin = operations, origin
        self.allowlist = set(json.loads((assets / "routes.json").read_text()))

    def handle(self, event: dict[str, Any], now: datetime) -> dict[str, Any]:
        path = event.get("rawPath", "")
        method = event.get("requestContext", {}).get("http", {}).get("method")
        if path.startswith("/api/operations") or path == "/api/capabilities":
            return self.operation_request(event, now)
        if method != "GET":
            return response(405)
        if path in {"/manage", "/manage/", "/manage/index.html", "/api/status"}:
            try:
                auth = self.sessions()
                record = auth.authenticate(
                    cookies(event).get(SESSION_COOKIE, ""), int(now.timestamp())
                )
                if self.operations is not None and path != "/api/status":
                    from wishicraft.web_operations import principal

                    principal(record, auth.policy)
            except AuthRejected:
                return (
                    response(
                        401, '{"error":"authentication_required"}', content_type="application/json"
                    )
                    if path == "/api/status"
                    else response(200, login_page())
                )
            except Exception:
                return response(
                    503, '{"error":"temporarily_unavailable"}', content_type="application/json"
                )
            if path == "/api/status":
                try:
                    return response(
                        200, json.dumps(self.status(now)), content_type="application/json"
                    )
                except Exception:
                    return response(
                        503, '{"error":"temporarily_unavailable"}', content_type="application/json"
                    )
            path = "/manage/"
        name = path.lstrip("/") + ("index.html" if path.endswith("/") else "")
        if name not in self.allowlist or path.startswith("//"):
            return response(404, "ページが見つかりません。")
        kind = (
            "text/css"
            if name.endswith(".css")
            else "text/javascript"
            if name.endswith(".js")
            else "text/html"
        )
        result = response(
            200, (self.assets / name).read_text(), content_type=kind + "; charset=utf-8"
        )
        if name == "manage/index.html":
            # Chrome form POST must retain a same-origin Origin for logout validation.
            result["headers"]["referrer-policy"] = "same-origin"
        return result

    def operation_request(self, event: dict[str, Any], now: datetime) -> dict[str, Any]:
        from wishicraft.web_operations import WebRejected, principal

        def reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
            return response(
                status, json.dumps({"schema_version": 1, **body}), content_type="application/json"
            )

        path = event.get("rawPath", "")
        method = event.get("requestContext", {}).get("http", {}).get("method")
        if self.operations is None:
            return reply(404, {"error": "not_found"})
        try:
            sessions = self.sessions()
            signed = cookies(event).get(SESSION_COOKIE, "")
            record = sessions.authenticate(signed, int(now.timestamp()))
            actor = principal(record, sessions.policy)
            if method == "POST":
                headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
                token = headers.get("x-csrf-token", "")
                if (
                    headers.get("origin") != self.origin
                    or not isinstance(token, str)
                    or not hmac.compare_digest(token, sessions.csrf(signed))
                ):
                    return reply(403, {"error": "csrf_rejected"})
                if (
                    path != "/api/operations"
                    or headers.get("content-type", "").split(";")[0] != "application/json"
                    or event.get("isBase64Encoded")
                ):
                    return reply(400, {"error": "invalid_input"})
                body = event.get("body", "")
                if not isinstance(body, str) or len(body) > 2048:
                    return reply(400, {"error": "invalid_input"})
                try:
                    value = json.loads(body)
                except ValueError:
                    return reply(400, {"error": "invalid_input"})
                status, result = self.operations().submit(
                    actor, value, sessions.verify(signed, "session-"), now
                )
                return reply(status, result)
            if method != "GET":
                return reply(405, {"error": "method_not_allowed"})
            if path == "/api/capabilities":
                return reply(
                    200,
                    {**self.operations().capabilities(actor), "csrf_token": sessions.csrf(signed)},
                )
            if path == "/api/operations/current":
                return reply(200, self.operations().read(actor, None))
            prefix = "/api/operations/request/"
            if path.startswith(prefix):
                return reply(200, self.operations().read(actor, path[len(prefix) :]))
            return reply(404, {"error": "not_found"})
        except AuthRejected:
            return reply(401, {"error": "authentication_required"})
        except WebRejected as error:
            return reply(error.status, {"error": error.code, "outcome": "rejected"})
        except Exception:
            return reply(
                503, {"error": "result_unknown" if method == "POST" else "temporarily_unavailable"}
            )


class AuthApp:
    def __init__(self, sessions: Sessions, oauth: DiscordOAuth, origin: str) -> None:
        self.sessions, self.oauth, self.origin = sessions, oauth, origin

    def handle(self, event: dict[str, Any], now: datetime) -> dict[str, Any]:
        path = event.get("rawPath")
        method = event.get("requestContext", {}).get("http", {}).get("method")
        jar, timestamp = cookies(event), int(now.timestamp())
        try:
            if path == "/auth/login" and method == "GET":
                state, state_cookie = self.sessions.begin(timestamp)
                return response(
                    302, location=self.oauth.authorization_url(state), set_cookies=[state_cookie]
                )
            if path == "/auth/callback" and method == "GET":
                query = parse_qs(
                    event.get("rawQueryString", ""), keep_blank_values=True, max_num_fields=4
                )
                if set(query) != {"state", "code"} or any(
                    len(v) != 1 or not v[0] or len(v[0]) > 2048 for v in query.values()
                ):
                    raise AuthRejected("invalid callback")
                self.sessions.consume(query["state"][0], jar.get(STATE_COOKIE, ""), timestamp)
                principal = self.oauth.exchange(query["code"][0])
                self.sessions.logout(jar.get(SESSION_COOKIE, ""))
                session_cookie = self.sessions.create(timestamp, principal)
                return response(
                    303,
                    location="/manage/",
                    set_cookies=[session_cookie, cookie(STATE_COOKIE, "", 0)],
                )
            if path == "/auth/logout" and method == "POST":
                headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
                if headers.get("origin") != self.origin:
                    raise AuthRejected("invalid origin")
                self.sessions.logout(jar.get(SESSION_COOKIE, ""))
                return response(303, location="/", set_cookies=[cookie(SESSION_COOKIE, "", 0)])
            return response(405)
        except (AuthRejected, ValueError):
            return response(
                403,
                login_page("ログインまたは利用権限を確認できませんでした。"),
                set_cookies=[cookie(STATE_COOKIE, "", 0)],
            )
        except Exception:
            return response(
                503, login_page("認証サービスを利用できません。時間をおいて再度お試しください。")
            )


def utc_now() -> datetime:
    return datetime.now(UTC)
