"""Short-lived Discord Interaction acknowledgement transport."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from wishicraft.discord_interactions import deferred_ephemeral_response

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class InteractionCallbackFailure(Exception):
    """Credential-safe callback failure classification."""

    code: str


class DiscordInteractionCallbackClient:
    """Acknowledge and edit one Interaction without a Bot Token."""

    def __init__(self, *, timeout_seconds: float = 2.0) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 2.0:
            raise ValueError("invalid Discord callback timeout")
        self._timeout = timeout_seconds

    def defer(self, *, interaction_id: str, interaction_token: str) -> None:
        request = self._request(
            "POST",
            f"/interactions/{interaction_id}/{interaction_token}/callback",
            deferred_ephemeral_response(),
        )
        status, raw = self._open(request)
        if status != 204 or raw:
            raise InteractionCallbackFailure("DISCORD_CALLBACK_MALFORMED_RESPONSE")

    def edit_original(self, *, application_id: str, interaction_token: str, content: str) -> None:
        request = self._request(
            "PATCH",
            f"/webhooks/{application_id}/{interaction_token}/messages/@original",
            {"content": content, "allowed_mentions": {"parse": []}},
        )
        status, raw = self._open(request)
        if status != 200:
            raise InteractionCallbackFailure("DISCORD_CALLBACK_MALFORMED_RESPONSE")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InteractionCallbackFailure("DISCORD_CALLBACK_MALFORMED_RESPONSE") from None
        message_id = value.get("id") if isinstance(value, dict) else None
        if not isinstance(message_id, str) or not message_id.isdecimal():
            raise InteractionCallbackFailure("DISCORD_CALLBACK_MALFORMED_RESPONSE")

    @staticmethod
    def _request(method: str, path: str, payload: dict[str, object]) -> urllib.request.Request:
        return urllib.request.Request(
            DISCORD_API_BASE + path,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            method=method,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Wishicraft (https://github.com/eash-misoni/wishicraft-server, 1)",
            },
        )

    def _open(self, request: urllib.request.Request) -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = response.status
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            if status in {401, 403, 404}:
                code = "DISCORD_CALLBACK_REJECTED"
            elif status == 429:
                code = "DISCORD_CALLBACK_RATE_LIMITED"
            elif 500 <= status <= 599:
                code = "DISCORD_CALLBACK_SERVER_FAILURE"
            else:
                code = "DISCORD_CALLBACK_REQUEST_FAILED"
            raise InteractionCallbackFailure(code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise InteractionCallbackFailure("DISCORD_CALLBACK_NETWORK_FAILURE") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise InteractionCallbackFailure("DISCORD_CALLBACK_MALFORMED_RESPONSE")
        return status, raw
