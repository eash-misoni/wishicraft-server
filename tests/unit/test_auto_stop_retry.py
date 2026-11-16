from __future__ import annotations

import io
import urllib.error
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import cast

import pytest

from tests.unit.test_auto_stop_warning import ConditionalFailure, Dynamo, Messages
from wishicraft.auto_stop_warning import WarningDelivery
from wishicraft.discord_delivery import DiscordFailure, DiscordHttpClient


class RateLimitedMessages(Messages):
    def __init__(self, failure: DiscordFailure | None = None) -> None:
        super().__init__()
        self.failure = failure or DiscordFailure("DISCORD_RATE_LIMITED", True, 125)

    def create(self, *, channel_id: str, nonce: str, content: str) -> str:
        super().create(channel_id=channel_id, nonce=nonce, content=content)
        raise self.failure


NOW = datetime(2026, 11, 16, tzinfo=UTC)


def deliver(dynamo: Dynamo, messages: Messages, now: datetime = NOW) -> dict[str, object]:
    # New service instances deliberately share only durable state.
    return WarningDelivery(dynamo, messages, table_name="intents", clock=lambda: now).deliver(
        game_id="game-vanilla-main", intent_id="asi-example", now=now
    )


@pytest.mark.parametrize("delay", [5, 125, 901, 3600])
def test_rate_limit_deadline_survives_invocations_and_allows_exact_deadline(delay: int) -> None:
    dynamo = Dynamo()
    limited = RateLimitedMessages(DiscordFailure("DISCORD_RATE_LIMITED", True, delay))
    assert deliver(dynamo, limited) == {"state": "RETRYABLE_FAILED", "created": False}
    assert dynamo.item["warning_attempt_count"] == {"N": "1"}
    assert dynamo.item["warning_next_attempt_at"] == {
        "S": (NOW + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
    }
    messages = Messages()
    for elapsed in (0, delay - 0.001):
        assert deliver(dynamo, messages, NOW + timedelta(seconds=elapsed)) == {
            "state": "RETRYABLE_FAILED",
            "created": False,
        }
        assert dynamo.item["warning_attempt_count"] == {"N": "1"}
    assert not messages.calls
    due = NOW + timedelta(seconds=delay)
    assert deliver(dynamo, messages, due) == {"state": "DELIVERED", "created": True}
    assert dynamo.item["warning_attempt_count"] == {"N": "2"}
    assert dynamo.item["warning_next_attempt_at"] == {"NULL": True}
    assert dynamo.item["warning_delivered_at"] == {"S": due.isoformat().replace("+00:00", "Z")}
    assert deliver(dynamo, messages, due) == {"state": "DELIVERED", "created": False}
    assert len(messages.calls) == 1
    assert limited.calls[0]["nonce"] == messages.calls[0]["nonce"]


def test_three_attempt_ceiling_includes_initial_send_and_waits_do_not_count() -> None:
    dynamo, messages = Dynamo(), RateLimitedMessages()
    for attempt in range(1, 4):
        now = NOW + timedelta(seconds=(attempt - 1) * 125)
        expected = "RETRYABLE_FAILED" if attempt < 3 else "FAILED"
        assert deliver(dynamo, messages, now) == {"state": expected, "created": False}
        assert dynamo.item["warning_attempt_count"] == {"N": str(attempt)}
        assert deliver(dynamo, messages, now) == {"state": expected, "created": False}
        assert len(messages.calls) == attempt
    assert dynamo.item["warning_next_attempt_at"] == {"NULL": True}
    assert deliver(dynamo, messages, NOW + timedelta(days=1))["state"] == "FAILED"
    assert len(messages.calls) == 3


@pytest.mark.parametrize("deadline", [None, {"NULL": True}])
def test_legacy_record_without_deadline_can_retry(deadline: object) -> None:
    dynamo = Dynamo()
    dynamo.item["warning_delivery_state"] = {"S": "RETRYABLE_FAILED"}
    dynamo.item["warning_attempt_count"] = {"N": "1"}
    if deadline is not None:
        dynamo.item["warning_next_attempt_at"] = deadline
    assert deliver(dynamo, Messages())["state"] == "DELIVERED"
    assert dynamo.item["warning_attempt_count"] == {"N": "2"}


@pytest.mark.parametrize(
    "seconds", [0, -1, True, 1.5, float("nan"), float("inf"), None, "60", 10**30]
)
def test_invalid_upstream_delay_fails_closed(seconds: object) -> None:
    dynamo = Dynamo()
    messages = RateLimitedMessages(DiscordFailure("DISCORD_RATE_LIMITED", True, cast(int, seconds)))
    assert deliver(dynamo, messages)["state"] == "FAILED"
    assert dynamo.item["warning_delivery_error"] == {"S": "DISCORD_WARNING_RETRY_DELAY_INVALID"}
    assert dynamo.item["warning_next_attempt_at"] == {"NULL": True}
    deliver(dynamo, messages, NOW + timedelta(days=1))
    assert len(messages.calls) == 1


@pytest.mark.parametrize("deadline", [{"S": "bad"}, {"S": "2026-11-16T00:00:00"}, {"N": "123"}])
def test_malformed_stored_deadline_prevents_send(deadline: object) -> None:
    dynamo, messages = Dynamo(), Messages()
    dynamo.item["warning_next_attempt_at"] = deadline
    with pytest.raises(RuntimeError, match="invalid warning retry deadline"):
        deliver(dynamo, messages)
    assert not messages.calls
    assert dynamo.item["warning_attempt_count"] == {"N": "0"}


def test_default_retry_delay_is_preserved_when_failure_omits_timing() -> None:
    dynamo = Dynamo()
    deliver(dynamo, RateLimitedMessages(DiscordFailure("TRANSIENT", True)))
    messages = Messages()
    assert deliver(dynamo, messages, NOW + timedelta(seconds=4))["state"] == "RETRYABLE_FAILED"
    assert not messages.calls
    assert deliver(dynamo, messages, NOW + timedelta(seconds=5))["state"] == "DELIVERED"


@pytest.mark.parametrize(
    "body", [b"{}", b"invalid", b'{"retry_after":null}', b'{"retry_after":"125"}']
)
def test_missing_or_invalid_http_timing_retains_adapter_default(body: bytes) -> None:
    with pytest.raises(DiscordFailure) as error:
        DiscordHttpClient._raise_http(
            urllib.error.HTTPError("redacted", 429, "rate", Message(), io.BytesIO(body))
        )
    assert error.value.retry_after_seconds == 5
    dynamo = Dynamo()
    deliver(dynamo, RateLimitedMessages(error.value))
    messages = Messages()
    assert deliver(dynamo, messages, NOW + timedelta(seconds=4))["state"] == "RETRYABLE_FAILED"
    assert not messages.calls
    assert deliver(dynamo, messages, NOW + timedelta(seconds=5))["state"] == "DELIVERED"


@pytest.mark.parametrize(
    "failure",
    [
        DiscordFailure("UNKNOWN", True, 125, True),
        DiscordFailure("DENIED", False),
    ],
)
def test_unknown_outcome_and_nonretryable_failure_never_schedule(failure: DiscordFailure) -> None:
    dynamo, messages = Dynamo(), RateLimitedMessages(failure)
    assert deliver(dynamo, messages)["state"] == "FAILED"
    assert dynamo.item["warning_next_attempt_at"] == {"NULL": True}
    assert deliver(dynamo, messages, NOW + timedelta(days=1))["state"] == "FAILED"
    assert len(messages.calls) == 1


def test_exhausted_legacy_record_clears_deadline_without_send() -> None:
    dynamo, messages = Dynamo(), Messages()
    dynamo.item["warning_attempt_count"] = {"N": "3"}
    dynamo.item["warning_next_attempt_at"] = {"S": "2026-11-17T00:00:00Z"}
    assert deliver(dynamo, messages)["state"] == "FAILED"
    assert dynamo.item["status"] == {"S": "WARNING_FAILED"}
    assert dynamo.item["warning_next_attempt_at"] == {"NULL": True}
    assert not messages.calls


def test_cancelled_intent_cannot_claim_after_wait_and_new_period_has_no_deadline() -> None:
    dynamo = Dynamo()
    deliver(dynamo, RateLimitedMessages())
    dynamo.item["status"] = {"S": "CANCELLED"}
    messages = Messages()
    assert deliver(dynamo, messages, NOW + timedelta(seconds=125))["created"] is False
    assert not messages.calls
    assert dynamo.item["warning_attempt_count"] == {"N": "1"}
    new_period = Dynamo()
    assert deliver(new_period, messages)["state"] == "DELIVERED"
    assert new_period.item["warning_attempt_count"] == {"N": "1"}


def test_current_candidate_is_revalidated_while_waiting_and_at_deadline() -> None:
    dynamo, messages = Dynamo(), Messages()
    dynamo.item["warning_delivery_state"] = {"S": "RETRYABLE_FAILED"}
    dynamo.item["warning_next_attempt_at"] = {"S": "2026-11-16T00:02:05Z"}
    checks: list[datetime] = []

    class NoLongerSafe(WarningDelivery):
        def _current_candidate(self, item: dict[str, object], now: datetime) -> bool:
            checks.append(now)
            return False

    service = NoLongerSafe(dynamo, messages, table_name="intents", system_table="system")
    for now in (NOW, NOW + timedelta(seconds=125)):
        assert service.deliver(game_id="game-vanilla-main", intent_id="asi-example", now=now) == {
            "state": "STALE_TARGET",
            "created": False,
        }
    assert len(checks) == 2
    assert not messages.calls


def test_deadline_claim_race_does_not_send_or_increment_twice() -> None:
    class LostClaim(Dynamo):
        def update_item(self, **kwargs: object) -> object:
            values = kwargs["ExpressionAttributeValues"]
            assert isinstance(values, dict)
            if ":previous" in values:
                self.item["warning_attempt_count"] = {"N": "2"}
                self.item["warning_delivery_state"] = {"S": "PENDING"}
                raise ConditionalFailure
            return super().update_item(**kwargs)

    dynamo, messages = LostClaim(), Messages()
    dynamo.item["warning_attempt_count"] = {"N": "1"}
    dynamo.item["warning_delivery_state"] = {"S": "RETRYABLE_FAILED"}
    dynamo.item["warning_next_attempt_at"] = {"S": "2026-11-16T00:00:00Z"}
    assert deliver(dynamo, messages) == {"state": "PENDING", "created": False}
    assert not messages.calls


def test_wait_starts_after_http_response_not_before_request() -> None:
    dynamo, messages = Dynamo(), RateLimitedMessages()
    response_time = NOW + timedelta(seconds=10)
    WarningDelivery(dynamo, messages, table_name="intents", clock=lambda: response_time).deliver(
        game_id="game-vanilla-main", intent_id="asi-example", now=NOW
    )
    sent = Messages()
    assert deliver(dynamo, sent, NOW + timedelta(seconds=125))["state"] == "RETRYABLE_FAILED"
    assert not sent.calls
    assert deliver(dynamo, sent, response_time + timedelta(seconds=125))["state"] == "DELIVERED"


def test_retry_success_preserves_five_minute_stop_boundary() -> None:
    from wishicraft.auto_stop import AutoStopIntent, AutoStopIntentStatus

    dynamo = Dynamo()
    deliver(dynamo, RateLimitedMessages())
    assert "warning_delivered_at" not in dynamo.item
    delivered = NOW + timedelta(seconds=125)
    deliver(dynamo, Messages(), delivered)
    intent = AutoStopIntent(
        intent_id="asi-example",
        game_id="game-vanilla-main",
        boot_id="boot",
        empty_since=NOW - timedelta(minutes=30),
        idle_timeout_minutes=30,
        warning_lead_minutes=5,
        warning_delivery_id="asw-example",
        warning_delivery_state="DELIVERED",
        warning_delivered_at=datetime.fromisoformat(
            cast(dict[str, str], dynamo.item["warning_delivered_at"])["S"].replace("Z", "+00:00")
        ),
        status=AutoStopIntentStatus.WARNING_DELIVERED,
        created_at=NOW,
        updated_at=delivered,
    )
    assert intent.stop_eligible_at() == delivered + timedelta(minutes=5)
