"""Retry-safe Discord delivery of an already-safe Operation projection."""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from wishicraft.progress_display import MILESTONE_STEPS, game_text, safe_text, timestamp

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
    delivery_id: str | None = None
    delivery_source_revision: int | None = None
    delivered_revision: int | None = None
    resumed_pending: bool = False
    actor_source: str | None = None
    actor_name: str | None = None
    target_game_id: str | None = None
    source_game_id: str | None = None
    seed_mode: str | None = None
    requested_at: str | None = None
    milestones: tuple[tuple[str, str], ...] = ()


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
    fields = {
        "schema_version",
        "kind",
        "status",
        "ready",
        "health",
        "endpoint",
        "observed_at",
        "summary",
    }
    selection = {"selected_game_id", "observed_game_id", "current_operation_id"}
    worlds = {"selected_world_id", "observed_world_id"}
    if not isinstance(projection, dict) or set(projection) not in (
        fields,
        fields | selection,
        fields | selection | worlds,
    ):
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
    if "selected_game_id" in projection:
        for field, label, pattern in [
            ("selected_game_id", "Selected Game", r"game-[a-z0-9-]{1,100}"),
            ("observed_game_id", "Observed Game", r"game-[a-z0-9-]{1,100}"),
            ("current_operation_id", "Current Operation", r"op-[a-z0-9-]{1,100}"),
        ]:
            value = projection[field]
            if value is not None and (
                not isinstance(value, str) or re.fullmatch(pattern, value) is None
            ):
                raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
            lines.append(f"{label}: {value or 'none'}")
    if "selected_world_id" in projection:
        for field, label in [
            ("selected_world_id", "Selected world"),
            ("observed_world_id", "Observed world"),
        ]:
            value = projection[field]
            if value is not None and (
                not isinstance(value, str)
                or re.fullmatch(r"legacy|op-[a-z0-9-]{1,100}", value) is None
            ):
                raise DiscordFailure("INVALID_SAFE_PROJECTION", False)
            lines.append(f"{label}: {value or 'none'}")
    if endpoint is not None:
        lines.append(f"Endpoint: {safe_text(endpoint, 253)}")
    lines.append(f"Health: {health}")
    return "\n".join(lines)


def render_operation_projection(record: DeliveryRecord) -> str:
    if record.operation_type not in {"STATUS", "START", "STOP", "BACKUP", "SWITCH", "RESET"}:
        raise ValueError("unsupported public Operation")
    state = {
        "PENDING": "Accepted",
        "RUNNING": "In progress",
        "SUCCEEDED": "Completed",
        "FAILED": "Failed — completion not confirmed",
        "TIMED_OUT": "Timed out — check status",
        "CANCELLED": "Cancelled — not completed",
    }.get(record.operation_status)
    if state is None:
        raise ValueError("unsupported public status")
    # Cancellation is not a claim that all possible side effects have been undone.
    actor = {
        "ADMIN": "Operator",
        "CLI": "Operator",
        "SCHEDULE": "Scheduled execution",
        "WEB": "Web user (name not recorded)",
    }.get(record.actor_source or "", "Not recorded")
    if record.actor_source == "DISCORD":
        actor = (
            safe_text(record.actor_name) + " (Discord)"
            if record.actor_name
            else "Discord user (name not recorded)"
        )
    lines = [f"Minecraft {record.operation_type}: {state}", f"Requested by: {actor}"]
    target = game_text(record.target_game_id)
    if record.operation_type == "SWITCH":
        lines.append(f"Game: {game_text(record.source_game_id)} → {target}")
    elif record.operation_type == "BACKUP":
        lines.append(
            "Protection: shared data volume (all Games)"
            if record.projection.get("scope") == "shared-volume"
            else "Protection scope: not recorded here; selected Game is not the backup unit"
        )
        lines.append(f"Selected Game at request: {target}")
    else:
        lines.append(f"Game: {target}")
    if record.operation_type == "RESET":
        lines.append(
            "Seed policy: "
            + {"fixed": "fixed (0)", "new": "new, fixed for this operation"}.get(
                record.seed_mode or "", "not recorded"
            )
        )
    if record.operation_type == "STATUS" and record.operation_status == "SUCCEEDED":
        lines.append(render_status_projection(record.projection))
    facts = []
    if record.requested_at is not None:
        facts.append((timestamp(record.requested_at), "Request accepted"))
    for step, at in record.milestones:
        if step in MILESTONE_STEPS:
            facts.append((timestamp(at), MILESTONE_STEPS[step]))
    facts.sort(key=lambda fact: fact[0])
    lines.append("Recorded progress (phase entry, not proof of completion):")
    lines.extend("• " + label for _, label in facts[-4:])
    if not facts:
        lines.append("• Earlier progress not recorded")
    if record.operation_status in {"PENDING", "RUNNING"}:
        latest = MILESTONE_STEPS.get(
            record.current_step, "Accepted" if record.current_step == "ADMITTED" else "Processing"
        )
        lines.append("Latest recorded phase: " + latest)
    elif record.operation_status == "SUCCEEDED":
        lines.append(
            {
                "START": "Online and ready.",
                "STOP": "Stopped; connection unavailable.",
                "SWITCH": "Destination online and ready.",
                "RESET": "New world online and ready.",
                "BACKUP": "Backup completed.",
                "STATUS": "State observation completed.",
            }[record.operation_type]
        )
        if record.operation_type == "RESET" and record.projection.get("cleanup_pending") is True:
            lines.append("Old world cleanup pending; data retained.")
    else:
        lines.append("Check /mc status before retrying; contact an admin if the result is unclear.")
    content = "\n".join(lines)
    if len(content.encode("utf-16-le")) // 2 > 2000:
        raise ValueError("public message exceeds Discord limit")
    return content


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
