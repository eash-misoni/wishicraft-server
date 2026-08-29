from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wishicraft.operation import LeaseProof
from wishicraft.stop_workflow import (
    Ec2StopAdapter,
    FixedHostStopAdapter,
    StopCoordinator,
    StopErrorCode,
    StopObservation,
    StopWorkflowError,
)
from wishicraft.system_state import DesiredState, DesiredStateSnapshot


class FakeEc2:
    def __init__(self, response: object = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.response = {"StoppingInstances": [{}]} if response is None else response

    def stop_instances(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class FakeSsm:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_command(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {"Command": {"CommandId": "command-stop"}}


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


def observation(**overrides: object) -> StopObservation:
    values: dict[str, object] = {
        "ec2_state": "running",
        "ssm_state": "online",
        "host_runtime_state": "ready",
        "minecraft_service_state": "active",
        "minecraft_protocol_state": "ready",
        "public_ipv4": "203.0.113.10",
        "dns_ipv4_values": ("203.0.113.10",),
        "health": "DEGRADED",
    }
    values.update(overrides)
    return StopObservation(**values)  # type: ignore[arg-type]


def stopped_observation(*, dns: tuple[str, ...] = ()) -> StopObservation:
    return observation(
        ec2_state="stopped",
        ssm_state="not-applicable",
        host_runtime_state="not-running",
        minecraft_service_state="not-running",
        minecraft_protocol_state="not-applicable",
        public_ipv4=None,
        dns_ipv4_values=dns,
        health="HEALTHY" if not dns else "DEGRADED",
    )


def test_terminal_success_requires_every_stopped_axis_and_dns_absence() -> None:
    assert stopped_observation().ready_for_success()
    assert not stopped_observation(dns=("203.0.113.10",)).ready_for_success()
    assert not observation(ec2_state="stopped").ready_for_success()


def test_running_stop_changes_desired_once() -> None:
    states = FakeStates(DesiredStateSnapshot(DesiredState.RUNNING, "game-vanilla-main", 2))
    coordinator = StopCoordinator(FakeLeases(), states, 900)  # type: ignore[arg-type]
    revision, already_stopped = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-stop", "lease-stop", 9999999999),
        observation=observation(),
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert (revision, already_stopped) == (3, False)
    assert states.updates[0]["desired_state"] is DesiredState.STOPPED
    assert states.updates[0]["desired_game_id"] is None


def test_desired_running_actual_stopped_converges_without_restart_side_effect() -> None:
    states = FakeStates(DesiredStateSnapshot(DesiredState.RUNNING, "game-vanilla-main", 2))
    coordinator = StopCoordinator(FakeLeases(), states, 900)  # type: ignore[arg-type]
    revision, already_stopped = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-stop", "lease-stop", 9999999999),
        observation=stopped_observation(dns=("203.0.113.10",)),
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert (revision, already_stopped) == (3, True)
    assert len(states.updates) == 1


@pytest.mark.parametrize("actual", [observation(), stopped_observation()])
def test_desired_stopped_convergence_does_not_increment_revision(
    actual: StopObservation,
) -> None:
    states = FakeStates(DesiredStateSnapshot(DesiredState.STOPPED, None, 3))
    coordinator = StopCoordinator(FakeLeases(), states, 900)  # type: ignore[arg-type]
    revision, already_stopped = coordinator.verify_and_set_desired(
        proof=LeaseProof("wishicraft-main", "op-stop", "lease-stop", 9999999999),
        observation=actual,
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert revision == 3
    assert already_stopped is actual.ec2_stopped
    assert states.updates == []


def test_host_stop_is_one_fixed_typed_command() -> None:
    api = FakeSsm()
    assert (
        FixedHostStopAdapter(api, timeout_seconds=360).stop(instance_id="i-0123456789abcdef0")
        == "command-stop"
    )
    assert api.calls[0]["Parameters"] == {
        "commands": ["sudo /usr/local/libexec/wishicraft/operation-v1 STOP"]
    }


def test_ec2_stop_requires_confirmed_graceful_runtime_stop() -> None:
    api = FakeEc2()
    with pytest.raises(StopWorkflowError) as captured:
        Ec2StopAdapter(api).stop_if_needed(
            instance_id="i-0123456789abcdef0", observation=observation()
        )
    assert captured.value.code is StopErrorCode.PRECONDITION_FAILED
    assert api.calls == []


def test_ec2_stop_runs_only_after_runtime_is_stopped() -> None:
    api = FakeEc2()
    actual = observation(
        host_runtime_state="not-running",
        minecraft_service_state="not-running",
        minecraft_protocol_state="not-applicable",
    )
    assert Ec2StopAdapter(api).stop_if_needed(instance_id="i-0123456789abcdef0", observation=actual)
    assert api.calls == [{"InstanceIds": ["i-0123456789abcdef0"]}]


def test_ec2_stop_api_failure_is_classified() -> None:
    api = FakeEc2({})
    actual = observation(
        host_runtime_state="not-running",
        minecraft_service_state="not-running",
        minecraft_protocol_state="not-applicable",
    )
    with pytest.raises(StopWorkflowError) as captured:
        Ec2StopAdapter(api).stop_if_needed(instance_id="i-0123456789abcdef0", observation=actual)
    assert captured.value.code is StopErrorCode.EC2_STOP_FAILED


def test_observation_errors_fail_closed() -> None:
    with pytest.raises(StopWorkflowError) as captured:
        observation(observation_errors=("ssm_probe_failed",)).validate_precondition()
    assert captured.value.code is StopErrorCode.OBSERVATION_FAILED
