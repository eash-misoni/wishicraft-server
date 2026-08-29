"""Phase 6 STOP workflow domain decisions and narrow AWS adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from wishicraft.operation import LeaseProof, LeaseRepository
from wishicraft.system_state import DesiredState, SystemStateRepository


class StopErrorCode(StrEnum):
    PRECONDITION_FAILED = "STOP_PRECONDITION_FAILED"
    SAVE_FAILED = "MINECRAFT_SAVE_FAILED"
    RCON_UNAVAILABLE = "RCON_UNAVAILABLE"
    GRACEFUL_STOP_FAILED = "GRACEFUL_RUNTIME_STOP_FAILED"
    RUNTIME_STOP_TIMEOUT = "MINECRAFT_STOP_TIMEOUT"
    DNS_DELETE_FAILED = "DNS_DELETE_FAILED"
    DNS_INSYNC_TIMEOUT = "DNS_INSYNC_TIMEOUT"
    EC2_STOP_FAILED = "EC2_STOP_FAILED"
    EC2_STOP_TIMEOUT = "EC2_STOP_TIMEOUT"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"


class StopWorkflowError(RuntimeError):
    def __init__(self, code: StopErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class StopObservation:
    ec2_state: str
    ssm_state: str
    host_runtime_state: str
    minecraft_service_state: str
    minecraft_protocol_state: str
    public_ipv4: str | None
    dns_ipv4_values: tuple[str, ...]
    observation_errors: tuple[str, ...] = ()
    discrepancies: tuple[str, ...] = ()
    health: str = "UNKNOWN"

    @classmethod
    def from_item(cls, item: dict[str, object]) -> StopObservation:
        observation = item.get("observation")
        if not isinstance(observation, dict):
            raise StopWorkflowError(StopErrorCode.OBSERVATION_FAILED)
        try:
            dns_values = observation["dns_ipv4_values"]
            errors = item.get("observation_errors", [])
            discrepancies = item.get("discrepancies", [])
            if not isinstance(dns_values, list) or not all(isinstance(v, str) for v in dns_values):
                raise ValueError
            if not isinstance(errors, list) or not all(isinstance(v, str) for v in errors):
                raise ValueError
            if not isinstance(discrepancies, list) or not all(
                isinstance(v, str) for v in discrepancies
            ):
                raise ValueError
            public_ipv4 = observation.get("public_ipv4")
            if public_ipv4 is not None and not isinstance(public_ipv4, str):
                raise ValueError
            return cls(
                ec2_state=_required_string(observation, "ec2_state"),
                ssm_state=_required_string(observation, "ssm_state"),
                host_runtime_state=_required_string(observation, "host_runtime_state"),
                minecraft_service_state=_required_string(observation, "minecraft_service_state"),
                minecraft_protocol_state=_required_string(observation, "minecraft_protocol_state"),
                public_ipv4=public_ipv4,
                dns_ipv4_values=tuple(dns_values),
                observation_errors=tuple(errors),
                discrepancies=tuple(discrepancies),
                health=_required_string(item, "health"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise StopWorkflowError(StopErrorCode.OBSERVATION_FAILED) from error

    @property
    def ec2_stopped(self) -> bool:
        return self.ec2_state == "stopped"

    @property
    def runtime_stopped(self) -> bool:
        return (
            self.host_runtime_state == "not-running"
            and self.minecraft_service_state in {"not-running", "not-applicable"}
            and self.minecraft_protocol_state == "not-applicable"
        )

    def validate_precondition(self) -> bool:
        if self.observation_errors:
            raise StopWorkflowError(StopErrorCode.OBSERVATION_FAILED)
        if self.ec2_stopped:
            return True
        if self.ec2_state != "running" or self.ssm_state != "online":
            raise StopWorkflowError(StopErrorCode.PRECONDITION_FAILED)
        return False

    def ready_for_success(self) -> bool:
        return (
            not self.observation_errors
            and not self.discrepancies
            and self.health == "HEALTHY"
            and self.ec2_stopped
            and self.ssm_state == "not-applicable"
            and self.runtime_stopped
            and self.public_ipv4 is None
            and not self.dns_ipv4_values
        )


class Ec2StopApi(Protocol):
    def stop_instances(self, **kwargs: object) -> object: ...


class Ec2StopAdapter:
    def __init__(self, api: Ec2StopApi) -> None:
        self._api = api

    def stop_if_needed(self, *, instance_id: str, observation: StopObservation) -> bool:
        if observation.ec2_stopped:
            return False
        if observation.ec2_state == "stopping":
            return False
        if observation.ec2_state != "running" or not observation.runtime_stopped:
            raise StopWorkflowError(StopErrorCode.PRECONDITION_FAILED)
        response = self._api.stop_instances(InstanceIds=[instance_id])
        if not isinstance(response, dict) or not isinstance(
            response.get("StoppingInstances"), list
        ):
            raise StopWorkflowError(StopErrorCode.EC2_STOP_FAILED)
        return True


class SsmStopApi(Protocol):
    def send_command(self, **kwargs: object) -> object: ...


class FixedHostStopAdapter:
    """Invoke the fixed save-and-graceful-stop operation without caller command input."""

    COMMAND = "sudo /usr/local/libexec/wishicraft/operation-v1 STOP"

    def __init__(self, api: SsmStopApi, *, timeout_seconds: int) -> None:
        self._api = api
        self._timeout = timeout_seconds

    def stop(self, *, instance_id: str) -> str:
        response = self._api.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [self.COMMAND]},
            TimeoutSeconds=self._timeout,
        )
        command = response.get("Command") if isinstance(response, dict) else None
        command_id = command.get("CommandId") if isinstance(command, dict) else None
        if not isinstance(command_id, str) or not command_id:
            raise StopWorkflowError(StopErrorCode.GRACEFUL_STOP_FAILED)
        return command_id


@dataclass
class StopCoordinator:
    leases: LeaseRepository
    states: SystemStateRepository
    lease_seconds: int

    def verify_and_set_desired(
        self, *, proof: LeaseProof, observation: StopObservation, now: datetime
    ) -> tuple[int, bool]:
        self.leases.verify_owned(proof, now=now)
        already_stopped = observation.validate_precondition()
        snapshot = self.states.desired_snapshot()
        if snapshot.desired_state is DesiredState.STOPPED:
            return snapshot.desired_revision, already_stopped
        revision = self.states.update_desired(
            desired_state=DesiredState.STOPPED,
            desired_game_id=None,
            expected_revision=snapshot.desired_revision,
            operation_id=proof.owner_operation_id,
            updated_at=now,
        )
        return revision, already_stopped

    def renew(self, proof: LeaseProof, *, now: datetime) -> LeaseProof:
        return self.leases.renew(proof, now=now, lease_seconds=self.lease_seconds)


def _required_string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ValueError(name)
    return result
