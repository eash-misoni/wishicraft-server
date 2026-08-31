from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from wishicraft.monitoring import (
    MonitoringSnapshot,
    MonitoringThresholds,
    evaluate_monitoring_snapshot,
)

NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
THRESHOLDS = MonitoringThresholds(
    ec2_running_seconds=8 * 3600,
    desired_stopped_running_seconds=15 * 60,
    desired_running_not_ready_seconds=20 * 60,
    observation_freshness_seconds=10 * 60,
)


def snapshot(**overrides: object) -> MonitoringSnapshot:
    values: dict[str, object] = {
        "desired_state": "STOPPED",
        "desired_updated_at": NOW - timedelta(days=1),
        "observed_at": NOW - timedelta(days=1),
        "observed_ec2_state": "stopped",
        "runtime_ready": False,
        "health": "HEALTHY",
        "discrepancies": (),
        "actual_ec2_state": "stopped",
        "ec2_launch_time": NOW - timedelta(days=2),
        "lock_lease_expires_at": None,
    }
    values.update(overrides)
    return MonitoringSnapshot(**values)  # type: ignore[arg-type]


def test_stable_stopped_state_is_normal_without_requiring_periodic_reconcile_mutation() -> None:
    assert set(
        evaluate_monitoring_snapshot(snapshot(), now=NOW, thresholds=THRESHOLDS).values()
    ) == {0.0}


@pytest.mark.parametrize(
    ("overrides", "metric"),
    [
        (
            {"actual_ec2_state": "running", "ec2_launch_time": NOW - timedelta(hours=9)},
            "TargetRunningTooLong",
        ),
        (
            {"actual_ec2_state": "running", "ec2_launch_time": NOW - timedelta(minutes=16)},
            "DesiredStoppedEc2Running",
        ),
        ({"actual_ec2_state": "running"}, "DesiredActualDivergence"),
        ({"lock_lease_expires_at": int(NOW.timestamp()) - 1}, "ExpiredOperationLock"),
        (
            {
                "desired_state": "RUNNING",
                "desired_updated_at": NOW - timedelta(minutes=21),
                "actual_ec2_state": "running",
                "runtime_ready": False,
            },
            "DesiredRunningNotReady",
        ),
        (
            {
                "desired_state": "RUNNING",
                "desired_updated_at": NOW - timedelta(minutes=1),
                "actual_ec2_state": "running",
                "runtime_ready": True,
                "observed_at": NOW - timedelta(minutes=11),
            },
            "MonitoringObservationUnknown",
        ),
    ],
)
def test_monitoring_conditions_emit_one_without_mutating_state(
    overrides: dict[str, object], metric: str
) -> None:
    metrics = evaluate_monitoring_snapshot(snapshot(**overrides), now=NOW, thresholds=THRESHOLDS)
    assert metrics[metric] == 1.0


def test_running_ready_fresh_state_is_normal() -> None:
    metrics = evaluate_monitoring_snapshot(
        snapshot(
            desired_state="RUNNING",
            desired_updated_at=NOW - timedelta(minutes=2),
            observed_at=NOW - timedelta(minutes=1),
            observed_ec2_state="running",
            actual_ec2_state="running",
            ec2_launch_time=NOW - timedelta(minutes=2),
            runtime_ready=True,
        ),
        now=NOW,
        thresholds=THRESHOLDS,
    )
    assert set(metrics.values()) == {0.0}
