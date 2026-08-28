"""Tests for strict Host Runtime probe schema v1 parsing."""

from __future__ import annotations

import copy
import json

import pytest

from tests.probe_fixtures import (
    TARGET_INSTANCE_ID,
    runtime_running_document,
    runtime_stopped_document,
)
from wishicraft.probe import (
    ActiveGameState,
    BindingConsistency,
    ContainerState,
    DockerState,
    HostRuntimeProbe,
    MountState,
    ProbeContractError,
    ProtocolResult,
    ProtocolState,
    UnitState,
    parse_host_runtime_probe,
)


def parse(document: dict[str, object]) -> HostRuntimeProbe:
    return parse_host_runtime_probe(json.dumps(document), expected_instance_id=TARGET_INSTANCE_ID)


def test_valid_runtime_stopped_probe() -> None:
    probe = parse_host_runtime_probe(
        json.dumps(runtime_stopped_document()), expected_instance_id=TARGET_INSTANCE_ID
    )

    assert probe.mount.state is MountState.EXPECTED
    assert probe.docker_state is DockerState.ACTIVE
    assert probe.host_runtime_state is UnitState.INACTIVE
    assert probe.container.state is ContainerState.NOT_FOUND
    assert probe.minecraft_runtime_state == "not-running"
    assert probe.protocol_state == "not-applicable"
    assert probe.active_game.state is ActiveGameState.NOT_APPLICABLE
    assert probe.active_game.game_id is None
    assert probe.ready is False
    assert probe.errors == ()


@pytest.mark.parametrize("stdout", ["", "not-json", "[]"])
def test_invalid_json_or_top_level_type_is_rejected(stdout: str) -> None:
    with pytest.raises(ProbeContractError):
        parse_host_runtime_probe(stdout, expected_instance_id=TARGET_INSTANCE_ID)


def test_unknown_schema_version_is_rejected() -> None:
    document = runtime_stopped_document(schema_version=2)

    with pytest.raises(ProbeContractError, match="unsupported probe schema"):
        parse(document)


def test_unknown_probe_version_is_rejected() -> None:
    document = runtime_stopped_document(probe_version="1.1.0")

    with pytest.raises(ProbeContractError, match="unsupported probe version"):
        parse(document)


def test_missing_required_field_is_rejected() -> None:
    document = runtime_stopped_document()
    del document["mount"]

    with pytest.raises(ProbeContractError, match="mount must be an object"):
        parse(document)


def test_running_protocol_success_establishes_ready() -> None:
    probe = parse_host_runtime_probe(
        json.dumps(runtime_running_document()), expected_instance_id=TARGET_INSTANCE_ID
    )

    assert probe.container.state is ContainerState.RUNNING
    assert probe.minecraft_runtime_state == "running"
    assert probe.protocol_state is ProtocolState.READY
    assert probe.protocol.result is ProtocolResult.SUCCESS
    assert probe.protocol.reported_version == "26.2"
    assert probe.protocol.protocol_version == 772
    assert probe.protocol.player_count == 0
    assert probe.protocol.version_match is True
    assert probe.active_game.game_id == "game-vanilla-main"
    assert probe.active_game.binding_consistency is BindingConsistency.CONSISTENT
    assert probe.ready is True


@pytest.mark.parametrize("result", ["failed", "unavailable", "unknown"])
def test_protocol_failure_never_establishes_ready(result: str) -> None:
    probe = parse_host_runtime_probe(
        json.dumps(
            runtime_running_document(
                protocol_result=result,
                reported_version=None,
                protocol_version=None,
                version_match=None,
            )
        ),
        expected_instance_id=TARGET_INSTANCE_ID,
    )

    assert probe.protocol.result.value == result
    assert probe.ready is False


def test_protocol_version_mismatch_is_explicitly_not_ready() -> None:
    probe = parse_host_runtime_probe(
        json.dumps(
            runtime_running_document(reported_version="Minecraft 26.3", version_match=False)
        ),
        expected_instance_id=TARGET_INSTANCE_ID,
    )

    assert probe.protocol.compatible_response is True
    assert probe.protocol.version_match is False
    assert probe.protocol_state is ProtocolState.NOT_READY
    assert probe.ready is False


def test_version_comparison_accepts_expected_version_with_label() -> None:
    probe = parse_host_runtime_probe(
        json.dumps(runtime_running_document(reported_version="Minecraft 26.2")),
        expected_instance_id=TARGET_INSTANCE_ID,
    )

    assert probe.protocol.version_match is True
    assert probe.ready is True


