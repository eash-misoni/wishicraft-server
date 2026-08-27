"""Fail-closed observation of the Phase 2 target host."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from wishicraft.probe import (
    ContainerState,
    DockerState,
    HostRuntimeProbe,
    MountState,
    UnitState,
    parse_host_runtime_probe,
)

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

    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTION_LOST = "connection-lost"
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

    NOT_RUNNING = "not-running"
    NOT_APPLICABLE = "not-applicable"
    UNKNOWN = "unknown"


class Ec2Api(Protocol):
    """Narrow EC2 API boundary used by the first status slice."""

    def describe_instances(self, *, InstanceIds: list[str]) -> object: ...


class SsmApi(Protocol):
    """Narrow SSM API boundary used to observe one managed node."""

    def describe_instance_information(self, **kwargs: object) -> object: ...


class ProbeOutput(Protocol):
    stdout: str


class HostRuntimeProbeApi(Protocol):
    """Fixed-operation boundary; callers cannot provide a shell command."""

    def run_probe(self, *, instance_id: str) -> ProbeOutput: ...


@dataclass(frozen=True)
class TargetStatus:
    """Canonical structured observation returned by the status slice."""

    instance_id: str
    ec2_state: Ec2State
    ssm_state: SsmState
    mount_state: MountState
    docker_state: DockerState
    host_runtime_state: HostRuntimeState
    container_state: ContainerState
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
            "mount_state": self.mount_state.value,
            "docker_state": self.docker_state.value,
            "host_runtime_state": self.host_runtime_state.value,
            "container_state": self.container_state.value,
            "minecraft_service_state": self.minecraft_service_state.value,
            "minecraft_protocol_state": self.minecraft_protocol_state.value,
            "ready": self.ready,
            "observed_at": observed_at,
        }


class TargetStatusObserver:
    """Observe the target EC2 and stop before unreachable lower layers."""

    def __init__(
        self,
        *,
        instance_id: str,
        ec2: Ec2Api,
        ssm: SsmApi,
        host_runtime_probe: HostRuntimeProbeApi,
    ) -> None:
        if INSTANCE_ID_PATTERN.fullmatch(instance_id) is None:
            raise ValueError("invalid target EC2 instance ID")
        self._instance_id = instance_id
        self._ec2 = ec2
        self._ssm = ssm
        self._host_runtime_probe = host_runtime_probe

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
                mount_state=MountState.UNKNOWN,
                docker_state=DockerState.UNKNOWN,
                host_runtime_state=HostRuntimeState.NOT_RUNNING,
                container_state=ContainerState.UNKNOWN,
                minecraft_service_state=MinecraftState.NOT_APPLICABLE,
                minecraft_protocol_state=MinecraftState.NOT_APPLICABLE,
                ready=False,
                observed_at=observed_at,
            )

        ssm_state = SsmState.UNKNOWN
        if ec2_state is Ec2State.RUNNING:
            try:
                ssm_state = _observe_ssm_state(self._ssm, self._instance_id)
            except Exception:  # noqa: BLE001 - AWS boundary is normalized without details.
                ssm_state = SsmState.UNKNOWN

        if ssm_state is SsmState.ONLINE:
            try:
                transport = self._host_runtime_probe.run_probe(instance_id=self._instance_id)
                probe = parse_host_runtime_probe(
                    transport.stdout, expected_instance_id=self._instance_id
                )
                return _status_from_probe(
                    instance_id=self._instance_id,
                    ec2_state=ec2_state,
                    ssm_state=ssm_state,
                    probe=probe,
                    observed_at=observed_at,
                )
            except Exception:  # noqa: BLE001 - transport/parser failures are fail-closed.
                pass

        return TargetStatus(
            instance_id=self._instance_id,
            ec2_state=ec2_state,
            ssm_state=ssm_state,
            mount_state=MountState.UNKNOWN,
            docker_state=DockerState.UNKNOWN,
            host_runtime_state=HostRuntimeState.UNKNOWN,
            container_state=ContainerState.UNKNOWN,
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


def _observe_ssm_state(ssm: SsmApi, expected_instance_id: str) -> SsmState:
    matched_statuses: list[str] = []
    seen_tokens: set[str] = set()
    next_token: str | None = None
    for _ in range(100):
        request: dict[str, object] = {
            "Filters": [{"Key": "InstanceIds", "Values": [expected_instance_id]}]
        }
        if next_token is not None:
            request["NextToken"] = next_token
        response = ssm.describe_instance_information(**request)
        if not isinstance(response, dict):
            return SsmState.UNKNOWN
        information_list = response.get("InstanceInformationList")
        if not isinstance(information_list, list):
            return SsmState.UNKNOWN
        for raw_information in information_list:
            if not isinstance(raw_information, dict):
                return SsmState.UNKNOWN
            information = cast(dict[object, object], raw_information)
            instance_id = information.get("InstanceId")
            ping_status = information.get("PingStatus")
            if not isinstance(instance_id, str) or not isinstance(ping_status, str):
                return SsmState.UNKNOWN
            if instance_id == expected_instance_id:
                matched_statuses.append(ping_status)
        raw_token = response.get("NextToken")
        if raw_token is None:
            break
        if not isinstance(raw_token, str) or not raw_token or raw_token in seen_tokens:
            return SsmState.UNKNOWN
        seen_tokens.add(raw_token)
        next_token = raw_token
    else:
        return SsmState.UNKNOWN

    if len(matched_statuses) != 1:
        return SsmState.UNKNOWN
    return {
        "Online": SsmState.ONLINE,
        "Inactive": SsmState.OFFLINE,
        "ConnectionLost": SsmState.CONNECTION_LOST,
    }.get(matched_statuses[0], SsmState.UNKNOWN)


def _status_from_probe(
    *,
    instance_id: str,
    ec2_state: Ec2State,
    ssm_state: SsmState,
    probe: HostRuntimeProbe,
    observed_at: datetime,
) -> TargetStatus:
    host_runtime_state = _normalize_host_runtime(probe)
    minecraft_state = (
        MinecraftState.NOT_RUNNING
        if probe.minecraft_runtime_state == "not-running"
        else MinecraftState.UNKNOWN
    )
    protocol_state = (
        MinecraftState.NOT_APPLICABLE
        if probe.protocol_state == "not-applicable"
        else MinecraftState.UNKNOWN
    )
    return TargetStatus(
        instance_id=instance_id,
        ec2_state=ec2_state,
        ssm_state=ssm_state,
        mount_state=probe.mount.state,
        docker_state=probe.docker_state,
        host_runtime_state=host_runtime_state,
        container_state=probe.container.state,
        minecraft_service_state=minecraft_state,
        minecraft_protocol_state=protocol_state,
        ready=False,
        observed_at=observed_at,
    )


def _normalize_host_runtime(probe: HostRuntimeProbe) -> HostRuntimeState:
    if probe.errors:
        return HostRuntimeState.UNKNOWN
    if probe.mount.state is not MountState.EXPECTED or probe.docker_state is not DockerState.ACTIVE:
        return HostRuntimeState.DEGRADED
    if probe.host_runtime_state in {
        UnitState.INACTIVE,
        UnitState.NOT_FOUND,
    } and probe.container.state in {ContainerState.STOPPED, ContainerState.NOT_FOUND}:
        return HostRuntimeState.NOT_RUNNING
    if (
        probe.host_runtime_state is UnitState.ACTIVE
        and probe.container.state is ContainerState.RUNNING
    ):
        return HostRuntimeState.RUNNING
    if (
        probe.host_runtime_state is UnitState.UNKNOWN
        or probe.container.state is ContainerState.UNKNOWN
    ):
        return HostRuntimeState.UNKNOWN
    return HostRuntimeState.DEGRADED
