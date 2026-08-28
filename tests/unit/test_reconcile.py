from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wishicraft.endpoint import DnsObservation, DnsState
from wishicraft.probe import ActiveGameState, ContainerState, DockerState, MountState
from wishicraft.reconcile import ReconcileService, TargetResolver
from wishicraft.status import (
    Discrepancy,
    Ec2State,
    HostRuntimeState,
    MinecraftState,
    PublicIpv4State,
    SsmState,
    TargetStatus,
)
from wishicraft.system_state import DesiredState, Health, SystemState

NOW = datetime(2026, 8, 28, 1, 2, 3, tzinfo=UTC)


def target_status(
    *,
    ec2: Ec2State = Ec2State.STOPPED,
    public_state: PublicIpv4State = PublicIpv4State.ABSENT,
    public_ip: str | None = None,
    ready: bool = False,
    game_id: str | None = None,
    discrepancies: tuple[Discrepancy, ...] = (),
    ssm: SsmState | None = None,
) -> TargetStatus:
    running = ec2 is Ec2State.RUNNING
    return TargetStatus(
        instance_id="i-04fc0629dc4ea466e",
        ec2_state=ec2,
        public_ipv4_state=public_state,
        public_ipv4=public_ip,
        private_ipv4="10.0.0.8",
        network_observation_source="ec2-describe-instances",
        ssm_state=ssm
        if ssm is not None
        else SsmState.ONLINE
        if running
        else SsmState.NOT_APPLICABLE,
        mount_state=MountState.EXPECTED if running else MountState.UNKNOWN,
        docker_state=DockerState.ACTIVE if running else DockerState.UNKNOWN,
        host_runtime_state=HostRuntimeState.RUNNING if running else HostRuntimeState.NOT_RUNNING,
        container_state=ContainerState.RUNNING if running else ContainerState.UNKNOWN,
        minecraft_service_state=MinecraftState.RUNNING
        if running
        else MinecraftState.NOT_APPLICABLE,
        minecraft_protocol_state=MinecraftState.READY if ready else MinecraftState.NOT_APPLICABLE,
        expected_game_id="game-vanilla-main",
        active_game_state=ActiveGameState.OBSERVED if running else ActiveGameState.NOT_APPLICABLE,
        observed_active_game_id=game_id,
        player_count=0 if ready else None,
        discrepancies=discrepancies,
        ready=ready,
        observed_at=NOW,
    )


class Resolver:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def resolve(self) -> str:
        if self.fail:
            raise RuntimeError("resolution failed")
        return "i-04fc0629dc4ea466e"


class Observer:
    def __init__(self, status: TargetStatus) -> None:
        self.status = status

    def observe(self, *, observed_at: datetime) -> TargetStatus:
        return self.status


class Factory:
    def __init__(self, status: TargetStatus) -> None:
        self.status = status

    def create(self, instance_id: str) -> Observer:
        return Observer(self.status)


class Dns:
    def __init__(self, observation: DnsObservation) -> None:
        self.observation = observation

    def observe(self) -> DnsObservation:
        return self.observation


class Repository:
    def __init__(self, desired: DesiredState = DesiredState.STOPPED) -> None:
        self.desired = desired
        self.saved: list[SystemState] = []

    def desired_state(self) -> DesiredState:
        return self.desired

    def save(self, state: SystemState) -> None:
        self.saved.append(state)


def service(status: TargetStatus, dns: DnsObservation, repo: Repository) -> ReconcileService:
    return ReconcileService(
        system_id="wishicraft-main",
        environment="dev",
        game_id="game-vanilla-main",
        target_resolver=Resolver(),
        status_factory=Factory(status),
        dns_observer=Dns(dns),
        repository=repo,
    )


def test_stopped_target_and_absent_dns_is_healthy() -> None:
    repo = Repository()
    result = service(
        target_status(), DnsObservation("mc-dev.example.", DnsState.ABSENT, ()), repo
    ).reconcile(observed_at=NOW)
    assert result.health is Health.HEALTHY
    assert result.discrepancies == ()
    assert result.observation["player_count"] is None
    assert result.observation["runtime_ready"] is False
    assert repo.saved == [result]


def test_running_ssm_offline_is_persisted_not_ready() -> None:
    result = service(
        target_status(ec2=Ec2State.RUNNING, ssm=SsmState.OFFLINE),
        DnsObservation("mc-dev.example.", DnsState.ABSENT, ()),
        Repository(DesiredState.RUNNING),
    ).reconcile(observed_at=NOW)
    assert result.observation["ssm_state"] == "offline"
    assert result.observation["runtime_ready"] is False
    assert result.health is Health.DEGRADED


def test_runtime_ready_game_match_and_endpoint_match_is_healthy() -> None:
    repo = Repository(DesiredState.RUNNING)
    result = service(
        target_status(
            ec2=Ec2State.RUNNING,
            public_state=PublicIpv4State.ASSIGNED,
            public_ip="203.0.113.8",
            ready=True,
            game_id="game-vanilla-main",
        ),
        DnsObservation("mc-dev.example.", DnsState.PRESENT, ("203.0.113.8",)),
        repo,
    ).reconcile(observed_at=NOW)
    assert result.health is Health.HEALTHY
    assert result.discrepancies == ()
    assert result.observation["player_count"] == 0