@pytest.mark.parametrize(
    "mutation",
    [
        {"host": "public.example.test"},
        {"port": 25566},
        {"observed_at": None},
        {"protocol_version": "772"},
        {"reported_version": None},
        {"player_count": -1},
        {"player_count": "0"},
    ],
)
def test_malformed_protocol_contract_is_rejected(mutation: dict[str, object]) -> None:
    document = runtime_running_document()
    minecraft = document["minecraft"]
    assert isinstance(minecraft, dict)
    protocol = minecraft["protocol"]
    assert isinstance(protocol, dict)
    protocol.update(mutation)

    with pytest.raises(ProbeContractError):
        parse(document)


def test_docker_unavailable_requires_unknown_container() -> None:
    document = copy.deepcopy(runtime_stopped_document())
    docker = document["docker"]
    container = document["container"]
    minecraft = document["minecraft"]
    assert isinstance(docker, dict)
    assert isinstance(container, dict)
    assert isinstance(minecraft, dict)
    docker["state"] = "inactive"
    container.update(
        {
            "state": "unknown",
            "health": "unknown",
            "published_ports": {},
        }
    )
    minecraft.update({"runtime_state": "unknown", "protocol_state": "unknown", "ready": False})
    document["active_game"] = {
        "state": "unknown",
        "game_id": None,
        "binding_consistency": "unknown",
    }
    protocol = minecraft["protocol"]
    assert isinstance(protocol, dict)
    protocol["result"] = "unknown"

    probe = parse_host_runtime_probe(json.dumps(document), expected_instance_id=TARGET_INSTANCE_ID)

    assert probe.docker_state is DockerState.INACTIVE
    assert probe.container.state is ContainerState.UNKNOWN
    assert probe.ready is False


def test_container_missing_is_a_known_not_running_state() -> None:
    probe = parse_host_runtime_probe(
        json.dumps(runtime_stopped_document()), expected_instance_id=TARGET_INSTANCE_ID
    )

    assert probe.container.state is ContainerState.NOT_FOUND
    assert probe.minecraft_runtime_state == "not-running"
    assert probe.protocol_state == "not-applicable"
    assert probe.protocol.player_count is None


def test_protocol_success_preserves_positive_player_count_without_sample() -> None:
    probe = parse(runtime_running_document(player_count=4))

    assert probe.protocol.player_count == 4
    assert not hasattr(probe.protocol, "players")
    assert probe.ready is True


def test_protocol_success_allows_unknown_player_count_without_changing_ready() -> None:
    probe = parse(runtime_running_document(player_count=None))

    assert probe.protocol.player_count is None
    assert probe.protocol_state is ProtocolState.READY
    assert probe.ready is True


def test_observation_failure_remains_unknown() -> None:
    document = copy.deepcopy(runtime_stopped_document())
    mount = document["mount"]
    assert isinstance(mount, dict)
    mount.update(
        {
            "state": "unknown",
            "filesystem_type": None,
            "filesystem_uuid": None,
            "root_uid": None,
            "root_gid": None,
            "root_mode": None,
        }
    )
    document["errors"] = ["MOUNT_OBSERVATION_FAILED"]

    probe = parse_host_runtime_probe(json.dumps(document), expected_instance_id=TARGET_INSTANCE_ID)

    assert probe.mount.state is MountState.UNKNOWN
    assert probe.errors == ("MOUNT_OBSERVATION_FAILED",)
    assert probe.ready is False


def test_instance_identity_mismatch_is_rejected() -> None:
    with pytest.raises(ProbeContractError, match="identity mismatch"):
        parse_host_runtime_probe(
            json.dumps(runtime_stopped_document()),
            expected_instance_id="i-00000000000000000",
        )


@pytest.mark.parametrize("game_id", [None, "", "../world", "game_Invalid"])
def test_malformed_observed_active_game_is_rejected(game_id: object) -> None:
    document = runtime_running_document()
    active_game = document["active_game"]
    assert isinstance(active_game, dict)
    active_game["game_id"] = game_id

    with pytest.raises(ProbeContractError, match="active game|game_id"):
        parse(document)


def test_running_container_accepts_unknown_active_game_fail_closed() -> None:
    document = runtime_running_document()
    document["active_game"] = {
        "state": "unknown",
        "game_id": None,
        "binding_consistency": "unknown",
    }

    probe = parse(document)

    assert probe.active_game.state is ActiveGameState.UNKNOWN
    assert probe.ready is True


def test_stopped_container_rejects_observed_active_game() -> None:
    document = runtime_stopped_document()
    document["active_game"] = {
        "state": "observed",
        "game_id": "game-vanilla-main",
        "binding_consistency": "consistent",
    }

    with pytest.raises(ProbeContractError, match="stopped container"):
        parse(document)
