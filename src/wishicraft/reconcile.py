"""Phase 3 Reconcile orchestration separated from AWS adapters and Lambda."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from wishicraft.endpoint import (
    DnsObservation,
    DnsState,
    derive_endpoint_discrepancies,
)
from wishicraft.status import (
    INSTANCE_ID_PATTERN,
    Ec2State,
    HostRuntimeState,
    MinecraftState,
    PublicIpv4State,
    SsmState,
    TargetStatus,
)
from wishicraft.system_state import DesiredState, Health, SystemState


class TargetEc2Api(Protocol):
    def describe_instances(self, **kwargs: object) -> object: ...


class TargetResolver:
    def __init__(self, api: TargetEc2Api, *, project: str, stage: str) -> None:
        self._api, self._project, self._stage = api, project, stage

    def resolve(self) -> str:
        filters = [
            {"Name": "tag:Project", "Values": [self._project]},
            {"Name": "tag:Stage", "Values": [self._stage]},
            {"Name": "tag:Purpose", "Values": ["phase2-target-validation"]},
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            },
        ]
        ids: list[str] = []
        seen_tokens: set[str] = set()
        next_token: str | None = None
        for _ in range(100):
            request: dict[str, object] = {"Filters": filters}
            if next_token is not None:
                request["NextToken"] = next_token
            response = self._api.describe_instances(**request)
            if not isinstance(response, dict) or not isinstance(response.get("Reservations"), list):
                raise ValueError("target resolution response malformed")
            for raw_reservation in response["Reservations"]:
                if not isinstance(raw_reservation, dict) or not isinstance(
                    raw_reservation.get("Instances"), list
                ):
                    raise ValueError("target resolution response malformed")
                for raw_instance in raw_reservation["Instances"]:
                    if not isinstance(raw_instance, dict):
                        raise ValueError("target resolution response malformed")
                    instance_id = raw_instance.get("InstanceId")
                    if (
                        not isinstance(instance_id, str)
                        or INSTANCE_ID_PATTERN.fullmatch(instance_id) is None
                    ):
                        raise ValueError("target resolution response malformed")
                    ids.append(instance_id)
            raw_token = response.get("NextToken")
            if raw_token is None:
                break
            if not isinstance(raw_token, str) or not raw_token or raw_token in seen_tokens:
                raise ValueError("target resolution pagination malformed")
            seen_tokens.add(raw_token)
            next_token = raw_token
        else:
            raise ValueError("target resolution pagination exceeded limit")
        if len(ids) != 1:
            raise ValueError("target identity is not unique")
        return ids[0]


class StatusFactory(Protocol):
    def create(self, instance_id: str) -> StatusObserver: ...


class StatusObserver(Protocol):
    def observe(self, *, observed_at: datetime) -> TargetStatus: ...


class TargetIdentityResolver(Protocol):
    def resolve(self) -> str: ...


class DnsObserver(Protocol):
    def observe(self) -> DnsObservation: ...


class StateRepository(Protocol):
    def desired_state(self) -> DesiredState: ...
    def save(self, state: SystemState) -> None: ...


@dataclass(frozen=True)
class ReconcileService:
    system_id: str
    environment: str
    game_id: str
    target_resolver: TargetIdentityResolver
    status_factory: StatusFactory
    dns_observer: DnsObserver
    repository: StateRepository

    def reconcile(self, *, observed_at: datetime) -> SystemState:
        desired = self.repository.desired_state()
        dns = self.dns_observer.observe()
        errors: list[str] = []
        target_id: str | None = None
        status: TargetStatus | None = None
        try:
            target_id = self.target_resolver.resolve()
            status = self.status_factory.create(target_id).observe(observed_at=observed_at)
            errors.extend(_observation_errors(status))
        except Exception:  # noqa: BLE001 - observation failure becomes a persisted UNKNOWN state.
            errors.append("TARGET_OBSERVATION_FAILED")
        if dns.state is DnsState.UNKNOWN:
            errors.append("DNS_OBSERVATION_FAILED")
        state = _derive_state(
            system_id=self.system_id,
            environment=self.environment,
            game_id=self.game_id,
            desired=desired,
            target_id=target_id,
            status=status,
            dns=dns,
            errors=tuple(errors),
            observed_at=observed_at,
        )
        self.repository.save(state)
        return state


def _observation_errors(status: TargetStatus) -> list[str]:
    errors: list[str] = []
    if status.ec2_state is Ec2State.UNKNOWN:
        errors.append("EC2_OBSERVATION_FAILED")
    if status.public_ipv4_state is PublicIpv4State.UNKNOWN:
        errors.append("NETWORK_OBSERVATION_FAILED")
    if status.ec2_state is Ec2State.RUNNING and status.ssm_state is SsmState.UNKNOWN:
        errors.append("SSM_OBSERVATION_FAILED")
    if (
        status.ssm_state is SsmState.ONLINE
        and status.host_runtime_state is HostRuntimeState.UNKNOWN
    ):
        errors.append("HOST_RUNTIME_OBSERVATION_FAILED")
    return errors


def _derive_state(
    *,
    system_id: str,
    environment: str,
    game_id: str,
    desired: DesiredState,
    target_id: str | None,
    status: TargetStatus | None,
    dns: DnsObservation,
    errors: tuple[str, ...],
    observed_at: datetime,
) -> SystemState:
    if status is None:
        observation: dict[str, object] = {
            "ec2_state": "unknown",
            "public_ipv4_state": "unknown",
            "public_ipv4": None,
            "private_ipv4": None,
            "ssm_state": "unknown",
            "host_runtime_state": "unknown",
            "minecraft_service_state": "unknown",
            "minecraft_protocol_state": "unknown",
            "runtime_ready": False,
            "active_game_state": "unknown",
            "observed_active_game_id": None,
        }
        base_discrepancies: list[str] = []
    else:
        raw = status.to_dict()
        observation = {key: value for key, value in raw.items() if key != "discrepancies"}
        observation["runtime_ready"] = observation.pop("ready")
        base_discrepancies = [item.value for item in status.discrepancies]
    observation.update(
        {
            "dns_state": dns.state.value,
            "dns_record_name": dns.record_name,
            "dns_ipv4_values": list(dns.ipv4_values),
            "dns_observation_source": dns.source,
        }
    )
    endpoint = (
        derive_endpoint_discrepancies(
            ec2_state=status.ec2_state,
            public_state=status.public_ipv4_state,
            public_ipv4=status.public_ipv4,
            dns=dns,
        )
        if status is not None
        else ()
    )
    discrepancies = tuple(base_discrepancies + [item.value for item in endpoint])
    health = _derive_health(desired, status, discrepancies, errors)
    return SystemState(
        system_id=system_id,
        environment=environment,
        game_id=game_id,
        desired_state=desired,
        target_instance_id=target_id,
        observation=observation,
        discrepancies=discrepancies,
        health=health,
        observation_errors=errors,
        observed_at=observed_at,
    )


def _derive_health(
    desired: DesiredState,
    status: TargetStatus | None,
    discrepancies: tuple[str, ...],
    errors: tuple[str, ...],
) -> Health:
    if status is None or errors:
        return Health.UNKNOWN
    if discrepancies:
        return Health.DEGRADED
    if desired is DesiredState.STOPPED:
        return Health.HEALTHY if status.ec2_state is Ec2State.STOPPED else Health.DEGRADED
    if (
        status.ec2_state is Ec2State.RUNNING
        and status.minecraft_protocol_state is MinecraftState.READY
        and status.ready
    ):
        return Health.HEALTHY
    return Health.DEGRADED
