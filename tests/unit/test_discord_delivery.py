from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from email.message import Message
from typing import cast

import pytest

from wishicraft.discord_delivery import (
    DeliveryRecord,
    DeliveryStatus,
    DiscordDeliveryService,
    DiscordFailure,
    DiscordHttpClient,
    operation_nonce,
    render_status_projection,
)


def projection(status: str = "online") -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "STATUS",
        "status": status,
        "ready": status == "online",
        "health": "healthy",
        "endpoint": "mc-dev.wishicraft.net" if status == "online" else None,
        "observed_at": "2026-08-31T00:00:00.000000Z",
        "summary": "The server is online and ready.",
    }


class Store:
    def __init__(self) -> None:
        self.record = DeliveryRecord(
            operation_id="op-status-001",
            operation_status="SUCCEEDED",
            channel_id="1531883129525244015",
            projection=projection(),
        )
        self.operation_result = "SUCCEEDED"

    def load(self, operation_id: str) -> DeliveryRecord:
        assert operation_id == self.record.operation_id
        return self.record

    def claim(
        self, record: DeliveryRecord, *, attempt_id: str, now_epoch: int
    ) -> DeliveryRecord | None:
        same_source = record.delivery_source_revision == record.source_revision
        if same_source and record.delivery_status is DeliveryStatus.PENDING:
            return (
                replace(record, resumed_pending=True) if record.attempt_id == attempt_id else None
            )
        if same_source and record.delivery_status in {
            DeliveryStatus.DELIVERED,
            DeliveryStatus.FAILED,
        }:
            return None
        self.record = replace(
            record,
            delivery_status=DeliveryStatus.PENDING,
            delivery_source_revision=record.source_revision,
            attempt_id=attempt_id,
            attempt_count=record.attempt_count + 1,
            first_attempt_epoch=record.first_attempt_epoch or now_epoch,
            next_attempt_epoch=None,
        )
        return self.record

    def mark_delivered(
        self, record: DeliveryRecord, *, attempt_id: str, message_id: str, now_epoch: int
    ) -> None:
        assert self.record.attempt_id == attempt_id
        self.record = replace(
            self.record,
            delivery_status=DeliveryStatus.DELIVERED,
            message_id=message_id,
            delivered_revision=record.source_revision,
        )

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
    ) -> None:
        assert self.record.attempt_id == attempt_id
        self.record = replace(
            self.record,
            delivery_status=status,
            next_attempt_epoch=next_attempt_epoch,
            outcome_unknown=outcome_unknown,
        )


class Messages:
    def __init__(self, failures: list[BaseException] | None = None) -> None:
        self.failures = failures or []
        self.calls: list[dict[str, str]] = []
        self.by_nonce: dict[str, str] = {}

    def create(self, *, channel_id: str, nonce: str, content: str) -> str:
        self.calls.append({"channel_id": channel_id, "nonce": nonce, "content": content})
        if nonce not in self.by_nonce:
            self.by_nonce[nonce] = "1532999999999999999"
        if self.failures:
            raise self.failures.pop(0)
        return self.by_nonce[nonce]

    def edit(self, *, channel_id: str, message_id: str, content: str) -> str:
        self.calls.append({"channel_id": channel_id, "message_id": message_id, "content": content})
        if self.failures:
            raise self.failures.pop(0)
        return message_id


class Queue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def schedule(self, *, operation_id: str, source_revision: int, delay_seconds: int) -> None:
        assert source_revision == 0
        self.calls.append((operation_id, delay_seconds))


def service(
    store: Store, messages: Messages, queue: Queue, *, epoch: int = 1788134400
) -> DiscordDeliveryService:
    return DiscordDeliveryService(
        store,
        messages,
        queue,
        clock=lambda: datetime.fromtimestamp(epoch, UTC),
    )


def test_same_operation_and_duplicate_event_create_one_logical_message() -> None:
    store, messages, queue = Store(), Messages(), Queue()
    delivery = service(store, messages, queue)
    delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    assert len(messages.calls) == 1
    assert store.record.delivery_status == DeliveryStatus.DELIVERED
    assert store.record.message_id == "1532999999999999999"
    assert store.operation_result == "SUCCEEDED"


