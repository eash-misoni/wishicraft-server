from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wishicraft.auto_stop import (
    AutoStopCandidate,
    AutoStopIntent,
    AutoStopIntentStatus,
    deterministic_intent_id,
    deterministic_stop_idempotency_key,
    evaluate_candidate,
    intent_matches_heartbeat,
)
from wishicraft.runtime_heartbeat import ProtocolState, RuntimeHeartbeat

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def heartbeat(
    *,
    age: timedelta = timedelta(),
    empty_age: timedelta = timedelta(minutes=25),
    count: int | None = 0,
    protocol: ProtocolState = ProtocolState.READY,
    boot_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
) -> RuntimeHeartbeat:
    observed = NOW - age
    return RuntimeHeartbeat(
        system_id="wishicraft-main",
        schema_version=1,
        instance_id="i-0123456789abcdef0",
        runtime_id="wishicraft-host-runtime",
        boot_id=boot_id,
        active_game_id="game-vanilla-main",
        protocol_state=protocol,
        player_count=count,
        empty_since=NOW - empty_age if count == 0 else None,
        observed_at=observed,
        expires_at=int(observed.timestamp()) + 86400,
    )


def candidate(value: RuntimeHeartbeat | None, **kwargs: object) -> AutoStopCandidate:
    return evaluate_candidate(
        heartbeat=value,
        game_id="game-vanilla-main",
        runtime_id="wishicraft-host-runtime",
        idle_timeout_minutes=30,
        desired_state="RUNNING",
        now=NOW,
        **kwargs,
    )


def test_warning_window_uses_per_game_30_minute_policy_and_five_minute_lead() -> None:
    assert not candidate(heartbeat(empty_age=timedelta(minutes=24, seconds=59))).eligible
    result = candidate(heartbeat(empty_age=timedelta(minutes=25)))
    assert result.eligible
    assert result.reason == "WARNING_ELIGIBLE"


def test_candidate_is_fail_closed_for_positive_unknown_stale_and_identity_mismatch() -> None:
    assert not candidate(heartbeat(count=1)).eligible
    assert not candidate(heartbeat(count=None, protocol=ProtocolState.UNKNOWN)).eligible
    assert not candidate(heartbeat(age=timedelta(minutes=5, seconds=1))).eligible
    wrong_boot = heartbeat(boot_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    result = candidate(wrong_boot)
    assert result.intent_id == deterministic_intent_id(
        game_id="game-vanilla-main",
        boot_id=wrong_boot.boot_id,
        empty_since=wrong_boot.empty_since,  # type: ignore[arg-type]
    )


def test_intent_and_stop_idempotency_are_stable_for_an_empty_period() -> None:
    value = heartbeat()
    first = candidate(value)
    second = candidate(value)
    assert first.intent_id == second.intent_id
    assert deterministic_stop_idempotency_key(first.intent_id or "") == (
        deterministic_stop_idempotency_key(second.intent_id or "")
    )


def test_warning_delivery_time_can_delay_stop_beyond_idle_timeout() -> None:
    value = heartbeat(empty_age=timedelta(minutes=29))
    delivered = NOW
    intent = AutoStopIntent(
        intent_id=candidate(value).intent_id or "",
        game_id="game-vanilla-main",
        boot_id=value.boot_id,
        empty_since=value.empty_since,  # type: ignore[arg-type]
        idle_timeout_minutes=30,
        warning_lead_minutes=5,
        warning_delivery_id="asw-test",
        warning_delivery_state="DELIVERED",
        warning_delivered_at=delivered,
        status=AutoStopIntentStatus.WARNING_DELIVERED,
        created_at=NOW,
        updated_at=NOW,
    )
    assert intent.stop_eligible_at() == delivered + timedelta(minutes=5)
    assert intent_matches_heartbeat(
        intent,
        value,
        runtime_id="wishicraft-host-runtime",
        now=NOW,
    )
    assert not intent_matches_heartbeat(
        intent,
        heartbeat(count=1),
        runtime_id="wishicraft-host-runtime",
        now=NOW,
    )
