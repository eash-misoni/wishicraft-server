"""Discord issuer compatibility using offline callback fixtures, never a live OAuth flow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest

from web.local import MemoryStore
from wishicraft.web_app import AuthApp
from wishicraft.web_auth import SESSION_COOKIE, DiscordOAuth, Policy, Sessions

NOW = datetime(2026, 11, 16, tzinfo=UTC)
ISSUER = "https://discord.com"
PRIVATE = "offline-issuer-fixture-private"


def fixture() -> tuple[AuthApp, MemoryStore, str, str, list[str]]:
    store = MemoryStore()
    policy = Policy("1", "2", "3", "4")
    auth = Sessions(store, (PRIVATE * 2).encode(), policy, origin="https://web.example")
    calls: list[str] = []

    class OAuth(DiscordOAuth):
        def exchange(self, code: str) -> dict[str, Any]:
            calls.append(code)
            return {
                "user_id": "9",
                "display_name": "Offline fixture",
                "roles": ["3"],
                "guild_id": "2",
            }

    state, header = auth.begin(int(NOW.timestamp()))
    return (
        AuthApp(
            auth, OAuth(policy, PRIVATE, "https://web.example/auth/callback"), "https://web.example"
        ),
        store,
        state,
        header.split(";")[0],
        calls,
    )


def event(pairs: list[tuple[str, str]], jar: str) -> dict[str, Any]:
    # The integration uses payload 2.0 and the uncombined raw query string.
    return {
        "version": "2.0",
        "rawPath": "/auth/callback",
        "rawQueryString": urlencode(pairs),
        "cookies": [jar],
        "requestContext": {"http": {"method": "GET"}},
    }


def test_documented_issuer_callback_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    app, store, state, jar, calls = fixture()
    result = app.handle(event([("state", state), ("code", PRIVATE), ("iss", ISSUER)], jar), NOW)
    assert result["statusCode"] == 303
    assert result["headers"]["location"] == "/manage/"
    assert calls == [PRIVATE]
    assert state not in store.records
    assert any(c.startswith(SESSION_COOKIE + "=") for c in result["cookies"])
    assert not caplog.records


@pytest.mark.parametrize(
    "case",
    [
        "missing_issuer",
        "empty_issuer",
        "wrong_issuer",
        "trailing_slash",
        "issuer_case",
        "duplicate_issuer",
        "different_issuers",
        "missing_state",
        "missing_code",
        "duplicate_state",
        "duplicate_code",
        "empty_code",
        "long_code",
        "long_issuer",
        "extra_field",
        "field_limit",
        "provider_error",
    ],
)
def test_invalid_shape_rejected_before_state_or_exchange(
    case: str, caplog: pytest.LogCaptureFixture
) -> None:
    app, store, state, jar, calls = fixture()
    pairs = [("state", state), ("code", PRIVATE), ("iss", ISSUER)]
    if case == "missing_issuer":
        pairs.pop()
    elif case in {"empty_issuer", "wrong_issuer", "trailing_slash", "issuer_case", "long_issuer"}:
        value = {
            "empty_issuer": "",
            "wrong_issuer": "https://other.example",
            "trailing_slash": ISSUER + "/",
            "issuer_case": "https://Discord.com",
            "long_issuer": "i" * 2049,
        }[case]
        pairs[-1] = ("iss", value)
    elif case in {"duplicate_issuer", "different_issuers"}:
        pairs.append(("iss", ISSUER if case == "duplicate_issuer" else "https://other.example"))
    elif case in {"missing_state", "missing_code"}:
        pairs = [pair for pair in pairs if pair[0] != case.removeprefix("missing_")]
    elif case in {"duplicate_state", "duplicate_code"}:
        pairs.append(("state", state) if case == "duplicate_state" else ("code", PRIVATE))
    elif case in {"empty_code", "long_code"}:
        pairs[1] = ("code", "" if case == "empty_code" else "c" * 2049)
    elif case == "extra_field":
        pairs.append(("extra", PRIVATE))
    elif case == "field_limit":
        pairs.extend([("extra", PRIVATE), ("other", PRIVATE)])
    elif case == "provider_error":
        pairs[1] = ("error", "access_denied")
    result = app.handle(event(pairs, jar), NOW)
    assert result["statusCode"] == 403
    assert "ログインまたは利用権限を確認できませんでした。" in result["body"]
    assert not calls
    assert set(store.records) == {state}
    assert not any(c.startswith(SESSION_COOKIE + "=") for c in result["cookies"])
    assert [json.loads(r.getMessage()) for r in caplog.records] == [
        {"component": "web-auth", "event": "rejected", "stage": "callback_shape"}
    ]
    for value in [PRIVATE, state, jar, ISSUER, "https://other.example"]:
        assert value not in caplog.text


def test_existing_2048_character_code_bound_is_preserved() -> None:
    app, store, state, jar, calls = fixture()
    code = "c" * 2048
    result = app.handle(event([("state", state), ("code", code), ("iss", ISSUER)], jar), NOW)
    assert result["statusCode"] == 303 and calls == [code]


def test_valid_issuer_does_not_replace_state_cookie_verification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, store, state, jar, calls = fixture()
    result = app.handle(event([("state", state), ("code", PRIVATE), ("iss", ISSUER)], ""), NOW)
    assert result["statusCode"] == 403 and not calls
    assert state in store.records
    assert [json.loads(r.getMessage())["stage"] for r in caplog.records] == ["state_cookie"]
