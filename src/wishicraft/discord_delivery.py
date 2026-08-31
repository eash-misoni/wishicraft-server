"""Retry-safe Discord delivery of an already-safe Operation projection."""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_DELIVERY_ATTEMPTS = 3
AMBIGUOUS_CREATE_WINDOW_SECONDS = 30
DEFAULT_RETRY_SECONDS = 5
MAX_RETRY_SECONDS = 900


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class DeliveryRecord:
    operation_id: str
    operation_status: str
    channel_id: str
    projection: dict[str, object]
    operation_type: str = "STATUS"
    current_step: str = "ADMITTED"
    source_revision: int = 0
    error_code: str | None = None
    delivery_status: DeliveryStatus | None = None
    attempt_id: str | None = None
    attempt_count: int = 0
    first_attempt_epoch: int | None = None
    next_attempt_epoch: int | None = None
    outcome_unknown: bool = False
    message_id: str | None = None
    delivery_source_revision: int | None = None
    delivered_revision: int | None = None
    resumed_pending: bool = False


@dataclass(frozen=True)
class DiscordFailure(Exception):
    code: str
    retryable: bool
    retry_after_seconds: int = DEFAULT_RETRY_SECONDS
    outcome_unknown: bool = False


class DeliveryStore(Protocol):
    def load(self, operation_id: str) -> DeliveryRecord: ...
    def claim(
        self,
        record: DeliveryRecord,
        *,
        attempt_id: str,
        now_epoch: int,
    ) -> DeliveryRecord | None: ...
    def mark_delivered(
        self, record: DeliveryRecord, *, attempt_id: str, message_id: str, now_epoch: int
    ) -> None: ...
    def mark_failed(
        self,
        record: DeliveryRecord,
        *,
        attempt_id: str,
        status: DeliveryStatus,
        code: str,
        next_attempt_epoch: int | None,
        outcome_unknown: bool,
        now_epoch: int,
    ) -> None: ...


class DiscordMessages(Protocol):
    def create(self, *, channel_id: str, nonce: str, content: str) -> str: ...
    def edit(self, *, channel_id: str, message_id: str, content: str) -> str: ...


class RetryQueue(Protocol):
    def schedule(self, *, operation_id: str, source_revision: int, delay_seconds: int) -> None: ...


class DiscordDeliveryService:
    def __init__(
        self,
        store: DeliveryStore,
        messages: DiscordMessages,
        retry_queue: RetryQueue,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._messages = messages
        self._retry_queue = retry_queue
        self._clock = clock

    def deliver(self, *, operation_id: str, attempt_id: str, source_revision: int = 0) -> None:
        now_epoch = int(self._clock().timestamp())
        record = self._store.load(operation_id)
        if record.source_revision != source_revision:
            return
        if (
            record.message_id is None
            and record.delivery_status is DeliveryStatus.FAILED
            and record.outcome_unknown
        ):
            # A prior create may exist without a persisted identity. A newer
            # projection cannot safely create another message after recovery expiry.
            return
        if record.delivery_source_revision in {
            None,
            source_revision,
        } and record.delivery_status in {DeliveryStatus.DELIVERED, DeliveryStatus.FAILED}:
            return
        if record.delivered_revision is not None and record.delivered_revision >= source_revision:
            return
        if (
            record.delivery_status is DeliveryStatus.RETRYABLE_FAILED
            and record.next_attempt_epoch is not None
            and now_epoch < record.next_attempt_epoch
        ):
            self._retry_queue.schedule(
                operation_id=operation_id,
                source_revision=source_revision,
                delay_seconds=min(MAX_RETRY_SECONDS, max(1, record.next_attempt_epoch - now_epoch)),
            )
            return
        claimed = self._store.claim(record, attempt_id=attempt_id, now_epoch=now_epoch)
        if claimed is None:
            return
        if self._ambiguous_window_expired(claimed, now_epoch=now_epoch):
            self._store.mark_failed(
                claimed,
                attempt_id=attempt_id,
                status=DeliveryStatus.FAILED,
                code="DISCORD_CREATE_OUTCOME_AMBIGUOUS",
                next_attempt_epoch=None,
                outcome_unknown=True,
                now_epoch=now_epoch,
            )
            return
        try:
            content = render_operation_projection(claimed)
            if claimed.message_id is None:
                message_id = self._messages.create(
                    channel_id=claimed.channel_id,
                    nonce=operation_nonce(claimed.operation_id),
                    content=content,
                )
            else:
                message_id = self._messages.edit(
                    channel_id=claimed.channel_id,
                    message_id=claimed.message_id,
                    content=content,
                )
        except DiscordFailure as failure:
            delay_supported = failure.retry_after_seconds <= MAX_RETRY_SECONDS
            retryable = (
                failure.retryable
                and delay_supported
                and claimed.attempt_count < MAX_DELIVERY_ATTEMPTS
            )
            status = DeliveryStatus.RETRYABLE_FAILED if retryable else DeliveryStatus.FAILED
            delay = max(1, failure.retry_after_seconds)
            next_attempt = now_epoch + delay if retryable else None
            self._store.mark_failed(
                claimed,
                attempt_id=attempt_id,
                status=status,
                code=(failure.code if delay_supported else "DISCORD_RETRY_DELAY_UNSUPPORTED"),
                next_attempt_epoch=next_attempt,
                outcome_unknown=failure.outcome_unknown,
                now_epoch=now_epoch,
            )
            return
        self._store.mark_delivered(
            claimed,
            attempt_id=attempt_id,
            message_id=message_id,
            now_epoch=now_epoch,
        )

    @staticmethod
    def _ambiguous_window_expired(record: DeliveryRecord, *, now_epoch: int) -> bool:
        if not record.outcome_unknown and not record.resumed_pending:
            return False
        return (
            record.first_attempt_epoch is not None
            and now_epoch - record.first_attempt_epoch > AMBIGUOUS_CREATE_WINDOW_SECONDS
        )


def operation_nonce(operation_id: str) -> str:
    """Map any valid Operation identity to Discord's 25-character nonce limit."""
    digest = hashlib.sha256(operation_id.encode("utf-8")).digest()[:16]
    value = int.from_bytes(digest)
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, 36)
        encoded = alphabet[remainder] + encoded
    return (encoded or "0").rjust(25, "0")


