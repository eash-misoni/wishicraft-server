"""Fail-closed observation of the Phase 2 target host."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-f]{17}$")


class Ec2State(StrEnum):
    """Canonical EC2 states used by Reconcile."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SHUTTING_DOWN = "shutting-down"
    TERMINATED = "terminated"
    UNKNOWN = "unknown"


class SsmState(StrEnum):
    """Canonical SSM managed-node states."""

    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


class HostRuntimeState(StrEnum):
    """Host Runtime state at the current observation depth."""

    NOT_RUNNING = "not-running"
    RUNNING = "running"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class MinecraftState(StrEnum):
    """Minecraft state at the current observation depth."""

    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


class Ec2Api(Protocol):
    """Narrow EC2 API boundary used by the first status slice."""

    def describe_instances(self, *, InstanceIds: list[str]) -> object: ...


@dataclass(frozen=True)
class TargetStatus:
    """Canonical structured observation returned by the status slice."""

    instance_id: str
    ec2_state: Ec2State
    ssm_state: SsmState
    host_runtime_state: HostRuntimeState
    minecraft_service_state: MinecraftState
    minecraft_protocol_state: MinecraftState
    ready: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-compatible representation."""
        observed_at = self.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return {
            "schema_version": 1,
            "instance_id": self.instance_id,
            "ec2_state": self.ec2_state.value,
            "ssm_state": self.ssm_state.value,
            "host_runtime_state": self.host_runtime_state.value,
            "minecraft_service_state": self.minecraft_service_state.value,
            "minecraft_protocol_state": self.minecraft_protocol_state.value,
            "ready": self.ready,
            "observed_at": observed_at,
        }


class TargetStatusObserver:
    """Observe the target EC2 and stop before unreachable lower layers."""

    def __init__(self, *, instance_id: str, ec2: Ec2Api) -> None:
        if INSTANCE_ID_PATTERN.fullmatch(instance_id) is None:
            raise ValueError("invalid target EC2 instance ID")
        self._instance_id = instance_id
        self._ec2 = ec2

    def observe(self, *, observed_at: datetime) -> TargetStatus:
        """Return UNKNOWN on API/schema failure; never infer STOPPED."""
        try:
            response = self._ec2.describe_instances(InstanceIds=[self._instance_id])
            ec2_state = _parse_ec2_state(response, self._instance_id)
        except Exception:  # noqa: BLE001 - AWS boundary is normalized without exposing details.
            ec2_state = Ec2State.UNKNOWN

        if ec2_state in {Ec2State.STOPPED, Ec2State.TERMINATED}:
            return TargetStatus(
                instance_id=self._instance_id,
                ec2_state=ec2_state,
                ssm_state=SsmState.NOT_APPLICABLE,
                host_runtime_state=HostRuntimeState.NOT_RUNNING,
                minecraft_service_state=MinecraftState.NOT_APPLICABLE,
                minecraft_protocol_state=MinecraftState.NOT_APPLICABLE,
                ready=False,
                observed_at=observed_at,
            )

        return TargetStatus(
            instance_id=self._instance_id,
            ec2_state=ec2_state,
            ssm_state=SsmState.UNKNOWN,
            host_runtime_state=HostRuntimeState.UNKNOWN,
            minecraft_service_state=MinecraftState.UNKNOWN,
            minecraft_protocol_state=MinecraftState.UNKNOWN,
            ready=False,
            observed_at=observed_at,
        )


def _parse_ec2_state(response: object, expected_instance_id: str) -> Ec2State:
    if not isinstance(response, dict):
        return Ec2State.UNKNOWN
    reservations = response.get("Reservations")
    if not isinstance(reservations, list):
        return Ec2State.UNKNOWN

    matched_states: list[str] = []
    for raw_reservation in reservations:
        if not isinstance(raw_reservation, dict):
            continue
        reservation = cast(dict[object, object], raw_reservation)
        instances = reservation.get("Instances")
        if not isinstance(instances, list):
            continue
        for raw_instance in instances:
            if not isinstance(raw_instance, dict):
                continue
            instance = cast(dict[object, object], raw_instance)
            if instance.get("InstanceId") != expected_instance_id:
                continue
            state = instance.get("State")
            if isinstance(state, dict) and isinstance(state.get("Name"), str):
                matched_states.append(state["Name"])

    if len(matched_states) != 1:
        return Ec2State.UNKNOWN
    try:
        return Ec2State(matched_states[0])
    except ValueError:
        return Ec2State.UNKNOWN
