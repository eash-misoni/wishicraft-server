"""Tests for fail-closed target status observation."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tests.probe_fixtures import runtime_running_json, runtime_stopped_json
from wishicraft.probe import ActiveGameState, ContainerState, DockerState, MountState
from wishicraft.status import (
    Discrepancy,
    Ec2Api,
    Ec2State,
    HostRuntimeProbeApi,
    HostRuntimeState,
    MinecraftState,
    PublicIpv4State,
    SsmApi,
    SsmState,
    TargetStatus,
    TargetStatusObserver,
)

TARGET_INSTANCE_ID = "i-04fc0629dc4ea466e"
EXPECTED_GAME_ID = "game-vanilla-main"
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
        self.calls: list[dict[str, object]] = []

    def describe_instance_information(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class FailingSsm:
    def describe_instance_information(self, **kwargs: object) -> object:
        raise RuntimeError("SSM response detail must not escape the adapter")


class ProbeResult:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


class FakeProbe:
    def __init__(self, stdout: str = "{}") -> None:
        self.stdout = stdout
        self.calls: list[str] = []

    def run_probe(self, *, instance_id: str) -> ProbeResult:
        self.calls.append(instance_id)
        return ProbeResult(self.stdout)


class PagedSsm:
    def __init__(self, pages: dict[str | None, object]) -> None:
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def describe_instance_information(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        token = kwargs.get("NextToken")
        return self.pages[token if isinstance(token, str) else None]


def observer(
    ec2: Ec2Api,
    ssm: SsmApi | None = None,
    probe: HostRuntimeProbeApi | None = None,
) -> TargetStatusObserver:
    return TargetStatusObserver(
        instance_id=TARGET_INSTANCE_ID,
        expected_game_id=EXPECTED_GAME_ID,
        ec2=ec2,
        ssm=ssm if ssm is not None else FakeSsm({}),
        host_runtime_probe=probe if probe is not None else FakeProbe(),
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
        "public_ipv4_state": "absent",
        "public_ipv4": None,
        "private_ipv4": None,
        "network_observation_source": "ec2-describe-instances",
        "ssm_state": "not-applicable",
        "mount_state": "unknown",
        "docker_state": "unknown",
        "host_runtime_state": "not-running",
        "container_state": "unknown",
        "minecraft_service_state": "not-applicable",
        "minecraft_protocol_state": "not-applicable",
        "expected_game_id": EXPECTED_GAME_ID,
        "active_game_state": "not-applicable",
        "observed_active_game_id": None,
        "discrepancies": [],
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


def test_running_target_observes_public_and_private_ipv4() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": TARGET_INSTANCE_ID,
                            "State": {"Name": "running"},
                            "PublicIpAddress": "203.0.113.8",
                            "PrivateIpAddress": "10.0.0.8",
                        }
                    ]
                }
            ]
        }
    )
    status = observer(ec2, FakeSsm({"InstanceInformationList": []})).observe(
        observed_at=OBSERVED_AT
    )
    assert status.public_ipv4_state is PublicIpv4State.ASSIGNED
    assert status.public_ipv4 == "203.0.113.8"
    assert status.private_ipv4 == "10.0.0.8"


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

    assert ssm.calls == [{"Filters": [{"Key": "InstanceIds", "Values": [TARGET_INSTANCE_ID]}]}]
    assert status.ec2_state is Ec2State.RUNNING
    assert status.ssm_state is expected_state
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN
    assert status.minecraft_service_state is MinecraftState.UNKNOWN
    assert status.minecraft_protocol_state is MinecraftState.UNKNOWN
    assert status.ready is False
    assert status.observed_at is OBSERVED_AT


def test_ssm_pagination_finds_target_on_second_page_and_runs_probe() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = PagedSsm(
        {
            None: {
                "InstanceInformationList": [
                    {"InstanceId": "i-00000000000000000", "PingStatus": "Online"}
                ],
                "NextToken": "page-2",
            },
            "page-2": {
                "InstanceInformationList": [
                    {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}
                ]
            },
        }
    )
    probe = FakeProbe(runtime_stopped_json())

    status = observer(ec2, ssm, probe).observe(observed_at=OBSERVED_AT)

    assert len(ssm.calls) == 2
    assert ssm.calls[1]["NextToken"] == "page-2"
    assert probe.calls == [TARGET_INSTANCE_ID]
    assert status.ssm_state is SsmState.ONLINE
    assert status.mount_state is MountState.EXPECTED
    assert status.docker_state is DockerState.ACTIVE
    assert status.host_runtime_state is HostRuntimeState.NOT_RUNNING
    assert status.container_state is ContainerState.NOT_FOUND
    assert status.minecraft_service_state is MinecraftState.NOT_RUNNING
    assert status.minecraft_protocol_state is MinecraftState.NOT_APPLICABLE
    assert status.ready is False


def test_online_running_protocol_ready_normalizes_to_ready() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = FakeSsm(
        {"InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}]}
    )
    probe = FakeProbe(runtime_running_json())

    status = observer(ec2, ssm, probe).observe(observed_at=OBSERVED_AT)

    assert probe.calls == [TARGET_INSTANCE_ID]
    assert status.host_runtime_state is HostRuntimeState.RUNNING
    assert status.container_state is ContainerState.RUNNING
    assert status.minecraft_service_state is MinecraftState.RUNNING
    assert status.minecraft_protocol_state is MinecraftState.READY
    assert status.active_game_state is ActiveGameState.OBSERVED
    assert status.observed_active_game_id == EXPECTED_GAME_ID
    assert status.discrepancies == ()
    assert status.ready is True


def ready_status_with_active_game(active_game: dict[str, object]) -> TargetStatus:
    document = json.loads(runtime_running_json())
    document["active_game"] = active_game
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = FakeSsm(
        {"InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}]}
    )
    return observer(ec2, ssm, FakeProbe(json.dumps(document))).observe(observed_at=OBSERVED_AT)


def test_protocol_ready_with_matching_active_game_has_no_discrepancy() -> None:
    status = ready_status_with_active_game(
        {
            "state": "observed",
            "game_id": EXPECTED_GAME_ID,
            "binding_consistency": "consistent",
        }
    )

    assert status.ready is True
    assert status.discrepancies == ()


def test_protocol_ready_with_other_active_game_keeps_runtime_ready() -> None:
    status = ready_status_with_active_game(
        {
            "state": "observed",
            "game_id": "game-fabric-test",
            "binding_consistency": "consistent",
        }
    )

    assert status.ready is True
    assert status.observed_active_game_id == "game-fabric-test"
    assert status.discrepancies == (Discrepancy.ACTIVE_GAME_MISMATCH,)


def test_running_with_unknown_active_game_derives_unknown_discrepancy() -> None:
    status = ready_status_with_active_game(
        {"state": "unknown", "game_id": None, "binding_consistency": "unknown"}
    )

    assert status.ready is True
    assert status.discrepancies == (Discrepancy.ACTIVE_GAME_UNKNOWN,)


def test_active_game_bind_mismatch_is_runtime_discrepancy() -> None:
    status = ready_status_with_active_game(
        {
            "state": "observed",
            "game_id": EXPECTED_GAME_ID,
            "binding_consistency": "mismatch",
        }
    )

    assert status.ready is True
    assert status.discrepancies == (Discrepancy.RUNTIME_STATE_MISMATCH,)


@pytest.mark.parametrize("protocol_result", ["failed", "unavailable", "unknown"])
def test_running_container_without_protocol_success_is_not_ready(protocol_result: str) -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = FakeSsm(
        {"InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}]}
    )
    probe = FakeProbe(
        runtime_running_json(
            protocol_result=protocol_result,
            reported_version=None,
            protocol_version=None,
            version_match=None,
        )
    )

    status = observer(ec2, ssm, probe).observe(observed_at=OBSERVED_AT)

    assert status.host_runtime_state is HostRuntimeState.RUNNING
    assert status.container_state is ContainerState.RUNNING
    assert status.minecraft_service_state is MinecraftState.RUNNING
    assert status.minecraft_protocol_state in {MinecraftState.NOT_READY, MinecraftState.UNKNOWN}
    assert status.ready is False


def test_duplicate_ssm_target_across_pages_is_unknown_and_skips_probe() -> None:
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )
    ssm = PagedSsm(
        {
            None: {
                "InstanceInformationList": [
                    {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}
                ],
                "NextToken": "page-2",
            },
            "page-2": {
                "InstanceInformationList": [
                    {"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}
                ]
            },
        }
    )
    probe = FakeProbe(runtime_stopped_json())

    status = observer(ec2, ssm, probe).observe(observed_at=OBSERVED_AT)

    assert status.ssm_state is SsmState.UNKNOWN
    assert probe.calls == []


@pytest.mark.parametrize("token", ["", 42, "loop"])
def test_malformed_or_looping_ssm_pagination_is_unknown(token: object) -> None:
    first_token = token if token != "loop" else "loop"
    pages: dict[str | None, object] = {
        None: {"InstanceInformationList": [], "NextToken": first_token}
    }
    if token == "loop":
        pages["loop"] = {"InstanceInformationList": [], "NextToken": "loop"}
    ssm = PagedSsm(pages)
    ec2 = FakeEc2(
        {
            "Reservations": [
                {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
            ]
        }
    )

    status = observer(ec2, ssm).observe(observed_at=OBSERVED_AT)

    assert status.ssm_state is SsmState.UNKNOWN


@pytest.mark.parametrize("ping_status", ["Inactive", "ConnectionLost"])
def test_non_online_ssm_state_skips_probe(ping_status: str) -> None:
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
    probe = FakeProbe(runtime_stopped_json())

    status = observer(ec2, ssm, probe).observe(observed_at=OBSERVED_AT)

    assert status.ssm_state in {SsmState.OFFLINE, SsmState.CONNECTION_LOST}
    assert probe.calls == []
    assert status.host_runtime_state is HostRuntimeState.UNKNOWN


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
        TargetStatusObserver(
            instance_id="i-guessed",
            expected_game_id=EXPECTED_GAME_ID,
            ec2=FakeEc2({}),
            ssm=FakeSsm({}),
            host_runtime_probe=FakeProbe(),
        )


def test_naive_observation_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        observer(FakeEc2({})).observe(observed_at=datetime(2026, 8, 23))
