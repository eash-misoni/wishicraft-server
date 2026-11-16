"""Fixed diagnostic labels, with the real callback/adapter and no network or credentials."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest

from web.local import MemoryStore
from wishicraft.web_app import AuthApp
from wishicraft.web_auth import (
    DISCORD_ISSUER,
    SESSION_COOKIE,
    AuthRejected,
    AuthRejectionStage,
    DiscordOAuth,
    Policy,
    Sessions,
    log_auth_rejection,
)

NOW = datetime(2026, 11, 16, tzinfo=UTC)
POLICY = Policy("111111111111", "222222222222", "333333333333", "444444444444")
USER = "555555555555"
CANARY = "private-fixture-value-not-for-logs"
TOKEN = CANARY + "-access-token"
CLIENT_SECRET = CANARY + "-client-secret"
ORIGIN = "https://fixture-private.example"


def callback(query: dict[str, str], jar: str) -> dict[str, Any]:
    return {
        "rawPath": "/auth/callback",
        "rawQueryString": urlencode({"iss": DISCORD_ISSUER, **query}),
        "cookies": [jar],
        "headers": {"x-private-fixture": CANARY},
        "requestContext": {"http": {"method": "GET"}},
    }


def assert_labels(
    caplog: pytest.LogCaptureFixture, expected: list[str], private: list[str]
) -> None:
    records = caplog.records
    assert [json.loads(r.getMessage()) for r in records] == [
        {"component": "web-auth", "event": "rejected", "stage": stage} for stage in expected
    ]
    allowed = {stage.value for stage in AuthRejectionStage}
    for record in records:
        assert record.name == "wishicraft.web_auth"
        assert record.levelno == logging.WARNING
        assert record.exc_info is None and record.stack_info is None
        assert json.loads(record.getMessage())["stage"] in allowed
        assert len(record.getMessage()) < 110
    for value in [CANARY, TOKEN, CLIENT_SECRET, ORIGIN, USER, *vars(POLICY).values(), *private]:
        assert value not in caplog.text


@pytest.mark.parametrize(
    "case,expected",
    [
        ("shape", "callback_shape"),
        ("missing_cookie", "state_cookie"),
        ("signature", "state_cookie"),
        ("mismatch", "state_cookie"),
        ("expired", "state_cookie"),
        ("consumed", "state_cookie"),
    ],
)
def test_callback_shape_and_state_labels(
    case: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    auth = Sessions(MemoryStore(), (CANARY * 2).encode(), POLICY)
    state, header = auth.begin(int(NOW.timestamp()))
    jar = header.split(";")[0]
    query = {"state": state, "code": CANARY}
    when = NOW
    oauth = DiscordOAuth(POLICY, CLIENT_SECRET, ORIGIN + "/auth/callback")

    def never_exchange(code: str) -> dict[str, Any]:
        pytest.fail("state rejection must not attempt OAuth exchange")

    monkeypatch.setattr(oauth, "exchange", never_exchange)
    if case == "shape":
        query["unexpected"] = CANARY
    elif case == "missing_cookie":
        jar = ""
    elif case == "signature":
        jar = jar[:-1] + ("1" if jar[-1] != "1" else "2")
    elif case == "mismatch":
        query["state"] = CANARY
    elif case == "expired":
        when += timedelta(seconds=300)
    elif case == "consumed":
        auth.consume(state, jar.split("=", 1)[1], int(NOW.timestamp()))
    result = AuthApp(auth, oauth, ORIGIN).handle(callback(query, jar), when)
    assert result["statusCode"] == 403
    assert "ログインまたは利用権限を確認できませんでした。" in result["body"]
    assert result["headers"]["cache-control"] == "no-store"
    assert all(not c.startswith(SESSION_COOKIE + "=") for c in result["cookies"])
    assert_labels(caplog, [expected], [state, header, jar] if jar else [state, header])
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    "case,expected,steps",
    [
        ("token", ["token_exchange"], ["token"]),
        ("no_token", ["token_response"], ["token"]),
        ("scope", ["grant_validation"], ["token", "revoke"]),
        ("type", ["grant_validation"], ["token", "revoke"]),
        ("identity", ["identity_lookup"], ["token", "identity", "revoke"]),
        ("member", ["member_lookup"], ["token", "identity", "member", "revoke"]),
        ("role", ["member_policy"], ["token", "identity", "member", "revoke"]),
        ("pending", ["member_policy"], ["token", "identity", "member", "revoke"]),
        ("member_identity", ["member_policy"], ["token", "identity", "member", "revoke"]),
        ("revoke", ["revoke"], ["token", "identity", "member", "revoke"]),
        ("role_revoke", ["member_policy", "revoke"], ["token", "identity", "member", "revoke"]),
        ("scope_revoke", ["grant_validation", "revoke"], ["token", "revoke"]),
        ("player", [], ["token", "identity", "member", "revoke", "session"]),
        ("admin", [], ["token", "identity", "member", "revoke", "session"]),
    ],
)
def test_real_adapter_labels_and_unchanged_revocation_order(
    case: str,
    expected: list[str],
    steps: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    class Store(MemoryStore):
        def put(self, key: str, value: dict[str, Any]) -> None:
            if key.startswith("session-"):
                calls.append("session")
            super().put(key, value)

    class Reply:
        def __init__(self, value: dict[str, Any]) -> None:
            self.value = value

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, maximum: int) -> bytes:
            return json.dumps(self.value).encode()

    class Opener:
        def open(self, request: Any, **kwargs: Any) -> Reply:
            assert kwargs == {"timeout": 5}
            step = (
                "revoke"
                if request.full_url.endswith("/revoke")
                else "token"
                if request.full_url.endswith("/token")
                else "member"
                if request.full_url.endswith("/member")
                else "identity"
            )
            calls.append(step)
            if case == step or step == "revoke" and case.endswith("_revoke"):
                raise OSError(CANARY + TOKEN + CLIENT_SECRET + ORIGIN + USER)
            if step == "token":
                return Reply(
                    {
                        "access_token": None if case == "no_token" else TOKEN,
                        "token_type": "Basic" if case == "type" else "Bearer",
                        "scope": "identify"
                        if case.startswith("scope")
                        else "identify guilds.members.read",
                    }
                )
            if step == "identity":
                return Reply({"id": USER, "username": CANARY})
            if step == "member":
                return Reply(
                    {
                        "user": {"id": "666666666666" if case == "member_identity" else USER},
                        "roles": []
                        if case.startswith("role")
                        else ["444444444444" if case == "admin" else "333333333333"],
                        "pending": case == "pending",
                        "nick": CANARY,
                    }
                )
            return Reply({})

    monkeypatch.setattr("wishicraft.web_auth.build_opener", lambda *args: Opener())
    auth = Sessions(Store(), (CANARY * 2).encode(), POLICY)
    state, header = auth.begin(int(NOW.timestamp()))
    oauth = DiscordOAuth(POLICY, CLIENT_SECRET, ORIGIN + "/auth/callback")
    result = AuthApp(auth, oauth, ORIGIN).handle(
        callback({"state": state, "code": CANARY}, header.split(";")[0]), NOW
    )
    assert calls == steps
    assert result["statusCode"] == (303 if case in {"player", "admin"} else 403)
    if expected:
        assert "ログインまたは利用権限を確認できませんでした。" in result["body"]
        assert not any(c.startswith(SESSION_COOKIE + "=") for c in result["cookies"])
        assert not auth.store.records  # type: ignore[attr-defined]
    else:
        assert result["headers"]["location"] == "/manage/"
    assert_labels(caplog, expected, [state, header, "666666666666"])
    assert not capsys.readouterr().out


def test_policy_outside_callback_is_not_a_diagnostic(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(AuthRejected):
        POLICY.authorize({"id": USER}, {"user": {"id": USER}, "roles": []})
    assert not caplog.records


def test_diagnostic_sink_cannot_change_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OSError(CANARY)

    monkeypatch.setattr(logging.getLogger("wishicraft.web_auth"), "warning", broken)
    log_auth_rejection(AuthRejectionStage.REVOKE)
    auth = Sessions(MemoryStore(), (CANARY * 2).encode(), POLICY)
    app = AuthApp(auth, DiscordOAuth(POLICY, CLIENT_SECRET, ORIGIN), ORIGIN)
    result = app.handle(callback({}, CANARY), NOW)
    assert result["statusCode"] == 403
    assert "ログインまたは利用権限を確認できませんでした。" in result["body"]
