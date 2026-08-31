"""Pure Phase 7 release-monitoring state evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class MonitoringThresholds:
    ec2_running_seconds: int
    desired_stopped_running_seconds: int
    desired_running_not_ready_seconds: int
    observation_freshness_seconds: int


@dataclass(frozen=True)
class MonitoringSnapshot:
    desired_state: str
    desired_updated_at: datetime | None
    observed_at: datetime | None
    observed_ec2_state: str | None
    runtime_ready: bool
    health: str | None
    discrepancies: tuple[object, ...]
    actual_ec2_state: str
    ec2_launch_time: datetime | None
    lock_lease_expires_at: int | None


METRIC_NAMES = (
    "TargetRunningTooLong",
    "DesiredStoppedEc2Running",
    "DesiredActualDivergence",
    "ExpiredOperationLock",
    "DesiredRunningNotReady",
    "MonitoringObservationUnknown",
)


def evaluate_monitoring_snapshot(
    snapshot: MonitoringSnapshot,
    *,
    now: datetime,
    thresholds: MonitoringThresholds,
) -> dict[str, float]:
    """Return complete 0/1 metrics without mutating Control Plane state."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)

    running = snapshot.actual_ec2_state == "running"
    stopped = snapshot.actual_ec2_state == "stopped"
    running_seconds = _age(now, snapshot.ec2_launch_time) if running else 0
    desired_age = _age(now, snapshot.desired_updated_at)
    observation_age = _age(now, snapshot.observed_at)
    observation_fresh = (
        snapshot.observed_at is not None
        and 0 <= observation_age <= thresholds.observation_freshness_seconds
    )
    desired_known = snapshot.desired_state in {"RUNNING", "STOPPED"}
    actual_known = snapshot.actual_ec2_state in {
        "pending",
        "running",
        "stopping",
        "stopped",
        "shutting-down",
        "terminated",
    }
    observation_required = snapshot.desired_state == "RUNNING"
    observation_unknown = not (desired_known and actual_known) or (
        observation_required
        and (not observation_fresh or snapshot.health not in {"HEALTHY", "DEGRADED"})
    )

    divergence = False
    if desired_known and actual_known:
        if snapshot.desired_state == "STOPPED":
            divergence = not stopped
        else:
            divergence = not running or not snapshot.runtime_ready
        divergence = divergence or bool(snapshot.discrepancies)

    stopped_running = (
        snapshot.desired_state == "STOPPED"
        and running
        and desired_age >= thresholds.desired_stopped_running_seconds
    )
    running_not_ready = (
        snapshot.desired_state == "RUNNING"
        and desired_age >= thresholds.desired_running_not_ready_seconds
        and (not running or not snapshot.runtime_ready or not observation_fresh)
    )
    expired_lock = (
        snapshot.lock_lease_expires_at is not None
        and snapshot.lock_lease_expires_at < int(now.timestamp())
    )

    return {
        "TargetRunningTooLong": float(
            running and running_seconds >= thresholds.ec2_running_seconds
        ),
        "DesiredStoppedEc2Running": float(stopped_running),
        "DesiredActualDivergence": float(divergence),
        "ExpiredOperationLock": float(expired_lock),
        "DesiredRunningNotReady": float(running_not_ready),
        "MonitoringObservationUnknown": float(observation_unknown),
    }


def _age(now: datetime, value: datetime | None) -> int:
    if value is None:
        return 0
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("monitoring timestamps must be timezone-aware")
    return max(0, int((now - value.astimezone(UTC)).total_seconds()))
