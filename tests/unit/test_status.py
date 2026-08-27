"""Tests for fail-closed target status observation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wishicraft.status import (
    Ec2Api,
    Ec2State,
    HostRuntimeState,
    MinecraftState,
    SsmApi,
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


class FakeSsm:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[list[dict[str, object]]] = []

    def describe_instance_information(self, *, Filters: list[dict[str, object]]) -> object:
        self.calls.append(Filters)
        return self.response


class FailingSsm:
    def describe_instance_information(self, *, Filters: list[dict[str, object]]) -> object:
        raise RuntimeError("SSM response detail must not escape the adapter")


def observer(ec2: Ec2Api, ssm: SsmApi | None = None) -> TargetStatusObserver:
    return TargetStatusObserver(
        instance_id=TARGET_INSTANCE_ID,
        ec2=ec2,
        ssm=ssm if ssm is not None else FakeSsm({}),
    )


def test_stopped_target_short_circuits_unreachable_runtime_layers() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "stopped"}}]}
            ]
        }
    )

    ssm = FakeSsm({})
    status = observer(ec2, ssm).observe(observed_at=OBSERVED_AT)

    assert ec2.calls == [[TARGET_INSTANCE_ID]]
    assert ssm.calls == []
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


def test_pending_target_does_not_query_ssm() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "pending"}}]}
            ]
        }
    )
    ssm = FakeSsm({})

    status = observer(ec2, ssm).observe(observed_at=OBSERVED_AT)

    assert ssm.calls == []
    assert status.ec2_state is Ec2State.PENDING
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.ready is False


@pytest.mark.parametrize(
    ("ping_status", "expected_state"),
    [
        ("Online", SsmState.ONLINE),
        ("Inactive", SsmState.OFFLINE),
        ("ConnectionLost", SsmState.CONNECTION_LOST),
    ],
)
def test_running_target_observes_ssm_managed_node(
    ping_status: str, expected_state: SsmState
) -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = FakeSsm(
        {"InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": ping_status}]}
    )

    status = observer(ec2, ssm).observe(observed_at=OBSERVED_AT)

    assert ssm.calls == [[{"Key": "InstanceIds", "Values": [TARGET_INSTANCE_ID]}]]
    assert status.ec2_state is Ec2State.RUNNING
    assert status.ssm_state is expected_state
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN
    assert status.ready is False
    assert status.observed_at is OBSERVED_AT


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"InstanceInformationList": []},
        {
            "InstanceInformationList": [
                {"InstanceId": "i-00000000000000000", "PingStatus": "Online"}
            ]
        },
        {
            "InstanceInformationList": [
                {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "FutureStatus"}
            ]
        },
        {
            "InstanceInformationList": [
                {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"},
                {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"},
            ]
        },
        {
            "InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}],
            "NextToken": "more-results",
        },
    ],
)
def test_invalid_or_unmatched_ssm_response_is_unknown(response: object) -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )

    status = observer(ec2, FakeSsm(response)).observe(observed_at=OBSERVED_AT)

    assert status.ec2_state is Ec2State.RUNNING
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.ready is False


def test_ssm_api_failure_is_unknown() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )

    status = observer(ec2, FailingSsm()).observe(observed_at=OBSERVED_AT)

    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.ready is False


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
    status = observer(FakeEc2(response)).observe(observed_at=OBSERVED_AT)

    assert status.ec2_state is Ec2State.UNKNOWN
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN
    assert status.ready is False


def test_ec2_api_failure_is_unknown_not_stopped() -> None:
    status = observer(FailingEc2()).observe(observed_at=OBSERVED_AT)

    assert status.ec2_state is Ec2State.UNKNOWN
    assert status.ssm_state is SsmState.UNKNOWN
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN


def test_invalid_target_instance_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid target EC2 instance ID"):
        TargetStatusObserver(instance_id="i-guessed", ec2=FakeEc2({}), ssm=FakeSsm({}))


def test_naive_observation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        observer(FakeEc2({})).observe(observed_at=datetime(2026, 8, 23))
