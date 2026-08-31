"""Safe user-facing projection of a freshly reconciled SystemState."""

from __future__ import annotations

import re
from enum import StrEnum


class ProjectedStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    ONLINE = "online"
    STOPPING = "stopping"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


def project_status(state: object) -> dict[str, object]:
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("invalid reconciled SystemState")
    desired = _string(state, "desired_state")
    health = _string(state, "health")
    observed_at = _string(state, "observed_at")
    observation = state.get("observation")
    discrepancies = state.get("discrepancies")
    errors = state.get("observation_errors")
    if (
        desired not in {"RUNNING", "STOPPED"}
        or health not in {"HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"}
        or not isinstance(observation, dict)
        or not isinstance(discrepancies, list)
        or not all(isinstance(item, str) for item in discrepancies)
        or not isinstance(errors, list)
        or not all(isinstance(item, str) for item in errors)
    ):
        raise ValueError("invalid reconciled SystemState")
    ec2 = _string(observation, "ec2_state")
    ready = observation.get("runtime_ready")
    dns = _string(observation, "dns_state")
    endpoint = observation.get("dns_record_name")
    if (
        not isinstance(ready, bool)
        or not isinstance(endpoint, str)
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\.?", endpoint) is None
    ):
        raise ValueError("invalid reconciled SystemState")

    status = _derive_status(desired=desired, health=health, ec2=ec2, ready=ready)
    usable_endpoint = (
        endpoint.rstrip(".") if status is ProjectedStatus.ONLINE and dns == "present" else None
    )
    return {
        "schema_version": 1,
        "kind": "STATUS",
        "status": status.value,
        "ready": status is ProjectedStatus.ONLINE,
        "health": health.lower(),
        "endpoint": usable_endpoint,
        "observed_at": observed_at,
        "summary": _summary(status),
    }


def unavailable_projection() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "STATUS",
        "status": ProjectedStatus.UNKNOWN.value,
        "ready": False,
        "health": "unknown",
        "endpoint": None,
        "observed_at": None,
        "summary": "Current server state could not be observed.",
    }


def _derive_status(*, desired: str, health: str, ec2: str, ready: bool) -> ProjectedStatus:
    if health == "UNKNOWN" or ec2 == "unknown":
        return ProjectedStatus.UNKNOWN
    if desired == "STOPPED" and ec2 in {"stopping", "shutting-down", "running", "pending"}:
        return ProjectedStatus.STOPPING
    if desired == "RUNNING" and ec2 in {"pending", "stopped", "stopping"}:
        return ProjectedStatus.STARTING
    if health in {"DEGRADED", "UNHEALTHY"}:
        return ProjectedStatus.DEGRADED
    if desired == "STOPPED" and ec2 in {"stopped", "terminated"}:
        return ProjectedStatus.STOPPED
    if desired == "RUNNING" and ec2 == "running" and ready:
        return ProjectedStatus.ONLINE
    return ProjectedStatus.DEGRADED


def _summary(status: ProjectedStatus) -> str:
    return {
        ProjectedStatus.STOPPED: "The server is stopped.",
        ProjectedStatus.STARTING: "The server is converging toward running.",
        ProjectedStatus.ONLINE: "The server is online and ready.",
        ProjectedStatus.STOPPING: "The server is converging toward stopped.",
        ProjectedStatus.DEGRADED: "The server state is degraded or not converged.",
        ProjectedStatus.UNKNOWN: "Current server state could not be observed.",
    }[status]


def _string(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError("invalid reconciled SystemState")
    return item