def test_create_success_then_crash_before_persistence_recovers_with_same_nonce() -> None:
    store = Store()
    messages = Messages([RuntimeError("simulated process crash after Discord accepted create")])
    queue = Queue()
    delivery = service(store, messages, queue)
    with pytest.raises(RuntimeError, match="simulated process crash"):
        delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    assert store.record.delivery_status is DeliveryStatus.PENDING
    delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    assert len(messages.calls) == 2
    assert messages.calls[0]["nonce"] == messages.calls[1]["nonce"]
    assert len(messages.by_nonce) == 1
    assert store.load("op-status-001").delivery_status == DeliveryStatus.DELIVERED


def test_unknown_timeout_retries_with_same_nonce_inside_recovery_window() -> None:
    store = Store()
    messages = Messages([DiscordFailure("DISCORD_NETWORK_FAILURE", True, 5, outcome_unknown=True)])
    queue = Queue()
    service(store, messages, queue, epoch=100).deliver(
        operation_id="op-status-001", attempt_id="ddb:terminal"
    )
    service(store, messages, queue, epoch=101).deliver(
        operation_id="op-status-001", attempt_id="ddb:metadata"
    )
    assert queue.calls == [("op-status-001", 4)]
    service(store, messages, queue, epoch=105).deliver(
        operation_id="op-status-001", attempt_id="sqs:retry-1"
    )
    assert len(messages.calls) == 2
    assert messages.calls[0]["nonce"] == messages.calls[1]["nonce"]
    assert store.record.delivery_status is DeliveryStatus.DELIVERED


def test_ambiguous_create_is_not_retried_after_nonce_recovery_window() -> None:
    store = Store()
    store.record = replace(
        store.record,
        delivery_status=DeliveryStatus.PENDING,
        delivery_source_revision=0,
        attempt_id="ddb:event-1",
        attempt_count=1,
        first_attempt_epoch=100,
    )
    messages, queue = Messages(), Queue()
    service(store, messages, queue, epoch=131).deliver(
        operation_id="op-status-001", attempt_id="ddb:event-1"
    )
    assert messages.calls == []
    assert store.record.delivery_status is DeliveryStatus.FAILED
    assert store.operation_result == "SUCCEEDED"


def test_competing_worker_and_stale_retry_do_not_create() -> None:
    store = Store()
    store.record = replace(
        store.record,
        delivery_status=DeliveryStatus.PENDING,
        delivery_source_revision=0,
        attempt_id="ddb:winner",
        attempt_count=1,
        first_attempt_epoch=1788134400,
    )
    messages, queue = Messages(), Queue()
    service(store, messages, queue).deliver(
        operation_id="op-status-001", attempt_id="ddb:competitor"
    )
    assert messages.calls == []


@pytest.mark.parametrize("terminal", [DeliveryStatus.DELIVERED, DeliveryStatus.FAILED])
def test_terminal_delivery_event_reprocessing_is_noop(terminal: DeliveryStatus) -> None:
    store = Store()
    store.record = replace(
        store.record,
        delivery_status=terminal,
        message_id="1532999999999999999" if terminal is DeliveryStatus.DELIVERED else None,
    )
    messages, queue = Messages(), Queue()
    service(store, messages, queue).deliver(operation_id="op-status-001", attempt_id="ddb:stale")
    assert messages.calls == []
    assert queue.calls == []


def test_retryable_failure_is_durable_state_then_stream_schedules_queue() -> None:
    store = Store()
    messages = Messages([DiscordFailure("DISCORD_RATE_LIMITED", True, 17, False)])
    queue = Queue()
    delivery = service(store, messages, queue)
    delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    assert store.record.delivery_status is DeliveryStatus.RETRYABLE_FAILED
    assert queue.calls == []
    delivery.deliver(operation_id="op-status-001", attempt_id="ddb:event-2")
    assert queue.calls == [("op-status-001", 17)]
    assert store.operation_result == "SUCCEEDED"


