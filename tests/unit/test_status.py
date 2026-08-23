"""Tests for fail-closed target status observation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wishicraft.status import (
    Ec2State,
    HostRuntimeState,
    MinecraftState,
    SsmState,
    TargetStatusObserver,
)

TARGET_INSTANCE_ID = "i-04fc0629dc4ea466e"
OBSERVED_AT = datetime(2026, 8, 23, 12, 34, 56, tzinfo=UTC)


class FakeEc2:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[list[str]] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> object:
        self.calls.append(InstanceIds)
        return self.response


class FailingEc2:
    def describe_instances(self, *, InstanceIds: list[str]) -> object:
        raise RuntimeError("AWS response detail must not escape the adapter")


def test_stopped_target_short_circuits_unreachable_runtime_layers() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "stopped"}}]}
            ]
        }
    )

    status = TargetStatusObserver(instance_id=TARGET_INSTANCE_ID, ec2=ec2).observe(
        observed_at=OBSERVED_AT
    )

    assert ec2.calls == [[TARGET_INSTANCE_ID]]
    assert status.ec2_state is Ec2State.STOPPED
    assert status.ssm_state is SsmState.NOT_APPLICABLE
    assert status.host_runtime_state is HostRuntimeState.NOT_RUNNING
    assert status.minecraft_service_state is MinecraftState.NOT_APPLICABLE
    assert status.minecraft_protocol_state is MinecraftState.NOT_APPLICABLE
    assert status.ready is False
    assert status.to_dict() == {
        "schema_version": 1,
        "instance_id": TARGET_INSTANCE_ID,
        "ec2_state": "stopped",
        "ssm_state": "not-applicable",
        "host_runtime_state": "not-running",
        "minecraft_service_state": "not-applicable",
        "minecraft_protocol_state": "not-applicable",
        "ready": False,
        "observed_at": "2026-08-23T12:34:56Z",
    }


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"Reservations": []},
        {
            "Reservations": [
                {"Instances": [{"InstanceId": "i-00000000000000000", "State": {"Name": "stopped"}}]}
            ]
        },
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "future"}}]}
            ]
        },
    ],
)
def test_invalid_or_unmatched_aws_response_is_unknown(response: object) -> None:
    status = TargetStatusObserver(instance_id=TARGET_INSTANCE_ID, ec2=FakeEc2(response)).observe(
        observed_at=OBSERVED_AT
    )

    assert status.ec2_state is Ec2State.UNKNOWN
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN
    assert status.ready is False


def test_ec2_api_failure_is_unknown_not_stopped() -> None:
    status = TargetStatusObserver(instance_id=TARGET_INSTANCE_ID, ec2=FailingEc2()).observe(
        observed_at=OBSERVED_AT
    )

    assert status.ec2_state is Ec2State.UNKNOWN
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN


def test_invalid_target_instance_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid target EC2 instance ID"):
        TargetStatusObserver(instance_id="i-guessed", ec2=FakeEc2({}))


def test_naive_observation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        TargetStatusObserver(instance_id=TARGET_INSTANCE_ID, ec2=FakeEc2({})).observe(
            observed_at=datetime(2026, 8, 23)
        )
