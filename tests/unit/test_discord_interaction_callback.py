from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import cast

import pytest

from wishicraft.discord_interaction_callback import (
    DiscordInteractionCallbackClient,
    InteractionCallbackFailure,
)

INTERACTION_ID = "1532000000000000001"
APPLICATION_ID = "1531887197433757768"
SYNTHETIC_TOKEN = "non-production-test-token"


class Response:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


def test_initial_deferred_ack_uses_callback_without_bot_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[urllib.request.Request, float]] = []

    def open_request(request: urllib.request.Request, *, timeout: float) -> Response:
        calls.append((request, timeout))
        return Response(204)

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    DiscordInteractionCallbackClient().defer(
        interaction_id=INTERACTION_ID, interaction_token=SYNTHETIC_TOKEN
    )

    request, timeout = calls[0]
    assert request.method == "POST"
    assert request.full_url.endswith(f"/{INTERACTION_ID}/{SYNTHETIC_TOKEN}/callback")
    assert request.get_header("Authorization") is None
    assert json.loads(cast(bytes, request.data)) == {"type": 5, "data": {"flags": 64}}
    assert timeout == 2.0


def test_original_ephemeral_response_is_edited_with_safe_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[urllib.request.Request] = []

    def open_request(request: urllib.request.Request, *, timeout: float) -> Response:
        assert timeout == 2.0
        calls.append(request)
        return Response(200, b'{"id":"1532000000000000099"}')

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    DiscordInteractionCallbackClient().edit_original(
        application_id=APPLICATION_ID,
        interaction_token=SYNTHETIC_TOKEN,
        content="Status accepted. Progress will be posted in this channel.",
    )

    request = calls[0]
    assert request.method == "PATCH"
    assert request.full_url.endswith(
        f"/webhooks/{APPLICATION_ID}/{SYNTHETIC_TOKEN}/messages/@original"
    )
    assert request.get_header("Authorization") is None
    assert json.loads(cast(bytes, request.data)) == {
        "content": "Status accepted. Progress will be posted in this channel.",
        "allowed_mentions": {"parse": []},
    }


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "DISCORD_CALLBACK_REQUEST_FAILED"),
        (401, "DISCORD_CALLBACK_REJECTED"),
        (403, "DISCORD_CALLBACK_REJECTED"),
        (404, "DISCORD_CALLBACK_REJECTED"),
        (429, "DISCORD_CALLBACK_RATE_LIMITED"),
        (500, "DISCORD_CALLBACK_SERVER_FAILURE"),
    ],
)
def test_http_failure_is_classified_without_credential_url(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    def fail(request: urllib.request.Request, *, timeout: float) -> Response:
        raise urllib.error.HTTPError(
            request.full_url, status, "detail", Message(), io.BytesIO(b"{}")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(InteractionCallbackFailure) as raised:
        DiscordInteractionCallbackClient().defer(
            interaction_id=INTERACTION_ID, interaction_token=SYNTHETIC_TOKEN
        )
    assert raised.value.code == code
    assert SYNTHETIC_TOKEN not in str(raised.value)
    assert "discord.com" not in str(raised.value)


@pytest.mark.parametrize("failure", [TimeoutError(), urllib.error.URLError("offline")])
def test_network_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    def fail(request: urllib.request.Request, *, timeout: float) -> Response:
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(
        InteractionCallbackFailure, match="DISCORD_CALLBACK_NETWORK_FAILURE"
    ) as raised:
        DiscordInteractionCallbackClient().defer(
            interaction_id=INTERACTION_ID, interaction_token=SYNTHETIC_TOKEN
        )
    assert SYNTHETIC_TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        Response(200),
        Response(204, b"unexpected"),
        Response(204, b"x" * (64 * 1024 + 1)),
    ],
)
def test_malformed_initial_callback_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch, response: Response
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: response)
    with pytest.raises(InteractionCallbackFailure, match="DISCORD_CALLBACK_MALFORMED_RESPONSE"):
        DiscordInteractionCallbackClient().defer(
            interaction_id=INTERACTION_ID, interaction_token=SYNTHETIC_TOKEN
        )


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"id":1}'])
def test_malformed_edit_response_is_rejected(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response(200, body))
    with pytest.raises(InteractionCallbackFailure, match="DISCORD_CALLBACK_MALFORMED_RESPONSE"):
        DiscordInteractionCallbackClient().edit_original(
            application_id=APPLICATION_ID,
            interaction_token=SYNTHETIC_TOKEN,
            content="safe content",
        )
