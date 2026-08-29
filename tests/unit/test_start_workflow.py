from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wishicraft.operation import LeaseProof
from wishicraft.start_workflow import (
    Ec2LifecycleAdapter,
    FixedHostStartAdapter,
    StartCoordinator,
    StartErrorCode,
    StartObservation,
    StartWorkflowError,
)
from wishicraft.system_state import DesiredState, DesiredStateSnapshot


class FakeEc2:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def start_instances(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class FakeSsm:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_command(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {"Command": {"CommandId": "command-1"}}


class FakeLeases:
    def __init__(self) -> None:
        self.verified = 0

    def verify_owned(self, proof: LeaseProof, *, now: datetime) -> None:
        del proof, now
        self.verified += 1


class FakeStates:
    def __init__(self, snapshot: DesiredStateSnapshot) -> None:
        self.snapshot = snapshot
        self.updates: list[dict[str, object]] = []

    def desired_snapshot(self) -> DesiredStateSnapshot:
        return self.snapshot

    def update_desired(self, **kwargs: object) -> int:
        self.updates.append(kwargs)
        return self.snapshot.desired_revision + 1


def _observation(**overrides: object) -> StartObservation:
    values: dict[str, object] = {
        "ec2_state": "running",
        "ssm_state": "online",
        "runtime_ready": True,
        "observed_active_game_id": "game-vanilla-main",
        "public_ipv4": "203.0.113.10",
        "dns_ipv4_values": ("203.0.113.10",),
    }
    values.update(overrides)
    return StartObservation(**values)  # type: ignore[arg-type]


def test_start_success_requires_runtime_game_and_endpoint_convergence() -> None:
    assert _observation().ready_for_success("game-vanilla-main")
    assert not _observation(dns_ipv4_values=()).ready_for_success("game-vanilla-main")
    assert not _observation(runtime_ready=False).ready_for_success("game-vanilla-main")


def test_ready_other_game_is_a_classified_conflict() -> None:
    with pytest.raises(StartWorkflowError) as captured:
        _observation(observed_active_game_id="game-other").validate_precondition(
            "game-vanilla-main"
        )
    assert captured.value.code is StartErrorCode.ACTIVE_GAME_MISMATCH


def test_ec2_adapter_treats_running_as_idempotent_and_only_starts_stopped() -> None:
    api = FakeEc2({"StartingInstances": [{}]})
    adapter = Ec2LifecycleAdapter(api)
    assert not adapter.start_if_needed(instance_id="i-0123456789abcdef0", current_state="running")
    assert adapter.start_if_needed(instance_id="i-0123456789abcdef0", current_state="stopped")
    assert api.calls == [{"InstanceIds": ["i-0123456789abcdef0"]}]


def test_ec2_adapter_rejects_unsafe_transitional_state() -> None:
    with pytest.raises(StartWorkflowError) as captured:
        Ec2LifecycleAdapter(FakeEc2({})).start_if_needed(
            instance_id="i-0123456789abcdef0", current_state="stopping"
        )
    assert captured.value.code is StartErrorCode.PRECONDITION_FAILED


def test_host_start_adapter_uses_only_fixed_typed_command() -> None:
    api = FakeSsm()
    command_id = FixedHostStartAdapter(api, timeout_seconds=360).start(
        instance_id="i-0123456789abcdef0"
    )
    assert command_id == "command-1"
    assert api.calls == [
        {
            "InstanceIds": ["i-0123456789abcdef0"],
            "DocumentName": "AWS-RunShellScript",
            "Parameters": {"commands": ["sudo /usr/local/libexec/wishicraft/operation-v1 START"]},
            "TimeoutSeconds": 360,
        }
    ]


def test_observation_parser_rejects_raw_or_malformed_state() -> None:
    with pytest.raises(StartWorkflowError) as captured:
        StartObservation.from_item({"observation": {"ec2_state": "running"}})
    assert captured.value.code is StartErrorCode.OBSERVATION_FAILED


def test_reference_timestamp_is_timezone_aware() -> None:
    assert datetime(2026, 8, 29, tzinfo=UTC).utcoffset() is not None


@pytest.mark.parametrize(
    "observation",
    (
        _observation(
            ec2_state="stopped",
            ssm_state="not-applicable",
            runtime_ready=False,
            observed_active_game_id=None,
            public_ipv4=None,
            dns_ipv4_values=(),
        ),
        _observation(runtime_ready=False, observed_active_game_id=None, dns_ipv4_values=()),
    ),
)
def test_desired_running_can_resume_convergence_without_revision_increment(
    observation: StartObservation,
) -> None:
    leases = FakeLeases()
    states = FakeStates(DesiredStateSnapshot(DesiredState.RUNNING, "game-vanilla-main", 2))
    coordinator = StartCoordinator(leases, states, lease_seconds=900)  # type: ignore[arg-type]

    revision, already_ready = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-new", "lease-new", 9999999999),
        observation=observation,
        game_id="game-vanilla-main",
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert (revision, already_ready) == (2, False)
    assert leases.verified == 1
    assert states.updates == []


def test_fully_converged_desired_running_skips_desired_mutation() -> None:
    states = FakeStates(DesiredStateSnapshot(DesiredState.RUNNING, "game-vanilla-main", 2))
    coordinator = StartCoordinator(FakeLeases(), states, lease_seconds=900)  # type: ignore[arg-type]

    revision, already_ready = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-new", "lease-new", 9999999999),
        observation=_observation(),
        game_id="game-vanilla-main",
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert (revision, already_ready) == (2, True)
    assert states.updates == []


def test_desired_stopped_normal_start_advances_revision_once() -> None:
    states = FakeStates(DesiredStateSnapshot(DesiredState.STOPPED, None, 2))
    coordinator = StartCoordinator(FakeLeases(), states, lease_seconds=900)  # type: ignore[arg-type]

    revision, already_ready = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-new", "lease-new", 9999999999),
        observation=_observation(
            ec2_state="stopped",
            ssm_state="not-applicable",
            runtime_ready=False,
            observed_active_game_id=None,
            public_ipv4=None,
            dns_ipv4_values=(),
        ),
        game_id="game-vanilla-main",
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert (revision, already_ready) == (3, False)
    assert len(states.updates) == 1
