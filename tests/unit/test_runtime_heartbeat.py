from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wishicraft.runtime_heartbeat import (
    HEARTBEAT_CADENCE_SECONDS,
    HEARTBEAT_STALE_SECONDS,
    HEARTBEAT_TTL_SECONDS,
    HeartbeatError,
    ProtocolState,
    RuntimeHeartbeat,
    RuntimeObservation,
    assert_newer,
    derive_heartbeat,
    format_timestamp,
    parse_timestamp,
)

NOW = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)


def observation(**changes: object) -> RuntimeObservation:
    values: dict[str, object] = {
        "instance_id": "i-04fc0629dc4ea466e",
        "runtime_id": "wishicraft-host-runtime",
        "boot_id": "12345678-1234-1234-1234-123456789abc",
        "active_game_id": "game-vanilla-main",
        "protocol_state": ProtocolState.READY,
        "player_count": 0,
        "observed_at": NOW,
    }
    values.update(changes)
    return RuntimeObservation(**values)  # type: ignore[arg-type]


def heartbeat(**changes: object) -> RuntimeHeartbeat:
    current = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id="game-vanilla-main",
        observation=observation(),
        previous=None,
    )
    return RuntimeHeartbeat(**{**current.__dict__, **changes})


def derive(
    *, current: RuntimeObservation | None = None, previous: RuntimeHeartbeat | None = None
) -> RuntimeHeartbeat:
    return derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id="game-vanilla-main",
        observation=current or observation(),
        previous=previous,
    )


def test_timing_contract_and_ttl_are_independent_of_freshness() -> None:
    value = derive()
    assert HEARTBEAT_CADENCE_SECONDS == 60
    assert HEARTBEAT_STALE_SECONDS == 300
    assert HEARTBEAT_TTL_SECONDS == 86_400
    assert value.expires_at == int(NOW.timestamp()) + 86_400
    assert value.is_fresh(NOW + timedelta(minutes=5))
    assert not value.is_fresh(NOW + timedelta(minutes=5, microseconds=1))


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (observation(player_count=1), None),
        (observation(player_count=None), None),
        (observation(protocol_state=ProtocolState.NOT_READY, player_count=0), None),
        (observation(active_game_id="game-other", player_count=0), None),
    ],
)
def test_untrusted_or_positive_observation_clears_empty_since(
    current: RuntimeObservation, expected: None
) -> None:
    value = derive(current=current, previous=heartbeat())
    assert value.empty_since is expected
    if (
        current.active_game_id != "game-vanilla-main"
        or current.protocol_state is not ProtocolState.READY
    ):
        assert value.player_count is None


def test_first_zero_starts_and_continuous_zero_preserves_empty_period() -> None:
    first = derive()
    second = derive(current=observation(observed_at=NOW + timedelta(seconds=60)), previous=first)
    assert first.empty_since == NOW
    assert second.empty_since == NOW


@pytest.mark.parametrize(
    "previous",
    [
        heartbeat(boot_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        heartbeat(observed_at=NOW - timedelta(minutes=5, microseconds=1)),
        heartbeat(player_count=None, empty_since=None),
        heartbeat(protocol_state=ProtocolState.UNKNOWN, player_count=None, empty_since=None),
    ],
)
def test_broken_continuity_starts_a_new_zero_period(previous: RuntimeHeartbeat) -> None:
    assert derive(previous=previous).empty_since == NOW


def test_unknown_then_zero_and_positive_then_zero_start_new_periods() -> None:
    unknown = derive(current=observation(player_count=None))
    positive = derive(current=observation(player_count=2))
    later = observation(observed_at=NOW + timedelta(seconds=60))
    assert derive(current=later, previous=unknown).empty_since == later.observed_at
    assert derive(current=later, previous=positive).empty_since == later.observed_at


def test_ordering_and_clock_regression_fail_closed() -> None:
    previous = heartbeat()
    newer = derive(current=observation(observed_at=NOW + timedelta(seconds=1)), previous=previous)
    assert_newer(newer, previous)
    with pytest.raises(HeartbeatError, match="not newer"):
        assert_newer(derive(previous=previous), previous)


def test_timestamp_is_timezone_aware_and_normalized() -> None:
    assert parse_timestamp("2026-09-09T09:00:00+09:00") == NOW
    assert format_timestamp(NOW) == "2026-09-09T00:00:00.000000Z"
    with pytest.raises(HeartbeatError, match="timezone-aware"):
        parse_timestamp("2026-09-09T00:00:00")
