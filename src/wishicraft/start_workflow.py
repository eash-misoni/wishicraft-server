"""Phase 5 START workflow domain decisions and narrow AWS adapters."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from wishicraft.operation import LeaseProof, LeaseRepository
from wishicraft.system_state import DesiredState, SystemStateRepository


class StartErrorCode(StrEnum):
    PRECONDITION_FAILED = "START_PRECONDITION_FAILED"
    ACTIVE_GAME_MISMATCH = "ACTIVE_GAME_MISMATCH"
    EC2_START_FAILED = "EC2_START_FAILED"
    SSM_TIMEOUT = "SSM_TIMEOUT"
    HOST_RUNTIME_FAILED = "HOST_RUNTIME_FAILED"
    READY_TIMEOUT = "MINECRAFT_READY_TIMEOUT"
    ENDPOINT_DISCREPANCY = "ENDPOINT_DISCREPANCY"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"


class StartWorkflowError(RuntimeError):
    def __init__(self, code: StartErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class StartObservation:
    ec2_state: str
    ssm_state: str
    runtime_ready: bool
    observed_active_game_id: str | None
    public_ipv4: str | None
    dns_ipv4_values: tuple[str, ...]
    observation_errors: tuple[str, ...] = ()

    @classmethod
    def from_item(cls, item: dict[str, object]) -> StartObservation:
        observation = item.get("observation")
        if not isinstance(observation, dict):
            raise StartWorkflowError(StartErrorCode.OBSERVATION_FAILED)
        try:
            dns_values = observation["dns_ipv4_values"]
            if not isinstance(dns_values, list) or not all(isinstance(v, str) for v in dns_values):
                raise ValueError
            errors = item.get("observation_errors", [])
            if not isinstance(errors, list) or not all(isinstance(v, str) for v in errors):
                raise ValueError
            public_ipv4 = observation.get("public_ipv4")
            active_game = observation.get("observed_active_game_id")
            if public_ipv4 is not None:
                ipaddress.IPv4Address(public_ipv4)
            if active_game is not None and not isinstance(active_game, str):
                raise ValueError
            return cls(
                ec2_state=_required_string(observation, "ec2_state"),
                ssm_state=_required_string(observation, "ssm_state"),
                runtime_ready=observation.get("runtime_ready") is True,
                observed_active_game_id=active_game,
                public_ipv4=public_ipv4,
                dns_ipv4_values=tuple(dns_values),
                observation_errors=tuple(errors),
            )
        except (KeyError, ValueError, TypeError) as error:
            raise StartWorkflowError(StartErrorCode.OBSERVATION_FAILED) from error

    def validate_precondition(self, expected_game_id: str) -> bool:
        if self.observation_errors:
            raise StartWorkflowError(StartErrorCode.OBSERVATION_FAILED)
        if self.runtime_ready and self.observed_active_game_id != expected_game_id:
            raise StartWorkflowError(StartErrorCode.ACTIVE_GAME_MISMATCH)
        return self.runtime_ready and self.observed_active_game_id == expected_game_id

    def ready_for_success(self, expected_game_id: str) -> bool:
        return (
            not self.observation_errors
            and self.ec2_state == "running"
            and self.ssm_state == "online"
            and self.runtime_ready
            and self.observed_active_game_id == expected_game_id
            and self.public_ipv4 is not None
            and self.dns_ipv4_values == (self.public_ipv4,)
        )


class Ec2LifecycleApi(Protocol):
    def start_instances(self, **kwargs: object) -> object: ...


class Ec2LifecycleAdapter:
    def __init__(self, api: Ec2LifecycleApi) -> None:
        self._api = api

    def start_if_needed(self, *, instance_id: str, current_state: str) -> bool:
        if current_state in {"running", "pending"}:
            return False
        if current_state != "stopped":
            raise StartWorkflowError(StartErrorCode.PRECONDITION_FAILED)
        response = self._api.start_instances(InstanceIds=[instance_id])
        if not isinstance(response, dict) or not isinstance(
            response.get("StartingInstances"), list
        ):
            raise StartWorkflowError(StartErrorCode.EC2_START_FAILED)
        return True


class SsmStartApi(Protocol):
    def send_command(self, **kwargs: object) -> object: ...


class FixedHostStartAdapter:
    """Invoke one fixed, versioned host-local START operation; no caller shell input."""

    COMMAND = "sudo /usr/local/libexec/wishicraft/operation-v1 START"

    def __init__(self, api: SsmStartApi, *, timeout_seconds: int) -> None:
        self._api = api
        self._timeout = timeout_seconds

    def start(self, *, instance_id: str) -> str:
        response = self._api.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [self.COMMAND]},
            TimeoutSeconds=self._timeout,
        )
        command = response.get("Command") if isinstance(response, dict) else None
        command_id = command.get("CommandId") if isinstance(command, dict) else None
        if not isinstance(command_id, str) or not command_id:
            raise StartWorkflowError(StartErrorCode.HOST_RUNTIME_FAILED)
        return command_id


@dataclass
class StartCoordinator:
    leases: LeaseRepository
    states: SystemStateRepository
    lease_seconds: int

    def verify_and_set_desired(
        self,
        *,
        proof: LeaseProof,
        observation: StartObservation,
        game_id: str,
        now: datetime,
    ) -> tuple[int, bool]:
        self.leases.verify_owned(proof, now=now)
        already_ready = observation.validate_precondition(game_id)
        snapshot = self.states.desired_snapshot()
        if snapshot.desired_state is DesiredState.RUNNING and snapshot.desired_game_id not in {
            None,
            game_id,
        }:
            raise StartWorkflowError(StartErrorCode.ACTIVE_GAME_MISMATCH)
        if snapshot.desired_state is DesiredState.RUNNING and snapshot.desired_game_id == game_id:
            return snapshot.desired_revision, already_ready
        revision = self.states.update_desired(
            desired_state=DesiredState.RUNNING,
            desired_game_id=game_id,
            expected_revision=snapshot.desired_revision,
            operation_id=proof.owner_operation_id,
            updated_at=now,
        )
        return revision, already_ready

    def renew(self, proof: LeaseProof, *, now: datetime) -> LeaseProof:
        return self.leases.renew(proof, now=now, lease_seconds=self.lease_seconds)


def _required_string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str):
        raise ValueError(name)
    return result
