"""Independent heartbeat and filesystem monitoring; no Control Plane writes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from wishicraft.runtime_heartbeat import HEARTBEAT_STALE_SECONDS

BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return int(value)
    return None


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def fresh(value: object, now: datetime, seconds: int) -> bool:
    parsed = timestamp(value)
    return parsed is not None and 0 <= (now - parsed).total_seconds() <= seconds


def evaluate_telemetry(
    *,
    state: dict[str, Any],
    heartbeat: dict[str, Any],
    lock: dict[str, Any],
    instance: dict[str, Any],
    now: datetime,
    system_id: str,
    game_id: str,
    volume_id: str,
    filesystem_uuid: str,
    mount_path: str,
    observation_freshness_seconds: int,
    startup_grace_seconds: int,
    shutdown_grace_seconds: int,
    usage_warning_percent: int,
) -> tuple[dict[str, float], dict[str, str]]:
    """Emit alarm flags every cycle; emit capacity values only for valid observations."""
    metrics = dict.fromkeys(
        (
            "RuntimeHeartbeatUnavailable",
            "RuntimeObservationUnknown",
            "RuntimeIdentityMismatch",
            "SystemStateObservationStale",
            "DataFilesystemObservationUnknown",
            "DataFilesystemUsageHigh",
        ),
        0.0,
    )
    reasons = {"heartbeat": "not-expected", "runtime": "not-expected", "filesystem": "not-expected"}
    actual = instance.get("State", {}).get("Name")
    desired = state.get("desired_state")
    observed = state.get("observation")
    observed = observed if isinstance(observed, dict) else {}
    observation_fresh = fresh(state.get("observed_at"), now, observation_freshness_seconds)
    metrics["SystemStateObservationStale"] = float(desired == "RUNNING" and not observation_fresh)
    if actual == "stopped":
        return metrics, reasons
    changed = timestamp(state.get("desired_updated_at"))
    age = (now - changed).total_seconds() if changed is not None else -1
    lease = integer(lock.get("lease_expires_at"))
    owned_transition = (
        isinstance(state.get("current_operation_id"), str)
        and lock.get("owner_operation_id") == state["current_operation_id"]
        and lease is not None
        and lease >= int(now.timestamp())
    )
    grace = owned_transition and (
        desired == "RUNNING"
        and 0 <= age < startup_grace_seconds
        or desired == "STOPPED"
        and 0 <= age < shutdown_grace_seconds
    )
    expected = actual == "running" and not grace
    if not expected:
        reason = "transition" if grace or actual in {"pending", "stopping"} else "ec2-unknown"
        reasons = dict.fromkeys(reasons, reason)
        if reason == "ec2-unknown":
            metrics.pop("DataFilesystemUsageHigh")
        return metrics, reasons

    heartbeat_time = timestamp(heartbeat.get("observed_at"))
    launch = instance.get("LaunchTime")
    current_boot = (
        isinstance(launch, datetime)
        and launch.tzinfo is not None
        and heartbeat_time is not None
        and launch <= heartbeat_time <= now
    )
    heartbeat_fresh = fresh(heartbeat.get("observed_at"), now, HEARTBEAT_STALE_SECONDS)
    if not heartbeat:
        reasons["heartbeat"] = "missing"
    elif not heartbeat_fresh:
        reasons["heartbeat"] = "stale-or-invalid-time"
    elif not current_boot:
        reasons["heartbeat"] = "before-launch-or-unknown-launch"
    else:
        reasons["heartbeat"] = "fresh"
    metrics["RuntimeHeartbeatUnavailable"] = float(reasons["heartbeat"] != "fresh")

    telemetry = observed.get("telemetry")
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    telemetry_fresh = observation_fresh and fresh(
        telemetry.get("observed_at"), now, observation_freshness_seconds
    )
    boot = heartbeat.get("boot_id")
    reference_boot = telemetry.get("boot_id")
    identity_mismatch = bool(heartbeat) and (
        heartbeat.get("system_id") != system_id
        or heartbeat.get("instance_id") != instance.get("InstanceId")
        or heartbeat.get("runtime_id") != "wishicraft-host-runtime"
        or heartbeat.get("active_game_id") not in (None, game_id)
        or not isinstance(boot, str)
        or BOOT_ID.fullmatch(boot) is None
        or telemetry_fresh
        and reference_boot is not None
        and boot != reference_boot
    )
    metrics["RuntimeIdentityMismatch"] = float(identity_mismatch)
    player_count = integer(heartbeat.get("player_count"))
    known_runtime = (
        reasons["heartbeat"] == "fresh"
        and not identity_mismatch
        and integer(heartbeat.get("schema_version")) == 1
        and heartbeat.get("active_game_id") == game_id
        and heartbeat.get("protocol_state") in {"ready", "not-ready"}
        and (
            heartbeat.get("protocol_state") == "not-ready"
            or player_count is not None
            and player_count >= 0
        )
    )
    reasons["runtime"] = str(heartbeat["protocol_state"]) if known_runtime else "unknown"
    metrics["RuntimeObservationUnknown"] = float(not known_runtime)

    total = integer(telemetry.get("total_bytes"))
    used = integer(telemetry.get("used_bytes"))
    available = integer(telemetry.get("available_bytes"))
    source = telemetry.get("source")
    disk_valid = (
        telemetry_fresh
        and integer(telemetry.get("schema_version")) == 1
        and telemetry.get("state") == "observed"
        and telemetry.get("error") is None
        and telemetry.get("mount_path") == mount_path
        and telemetry.get("volume_id") == volume_id
        and telemetry.get("filesystem_uuid") == filesystem_uuid
        and isinstance(source, str)
        and re.fullmatch(r"/dev/nvme[0-9]+n[0-9]+", source) is not None
        and isinstance(reference_boot, str)
        and BOOT_ID.fullmatch(reference_boot) is not None
        and current_boot
        and not identity_mismatch
        and heartbeat_fresh
        and total is not None
        and used is not None
        and available is not None
        and total > 0
        and used >= 0
        and available >= 0
        and 0 < used + available <= total
    )
    reasons["filesystem"] = "observed" if disk_valid else "unknown"
    metrics["DataFilesystemObservationUnknown"] = float(not disk_valid)
    if not disk_valid:
        # Unknown capacity must not publish a false recovery for an existing high alarm.
        metrics.pop("DataFilesystemUsageHigh")
    if disk_valid:
        assert total is not None and used is not None and available is not None
        percent = 100 * used / (used + available)
        metrics.update(
            DataFilesystemUsagePercent=percent,
            DataFilesystemUsedBytes=float(used),
            DataFilesystemAvailableBytes=float(available),
            DataFilesystemTotalBytes=float(total),
            DataFilesystemUsageHigh=float(percent >= usage_warning_percent),
        )
    return metrics, reasons