def test_known_not_created_429_can_retry_after_ambiguity_window() -> None:
    store = Store()
    store.record = replace(
        store.record,
        delivery_status=DeliveryStatus.RETRYABLE_FAILED,
        attempt_id="ddb:terminal",
        attempt_count=1,
        first_attempt_epoch=100,
        next_attempt_epoch=165,
        outcome_unknown=False,
    )
    messages, queue = Messages(), Queue()
    service(store, messages, queue, epoch=165).deliver(
        operation_id="op-status-001", attempt_id="sqs:rate-limit"
    )
    assert len(messages.calls) == 1
    assert store.record.delivery_status is DeliveryStatus.DELIVERED


def test_retry_after_beyond_sqs_limit_fails_without_early_retry() -> None:
    store = Store()
    messages = Messages([DiscordFailure("DISCORD_RATE_LIMITED", True, 901, False)])
    queue = Queue()
    service(store, messages, queue).deliver(operation_id="op-status-001", attempt_id="ddb:terminal")
    assert store.record.delivery_status is DeliveryStatus.FAILED
    assert queue.calls == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (DiscordFailure("SERVER", True, 5, True), DeliveryStatus.RETRYABLE_FAILED),
        (DiscordFailure("TIMEOUT", True, 5, True), DeliveryStatus.RETRYABLE_FAILED),
        (DiscordFailure("NETWORK", True, 5, True), DeliveryStatus.RETRYABLE_FAILED),
        (DiscordFailure("AUTH", False), DeliveryStatus.FAILED),
        (DiscordFailure("NOT_FOUND", False), DeliveryStatus.FAILED),
        (DiscordFailure("MALFORMED", True, 5, True), DeliveryStatus.RETRYABLE_FAILED),
    ],
)
def test_failure_classification_does_not_change_control_plane_result(
    failure: DiscordFailure, expected: DeliveryStatus
) -> None:
    store, messages, queue = Store(), Messages([failure]), Queue()
    service(store, messages, queue).deliver(operation_id="op-status-001", attempt_id="ddb:event-1")
    assert store.record.delivery_status is expected
    assert store.operation_result == "SUCCEEDED"


def test_nonce_is_stable_unique_width_and_projection_is_safe() -> None:
    assert operation_nonce("op-status-001") == operation_nonce("op-status-001")
    assert operation_nonce("op-status-001") != operation_nonce("op-status-002")
    assert len(operation_nonce("op-status-001")) == 25
    sample = {operation_nonce(f"op-{index:04d}") for index in range(1000)}
    assert len(sample) == 1000
    assert all(len(value) == 25 and value.isalnum() and value == value.lower() for value in sample)
    rendered = render_status_projection(projection())
    assert "online" in rendered
    assert "mc-dev.wishicraft.net" in rendered
    unsafe = {**projection(), "raw_exception": "token-like internal detail"}
    with pytest.raises(DiscordFailure) as error:
        render_status_projection(unsafe)
    assert "token-like" not in str(error.value)


def test_start_progress_updates_one_message_monotonically() -> None:
    store, messages, queue = Store(), Messages(), Queue()
    store.record = replace(
        store.record,
        operation_id="op-start-001",
        operation_type="START",
        operation_status="PENDING",
        current_step="ADMITTED",
        source_revision=0,
        projection={},
    )
    delivery = service(store, messages, queue)
    delivery.deliver(operation_id="op-start-001", source_revision=0, attempt_id="ddb:insert")
    message_id = store.record.message_id
    assert message_id is not None

    store.record = replace(
        store.record,
        operation_status="RUNNING",
        current_step="EC2_STARTING",
        source_revision=1,
    )
    delivery.deliver(operation_id="op-start-001", source_revision=1, attempt_id="ddb:step-1")
    store.record = replace(
        store.record,
        operation_status="SUCCEEDED",
        source_revision=2,
    )
    delivery.deliver(operation_id="op-start-001", source_revision=2, attempt_id="ddb:terminal")

    assert len(messages.by_nonce) == 1
    assert len(messages.calls) == 3
    assert messages.calls[1]["message_id"] == message_id
    assert messages.calls[2]["message_id"] == message_id
    assert "online" in messages.calls[2]["content"]
    delivery.deliver(operation_id="op-start-001", source_revision=1, attempt_id="ddb:stale")
    assert len(messages.calls) == 3


