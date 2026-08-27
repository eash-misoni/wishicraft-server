"""Tests for strict Host Runtime probe schema v1 parsing."""

from __future__ import annotations

import copy
import json

import pytest

from tests.probe_fixtures import TARGET_INSTANCE_ID, runtime_stopped_document
from wishicraft.probe import (
    ContainerState,
    DockerState,
    MountState,
    ProbeContractError,
    UnitState,
    parse_host_runtime_probe,
)


def parse(document: dict[str, object]) -> object:
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


def test_missing_required_field_is_rejected() -> None:
    document = runtime_stopped_document()
    del document["mount"]

    with pytest.raises(ProbeContractError, match="mount must be an object"):
        parse(document)


def test_ready_true_is_impossible_for_probe_v1() -> None:
    document = copy.deepcopy(runtime_stopped_document())
    minecraft = document["minecraft"]
    assert isinstance(minecraft, dict)
    minecraft["ready"] = True

    with pytest.raises(ProbeContractError, match="cannot establish Minecraft READY"):
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
