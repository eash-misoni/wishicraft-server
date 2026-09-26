from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from wishicraft import daily_backup as d
from wishicraft.system_state import utc_timestamp

NOW = datetime(2026, 9, 26, tzinfo=UTC)
VOLUME = "vol-test"


def state() -> dict[str, Any]:
    return dict(
        system_id="system",
        desired_state="STOPPED",
        desired_revision=3,
        desired_game_id="game-a",
        health="HEALTHY",
        observed_at=utc_timestamp(NOW),
        observation={"ec2_state": "stopped"},
        target_instance_id="i-test",
        current_operation_id=None,
        discrepancies=[],
        observation_errors=[],
        backup_protection=d.stopped(d.initial(VOLUME, NOW), NOW),
    )


def protected() -> dict[str, Any]:
    return d.success(
        d.initial(VOLUME, NOW),
        boundary=1,
        operation="op-old",
        snapshot="snap-old",
        acquired_at=utc_timestamp(NOW),
        now=NOW,
    )


def view(p: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return d.status(
        p,
        kwargs.pop("state", state()),
        now=kwargs.pop("now", NOW),
        enabled=kwargs.pop("enabled", True),
        actual=kwargs.pop("actual", "stopped"),
        locked=kwargs.pop("locked", False),
    )


def test_initial_history_is_unknown_not_inferred_from_old_backup() -> None:
    p = d.read_protection({"last_backup_at": utc_timestamp(NOW)}, VOLUME, NOW)
    assert p["protected_boundary"] == 0 and p["oldest_at"] is None
    assert p["unknown_since"] == utc_timestamp(NOW)
    assert view(p)["reason"] == "NORMAL_STOP_REQUIRED"


def test_boundary_tracks_possible_changes_and_preserves_oldest() -> None:
    p = d.dirty(protected(), NOW)
    for minutes in range(1, 10):
        p = d.dirty(p, NOW + timedelta(minutes=minutes))
    assert p["boundary"] == 11 and p["oldest_at"] == utc_timestamp(NOW)
    assert p["stopped_at"] is None


def test_zero_players_is_never_a_clean_proof() -> None:
    s = state()
    s["player_count"] = 0
    assert view(s["backup_protection"], state=s)["unprotected"]


@pytest.mark.parametrize("seconds,expected", [(1799, False), (1800, True), (1801, True)])
def test_stopped_warning_threshold(seconds: int, expected: bool) -> None:
    p = state()["backup_protection"]
    assert view(p, now=NOW + timedelta(seconds=seconds))["stopped_warning"] is expected


@pytest.mark.parametrize("seconds,expected", [(86399, False), (86400, True), (86401, True)])
def test_interval_warning_while_running(seconds: int, expected: bool) -> None:
    p = d.dirty(protected(), NOW)
    s = {**state(), "desired_state": "RUNNING"}
    result = view(p, state=s, actual="running", now=NOW + timedelta(seconds=seconds))
    assert result["reason"] == "RUNNING" and result["interval_warning"] is expected
    assert not result["stopped_warning"]


def test_short_stops_restart_stop_clock_but_never_oldest_clock() -> None:
    p = d.stopped(d.dirty(protected(), NOW), NOW + timedelta(minutes=10))
    p = d.dirty(p, NOW + timedelta(minutes=11))
    p = d.stopped(p, NOW + timedelta(hours=24))
    result = view(p, now=NOW + timedelta(hours=24, minutes=1))
    assert result["interval_warning"] and not result["stopped_warning"]
    assert p["oldest_at"] == utc_timestamp(NOW)


def test_stopped_clock_is_idempotent_and_maintenance_does_not_clear_it() -> None:
    p = state()["backup_protection"]
    assert d.stopped(p, NOW + timedelta(hours=1)) == p
    changed = d.dirty(p, NOW + timedelta(minutes=10), unknown=True)
    assert changed["stopped_at"] == p["stopped_at"]
    assert changed["unknown_since"] == p["unknown_since"]


def test_late_success_cannot_protect_post_capture_boundary() -> None:
    p = d.dirty(protected(), NOW)
    captured = p["boundary"]
    p = d.dirty(p, NOW + timedelta(minutes=1))
    p = d.success(
        p,
        boundary=captured,
        operation="op-one",
        snapshot="snap-one",
        acquired_at=utc_timestamp(NOW),
        now=NOW + timedelta(hours=1),
    )
    assert p["boundary"] > p["protected_boundary"]
    assert p["oldest_at"] == utc_timestamp(NOW)
    assert p["last_success"]["acquired_at"] != p["last_success"]["verified_at"]


def test_protected_stopped_state_does_not_warn_for_old_snapshot() -> None:
    result = view(protected(), now=NOW + timedelta(days=100))
    assert result["reason"] == "PROTECTED"
    assert not result["interval_warning"] and not result["stopped_warning"]


def test_disabled_reenabled_preserves_history() -> None:
    p = d.stopped(d.dirty(protected(), NOW), NOW)
    assert view(p, enabled=False)["reason"] == "DISABLED"
    assert view(p, now=NOW + timedelta(days=2))["interval_warning"]
    assert p["oldest_at"] == utc_timestamp(NOW)


@pytest.mark.parametrize(
    "intent,reason",
    [("ADMITTED", "BACKUP_RUNNING"), ("UNKNOWN", "RECONCILIATION_REQUIRED"), ("FAILED", "FAILED")],
)
def test_intent_reasons(intent: str, reason: str) -> None:
    p = state()["backup_protection"]
    p["intent"] = {"status": intent}
    assert view(p)["reason"] == reason


@pytest.mark.parametrize(
    "change,actual,locked,reason",
    [
        ({"maintenance": {"status": "ACTIVE"}}, "stopped", False, "MAINTENANCE"),
        ({"maintenance": {"status": "INCIDENT"}}, "stopped", False, "MAINTENANCE"),
        ({"current_operation_id": "op-other"}, "stopped", False, "OTHER_OPERATION"),
        ({}, "stopped", True, "OTHER_OPERATION"),
        ({"health": "DEGRADED"}, "stopped", False, "OBSERVATION_UNKNOWN"),
        ({}, "unknown", False, "OBSERVATION_UNKNOWN"),
    ],
)
def test_wait_reasons(change: dict[str, Any], actual: str, locked: bool, reason: str) -> None:
    s = {**state(), **change}
    result = view(
        s["backup_protection"], state=s, actual=actual, locked=locked, now=NOW + timedelta(hours=24)
    )
    assert result["reason"] == reason and result["interval_warning"]