def test_runtime_ready_game_mismatch_remains_ready_but_degraded() -> None:
    repo = Repository(DesiredState.RUNNING)
    result = service(
        target_status(
            ec2=Ec2State.RUNNING,
            public_state=PublicIpv4State.ASSIGNED,
            public_ip="203.0.113.8",
            ready=True,
            game_id="game-fabric-test",
            discrepancies=(Discrepancy.ACTIVE_GAME_MISMATCH,),
        ),
        DnsObservation("mc-dev.example.", DnsState.PRESENT, ("203.0.113.8",)),
        repo,
    ).reconcile(observed_at=NOW)
    assert result.observation["runtime_ready"] is True
    assert result.health is Health.DEGRADED
    assert "active-game-mismatch" in result.discrepancies


def test_endpoint_mismatch_is_derived_separately() -> None:
    result = service(
        target_status(
            ec2=Ec2State.RUNNING,
            public_state=PublicIpv4State.ASSIGNED,
            public_ip="203.0.113.8",
        ),
        DnsObservation("mc-dev.example.", DnsState.PRESENT, ("203.0.113.9",)),
        Repository(DesiredState.RUNNING),
    ).reconcile(observed_at=NOW)
    assert "dns-points-to-wrong-ipv4" in result.discrepancies


def test_adapter_failure_persists_fresh_unknown_instead_of_old_ready() -> None:
    repo = Repository(DesiredState.RUNNING)
    reconcile = ReconcileService(
        system_id="wishicraft-main",
        environment="dev",
        game_id="game-vanilla-main",
        target_resolver=Resolver(fail=True),
        status_factory=Factory(target_status(ready=True)),
        dns_observer=Dns(DnsObservation("mc-dev.example.", DnsState.UNKNOWN, ())),
        repository=repo,
    )
    result = reconcile.reconcile(observed_at=NOW)
    assert result.observation["ec2_state"] == "unknown"
    assert result.observation["runtime_ready"] is False
    assert result.health is Health.UNKNOWN
    assert result.observation_errors == ("TARGET_OBSERVATION_FAILED", "DNS_OBSERVATION_FAILED")
    assert repo.saved == [result]


def test_new_unknown_observation_replaces_previous_ready_current_state() -> None:
    class CurrentRepository(Repository):
        def __init__(self) -> None:
            super().__init__(DesiredState.RUNNING)
            self.current = SystemState(
                system_id="wishicraft-main",
                environment="dev",
                game_id="game-vanilla-main",
                desired_state=DesiredState.RUNNING,
                target_instance_id="i-04fc0629dc4ea466e",
                observation={"ec2_state": "running", "runtime_ready": True},
                discrepancies=(),
                health=Health.HEALTHY,
                observation_errors=(),
                observed_at=datetime(2026, 8, 28, 1, 2, 2, tzinfo=UTC),
            )

        def save(self, state: SystemState) -> None:
            self.current = state

    repo = CurrentRepository()
    reconcile = ReconcileService(
        system_id="wishicraft-main",
        environment="dev",
        game_id="game-vanilla-main",
        target_resolver=Resolver(fail=True),
        status_factory=Factory(target_status(ready=True)),
        dns_observer=Dns(DnsObservation("mc-dev.example.", DnsState.ABSENT, ())),
        repository=repo,
    )

    result = reconcile.reconcile(observed_at=NOW)

    assert repo.current is result
    assert repo.current.observation["ec2_state"] == "unknown"
    assert repo.current.observation["runtime_ready"] is False
    assert repo.current.health is Health.UNKNOWN


def test_target_identity_resolves_exactly_one_tagged_instance() -> None:
    class Ec2:
        def describe_instances(self, **kwargs: object) -> object:
            return {"Reservations": [{"Instances": [{"InstanceId": "i-04fc0629dc4ea466e"}]}]}

    assert TargetResolver(Ec2(), project="wishicraft", stage="dev").resolve() == (
        "i-04fc0629dc4ea466e"
    )


def test_target_identity_rejects_zero_or_duplicate_matches() -> None:
    class Ec2:
        def __init__(self, instances: list[dict[str, object]]) -> None:
            self.instances = instances

        def describe_instances(self, **kwargs: object) -> object:
            return {"Reservations": [{"Instances": self.instances}]}

    cases: tuple[list[dict[str, object]], ...] = (
        [],
        [{"InstanceId": "i-04fc0629dc4ea466e"}, {"InstanceId": "i-00000000000000000"}],
    )
    for instances in cases:
        try:
            TargetResolver(Ec2(instances), project="wishicraft", stage="dev").resolve()
        except ValueError:
            pass
        else:
            raise AssertionError("ambiguous target identity must fail closed")


def test_target_identity_paginates_and_finds_second_page() -> None:
    class Ec2:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def describe_instances(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            if kwargs.get("NextToken") == "page-2":
                return {"Reservations": [{"Instances": [{"InstanceId": "i-04fc0629dc4ea466e"}]}]}
            return {"Reservations": [], "NextToken": "page-2"}

    api = Ec2()
    assert TargetResolver(api, project="wishicraft", stage="dev").resolve() == (
        "i-04fc0629dc4ea466e"
    )
    assert api.calls[1]["NextToken"] == "page-2"


def test_target_identity_rejects_duplicate_across_pages_and_token_loop() -> None:
    instance = {"Instances": [{"InstanceId": "i-04fc0629dc4ea466e"}]}

    class Duplicate:
        def describe_instances(self, **kwargs: object) -> object:
            if kwargs.get("NextToken") == "page-2":
                return {"Reservations": [instance]}
            return {"Reservations": [instance], "NextToken": "page-2"}

    class Loop:
        def describe_instances(self, **kwargs: object) -> object:
            return {"Reservations": [], "NextToken": "loop"}

    for api in (Duplicate(), Loop()):
        with pytest.raises(ValueError):
            TargetResolver(api, project="wishicraft", stage="dev").resolve()