def render_status_projection(projection: object) -> str:
    if not isinstance(projection, dict) or set(projection) != {
        "schema_version",
        "kind",
        "status",
        "ready",
        "health",
        "endpoint",
        "observed_at",
        "summary",
    }:
        raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
    if projection.get("schema_version") != 1 or projection.get("kind") != "STATUS":
        raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
    status = projection.get("status")
    health = projection.get("health")
    summary = projection.get("summary")
    endpoint = projection.get("endpoint")
    if (
        status not in {"stopped", "starting", "online", "stopping", "degraded", "unknown"}
        or health not in {"healthy", "degraded", "unhealthy", "unknown"}
        or not isinstance(summary, str)
        or len(summary) > 200
        or (endpoint is not None and (not isinstance(endpoint, str) or len(endpoint) > 253))
    ):
        raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
    lines = [f"Minecraft: {status}", summary]
    if endpoint is not None:
        lines.append(f"Endpoint: {endpoint}")
    lines.append(f"Health: {health}")
    return "\n".join(lines)


def render_operation_projection(record: DeliveryRecord) -> str:
    if record.operation_type == "STATUS":
        return render_status_projection(record.projection)
    if record.operation_type != "START":
        raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
    if record.operation_status == "SUCCEEDED":
        return "Minecraft START: online and ready."
    if record.operation_status in {"FAILED", "TIMED_OUT", "CANCELLED"}:
        return "Minecraft START: failed safely. Check the operation log with an administrator."
    steps = {
        "ADMITTED": "Minecraft START: accepted.",
        "DESIRED_RUNNING": "Minecraft START: preparing the requested running state.",
        "EC2_STARTING": "Minecraft START: starting the server host.",
        "HOST_RUNTIME_STARTING": "Minecraft START: starting Minecraft.",
        "ENDPOINT_CONVERGING": "Minecraft START: checking readiness and connection endpoint.",
    }
    return steps.get(record.current_step, "Minecraft START: in progress.")


class DiscordHttpClient:
    def __init__(self, *, token: str, timeout_seconds: int = 5) -> None:
        if not token:
            raise ValueError("Discord Bot Token is unavailable")
        self._token = token
        self._timeout = timeout_seconds

    def create(self, *, channel_id: str, nonce: str, content: str) -> str:
        payload = {
            "content": content,
            "nonce": nonce,
            "enforce_nonce": True,
            "allowed_mentions": {"parse": []},
        }
        value = self._request("POST", f"/channels/{channel_id}/messages", payload)
        message_id = value.get("id")
        returned_nonce = value.get("nonce")
        if not isinstance(message_id, str) or not message_id.isdecimal():
            raise DiscordFailure("DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=True)
        if returned_nonce is not None and returned_nonce != nonce:
            raise DiscordFailure("DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=True)
        return message_id

    def edit(self, *, channel_id: str, message_id: str, content: str) -> str:
        value = self._request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            {"content": content, "allowed_mentions": {"parse": []}},
        )
        returned = value.get("id")
        if returned != message_id:
            raise DiscordFailure("DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=False)
        return message_id

    def _request(self, method: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            DISCORD_API_BASE + path,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            method=method,
            headers={
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "Wishicraft (https://github.com/eash-misoni/wishicraft-server, 1)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read(64 * 1024 + 1)
        except urllib.error.HTTPError as error:
            self._raise_http(error)
        except (urllib.error.URLError, TimeoutError) as error:
            raise DiscordFailure("DISCORD_NETWORK_FAILURE", True, outcome_unknown=True) from error
        if len(raw) > 64 * 1024:
            raise DiscordFailure("DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=True)
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DiscordFailure(
                "DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=True
            ) from error
        if not isinstance(value, dict):
            raise DiscordFailure("DISCORD_MALFORMED_RESPONSE", True, outcome_unknown=True)
        return value

    @staticmethod
    def _raise_http(error: urllib.error.HTTPError) -> None:
        status = error.code
        if status == 429:
            retry_after = DEFAULT_RETRY_SECONDS
            try:
                raw = error.read(4097)
                value = json.loads(raw) if len(raw) <= 4096 else None
                raw_retry = value.get("retry_after") if isinstance(value, dict) else None
                if (
                    isinstance(raw_retry, (int, float))
                    and not isinstance(raw_retry, bool)
                    and math.isfinite(raw_retry)
                ):
                    retry_after = max(1, math.ceil(raw_retry))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            raise DiscordFailure("DISCORD_RATE_LIMITED", True, retry_after, False)
        if status in {401, 403}:
            raise DiscordFailure("DISCORD_AUTHORIZATION_FAILED", False)
        if status == 404:
            raise DiscordFailure("DISCORD_MESSAGE_OR_CHANNEL_NOT_FOUND", False)
        if 500 <= status <= 599:
            raise DiscordFailure("DISCORD_SERVER_FAILURE", True, outcome_unknown=True)
        raise DiscordFailure("DISCORD_REQUEST_REJECTED", False)
