"""Operator intent, independent of Minecraft Desired and workflow leases."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from wishicraft.monitoring_telemetry import fresh, integer, timestamp

SUPPRESSIBLE = frozenset(
    {"DesiredStoppedEc2Running", "RuntimeObservationUnknown", "DesiredActualDivergence"}
)
# Expiry restores notifications, but only safe closeout reopens admission.
ADMISSION_CONDITION = "(attribute_not_exists(maintenance) OR maintenance.#ms = :maintenance_ended)"


def lease_active(value: object, *, now: datetime) -> bool:
    if not isinstance(value, dict):
        return False
    started, expires = integer(value.get("started_at")), integer(value.get("expires_at"))
    return bool(
        value.get("schema_version") == 1
        and value.get("status") == "ACTIVE"
        and started is not None
        and expires is not None
        and started <= now.timestamp() < expires
        and 0 < expires - started <= 4 * 3600
        and all(isinstance(value.get(k), str) and value[k] for k in ("id", "actor", "reason"))
    )


def new_lease(
    *, lease_id: str, actor: str, reason: str, stage: str, duration: int, now: datetime
) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("maintenance time must be aware")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 60 <= duration <= 14400:
        raise ValueError("maintenance duration must be 60..14400 seconds; no renewal")
    for value in (lease_id, reason, stage):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}", value) is None
        ):
            raise ValueError("invalid maintenance identity/reason/stage")
    if not actor or len(actor) > 512 or any(ord(c) < 32 for c in actor):
        raise ValueError("invalid maintenance actor")
    return {
        "schema_version": 1,
        "id": lease_id,
        "status": "ACTIVE",
        "reason": reason,
        "actor": actor,
        "stage": stage,
        "started_at": int(now.timestamp()),
        "expires_at": int(now.timestamp()) + duration,
    }


def maintenance_metrics(
    *,
    state: dict[str, Any],
    lock: dict[str, Any],
    instance: dict[str, Any],
    now: datetime,
    freshness_seconds: int,
) -> dict[str, float]:
    active = lease_active(state.get("maintenance"), now=now)
    observed = state.get("observation", {})
    observed = observed if isinstance(observed, dict) else {}
    actual = instance.get("State", {}).get("Name")
    healthy_control = (
        active
        and state.get("desired_state") == "STOPPED"
        and state.get("current_operation_id") is None
        and not lock
        and fresh(state.get("observed_at"), now, freshness_seconds)
        and state.get("target_instance_id") == instance.get("InstanceId")
        and observed.get("instance_id") == instance.get("InstanceId")
        and observed.get("dns_state") == "absent"
        and observed.get("runtime_ready") is False
        and observed.get("observed_active_game_id") is None
        and state.get("observation_errors") == []
    )
    stopped = (
        actual == "stopped"
        and observed.get("ec2_state") == "stopped"
        and state.get("health") == "HEALTHY"
        and state.get("discrepancies") == []
    )
    launch = instance.get("LaunchTime")
    observed_at = timestamp(state.get("observed_at"))
    running = (
        actual == "running"
        and observed.get("ec2_state") == "running"
        and isinstance(launch, datetime)
        and launch.tzinfo is not None
        and observed_at is not None
        and launch <= observed_at <= now
        and observed.get("ssm_state") == "online"
        and observed.get("docker_state") == "active"
        and observed.get("mount_state") == "expected"
        and observed.get("container_state") == "not-found"
        and observed.get("host_runtime_state") == "not-running"
        and observed.get("minecraft_service_state") == "not-running"
        and observed.get("minecraft_protocol_state") == "not-applicable"
        and state.get("health") == "DEGRADED"
        and state.get("discrepancies") == ["dns-missing-when-required"]
    )
    return {
        "MaintenanceActive": float(active),
        "MaintenanceSuppressionEligible": float(bool(healthy_control and (stopped or running))),
        "MaintenanceExpiresAt": float(state["maintenance"]["expires_at"]) if active else 0.0,
    }


def admission_check(*, table: str, system_id: str) -> dict[str, Any]:
    return {
        "ConditionCheck": {
            "TableName": table,
            "Key": {"system_id": {"S": system_id}},
            "ConditionExpression": "attribute_exists(system_id) AND " + ADMISSION_CONDITION,
            "ExpressionAttributeNames": {"#ms": "status"},
            "ExpressionAttributeValues": {":maintenance_ended": {"S": "ENDED"}},
        }
    }
