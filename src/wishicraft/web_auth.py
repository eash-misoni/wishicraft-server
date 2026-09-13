"""Short lived, revocable Web sessions; Discord credentials remain in process memory."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from wishicraft.authorization import role_authorized

SCOPES = "identify guilds.members.read"
SESSION_SECONDS = 900
STATE_SECONDS = 300
SESSION_COOKIE = "__Host-wishicraft"
STATE_COOKIE = "__Host-wishicraft-state"


class AuthRejected(ValueError):
    """Generic authentication/authorization failure; never carries upstream details."""


class Store(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put(self, key: str, value: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class Policy:
    application_id: str
    guild_id: str
    player_role_id: str
    admin_role_id: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            "|".join(
                (self.application_id, self.guild_id, self.player_role_id, self.admin_role_id)
            ).encode()
        ).hexdigest()

    def authorize(self, identity: dict[str, Any], member: dict[str, Any]) -> None:
        user_id = identity.get("id")
        if (
            not isinstance(user_id, str)
            or not re.fullmatch(r"[0-9]{1,20}", user_id)
            or not isinstance(member.get("user"), dict)
            or member["user"].get("id") != user_id
            or member.get("pending", False) is not False
            or not role_authorized(
                member.get("roles"),
                player_role_id=self.player_role_id,
                admin_role_id=self.admin_role_id,
            )
        ):
            raise AuthRejected("access denied")


def cookie(name: str, value: str, seconds: int) -> str:
    return f"{name}={value}; Path=/; Max-Age={seconds}; Secure; HttpOnly; SameSite=Lax"


def cookies(event: dict[str, Any]) -> dict[str, str]:
    raw = event.get("cookies", [])
    parsed: SimpleCookie = SimpleCookie()
    try:
        parsed.load("; ".join(raw))
    except Exception:
        return {}
    return {key: value.value for key, value in parsed.items()}


class Sessions:
    def __init__(self, store: Store, key: bytes, policy: Policy, *, origin: str = "") -> None:
        if len(key) < 32:
            raise ValueError("session key must contain at least 32 bytes")
        self.store, self.key, self.policy = store, key, policy
        self.fingerprint = (
            hashlib.sha256((policy.fingerprint + "|" + origin).encode()).hexdigest()
            if origin
            else policy.fingerprint
        )

    def sign(self, value: str) -> str:
        return value + "." + hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def verify(self, signed: str, prefix: str) -> str:
        if not re.fullmatch(prefix + r"[A-Za-z0-9_-]{43}\.[0-9a-f]{64}", signed):
            raise AuthRejected("invalid session")
        value = signed.rsplit(".", 1)[0]
        if not hmac.compare_digest(self.sign(value), signed):
            raise AuthRejected("invalid session")
        return value

    def begin(self, now: int) -> tuple[str, str]:
        state = "state-" + secrets.token_urlsafe(32)
        self.store.put(state, {"expires_at": now + STATE_SECONDS, "policy": self.fingerprint})
        return state, cookie(STATE_COOKIE, self.sign(state), STATE_SECONDS)

    def consume(self, state: str, signed: str, now: int) -> None:
        value = self.verify(signed, "state-")
        if not hmac.compare_digest(value, state):
            raise AuthRejected("invalid state")
        # Atomic DeleteItem ReturnValues=ALL_OLD: only one callback can exchange the code.
        record = self.store.delete(value)
        self._valid(record, now)

    def _valid(self, record: dict[str, Any] | None, now: int) -> None:
        if (
            record is None
            or type(record.get("expires_at")) is not int
            or record["expires_at"] <= now
            or record.get("policy") != self.fingerprint
        ):
            raise AuthRejected("expired or invalid session")

    def create(self, now: int) -> str:
        value = "session-" + secrets.token_urlsafe(32)
        self.store.put(value, {"expires_at": now + SESSION_SECONDS, "policy": self.fingerprint})
        return cookie(SESSION_COOKIE, self.sign(value), SESSION_SECONDS)

    def authenticate(self, signed: str, now: int) -> None:
        value = self.verify(signed, "session-")
        self._valid(self.store.get(value), now)

    def logout(self, signed: str) -> None:
        try:
            value = self.verify(signed, "session-")
        except AuthRejected:
            return
        self.store.delete(value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class DiscordOAuth:
    def __init__(self, policy: Policy, secret: str, redirect_uri: str) -> None:
        self.policy, self.secret, self.redirect_uri = policy, secret, redirect_uri

    def authorization_url(self, state: str) -> str:
        return "https://discord.com/oauth2/authorize?" + urlencode(
            {
                "client_id": self.policy.application_id,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
                "redirect_uri": self.redirect_uri,
            }
        )

    def request(
        self, path: str, *, form: dict[str, str] | None = None, token: str | None = None
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "DiscordBot (https://github.com/eash-misoni/wishicraft-server, 0.1.0)",
        }
        data = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(form).encode()
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with build_opener(NoRedirect()).open(
                Request("https://discord.com/api/v10" + path, data=data, headers=headers), timeout=5
            ) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError
                if path == "/oauth2/token/revoke":
                    return {}  # Successful revocation does not require a JSON response body.
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except Exception:
            raise AuthRejected("Discord authentication unavailable") from None

    def exchange(self, code: str) -> None:
        token_response = self.request(
            "/oauth2/token",
            form={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.policy.application_id,
                "client_secret": self.secret,
            },
        )
        token = token_response.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthRejected("invalid OAuth grant")
        try:
            token_type, scope = token_response.get("token_type"), token_response.get("scope")
            if (
                not isinstance(token_type, str)
                or token_type.lower() != "bearer"
                or not isinstance(scope, str)
                or set(scope.split()) != set(SCOPES.split())
            ):
                raise AuthRejected("invalid OAuth grant")
            identity = self.request("/users/@me", token=token)
            member = self.request(f"/users/@me/guilds/{self.policy.guild_id}/member", token=token)
            self.policy.authorize(identity, member)
        finally:
            # Revocation invalidates the associated refresh token as well. Fail closed on failure.
            self.request(
                "/oauth2/token/revoke",
                form={
                    "token": token,
                    "token_type_hint": "access_token",
                    "client_id": self.policy.application_id,
                    "client_secret": self.secret,
                },
            )