def test_newer_revision_can_recover_after_older_delivery_failed() -> None:
    store, messages, queue = Store(), Messages(), Queue()
    store.record = replace(
        store.record,
        operation_id="op-start-002",
        operation_type="START",
        operation_status="RUNNING",
        current_step="EC2_STARTING",
        source_revision=1,
        projection={},
        delivery_source_revision=1,
        delivery_status=DeliveryStatus.FAILED,
    )
    store.record = replace(store.record, source_revision=2, current_step="HOST_RUNTIME_STARTING")
    service(store, messages, queue).deliver(
        operation_id="op-start-002", source_revision=2, attempt_id="ddb:newer"
    )
    assert store.record.delivery_status is DeliveryStatus.DELIVERED
    assert store.record.delivered_revision == 2


class Response:
    def __init__(self, value: object) -> None:
        self.raw = json.dumps(value).encode()

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.raw[:size]


def test_http_create_uses_nonce_enforcement_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def urlopen(request: object, timeout: int) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response({"id": "1532999999999999999", "nonce": "nonce-1"})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    client = DiscordHttpClient(token="synthetic-unit-token")
    assert client.create(channel_id="123", nonce="nonce-1", content="safe") == (
        "1532999999999999999"
    )
    request = cast(urllib.request.Request, captured["request"])
    body = json.loads(cast(bytes, request.data))
    assert body["enforce_nonce"] is True
    assert body["allowed_mentions"] == {"parse": []}
    assert "synthetic-unit-token" not in json.dumps(body)


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "DISCORD_AUTHORIZATION_FAILED", False),
        (403, "DISCORD_AUTHORIZATION_FAILED", False),
        (404, "DISCORD_MESSAGE_OR_CHANNEL_NOT_FOUND", False),
        (500, "DISCORD_SERVER_FAILURE", True),
    ],
)
def test_http_error_classification(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, retryable: bool
) -> None:
    def urlopen(request: object, timeout: int) -> Response:
        raise urllib.error.HTTPError("redacted", status, "error", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient(token="synthetic-unit-token").create(
            channel_id="123", nonce="nonce", content="safe"
        )
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert "synthetic-unit-token" not in str(error.value)


def test_http_429_respects_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: object, timeout: int) -> Response:
        body = io.BytesIO(b'{"retry_after":12.25,"message":"do not persist"}')
        raise urllib.error.HTTPError("redacted", 429, "rate", Message(), body)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient(token="synthetic-unit-token").create(
            channel_id="123", nonce="nonce", content="safe"
        )
    assert error.value.code == "DISCORD_RATE_LIMITED"
    assert error.value.retry_after_seconds == 13


@pytest.mark.parametrize(
    "transport_error",
    [urllib.error.URLError("synthetic network failure"), TimeoutError("synthetic timeout")],
)
def test_http_transport_failures_are_retryable_without_token_leak(
    monkeypatch: pytest.MonkeyPatch, transport_error: Exception
) -> None:
    def urlopen(request: object, timeout: int) -> Response:
        raise transport_error

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient(token="synthetic-unit-token").create(
            channel_id="123", nonce="nonce", content="safe"
        )
    assert error.value.code == "DISCORD_NETWORK_FAILURE"
    assert error.value.retryable is True
    assert error.value.outcome_unknown is True
    assert "synthetic-unit-token" not in str(error.value)


def test_malformed_success_is_retryable_unknown_without_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: Response({"unexpected": "credential-like-body"}),
    )
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient(token="synthetic-unit-token").create(
            channel_id="123", nonce="nonce", content="safe"
        )
    assert error.value.code == "DISCORD_MALFORMED_RESPONSE"
    assert error.value.outcome_unknown is True
    assert "credential-like-body" not in str(error.value)


def test_edit_404_is_permanent_and_does_not_imply_recreate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(request: object, timeout: int) -> Response:
        raise urllib.error.HTTPError("redacted", 404, "missing", Message(), io.BytesIO(b"{}"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient(token="synthetic-unit-token").edit(
            channel_id="123", message_id="456", content="safe"
        )
    assert error.value.code == "DISCORD_MESSAGE_OR_CHANNEL_NOT_FOUND"
    assert error.value.retryable is False
