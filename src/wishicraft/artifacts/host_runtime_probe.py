#!/usr/bin/env python3
# ruff: noqa: UP017, UP045
"""Wishicraft Host Runtime read-only probe v1.

This artifact intentionally has no arguments and performs no repair or lifecycle action.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

# The Target AMI currently provides Python 3.9. Keep this transported artifact
# compatible with that interpreter even though the control-plane package targets 3.12.

SCHEMA_VERSION = 1
PROBE_VERSION = "1.3.0"
MOUNT_PATH = "/srv/minecraft"
EXPECTED_FILESYSTEM_TYPE = "xfs"
EXPECTED_FILESYSTEM_UUID = "420cea6d-0520-4436-bb5a-db1191f1e63b"
DOCKER_UNIT = "docker.service"
HOST_RUNTIME_UNIT = "wishicraft-host-runtime.service"
RUNTIME_ID = "wishicraft-host-runtime"
COMPOSE_PROJECT = "wishicraft-host-runtime"
COMPOSE_SERVICE = "minecraft"
EXPECTED_MINECRAFT_VERSION = "26.2"
MINECRAFT_HOST = "localhost"
MINECRAFT_PORT = 25565
PROTOCOL_TIMEOUT = "3s"
_DIGEST_PATTERN = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")
_GAME_ID_PATTERN = re.compile(r"game-[a-z0-9]+(?:-[a-z0-9]+)*$")
_GAME_ID_LABEL = "com.wishicraft.active-game-id"
_GAME_DATA_SOURCE_LABEL = "com.wishicraft.active-game-data-source"


def run(*command: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", "")
    except OSError:
        return subprocess.CompletedProcess(command, 127, "", "")


def instance_id() -> tuple[Optional[str], Optional[str]]:
    try:
        token_request = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_request, timeout=2) as response:
            token = response.read().decode("ascii")
        identity_request = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(identity_request, timeout=2) as response:
            value = response.read().decode("ascii")
        if re.fullmatch(r"i-[0-9a-f]{17}", value) is None:
            return None, "INSTANCE_ID_INVALID"
        return value, None
    except (OSError, UnicodeError, TimeoutError):
        return None, "INSTANCE_ID_UNAVAILABLE"


def observe_mount() -> tuple[dict[str, Any], Optional[str]]:
    result: dict[str, Any] = {
        "state": "unknown",
        "mount_path": MOUNT_PATH,
        "filesystem_type": None,
        "filesystem_uuid": None,
        "expected_filesystem_type": EXPECTED_FILESYSTEM_TYPE,
        "expected_filesystem_uuid": EXPECTED_FILESYSTEM_UUID,
        "root_uid": None,
        "root_gid": None,
        "root_mode": None,
    }
    probe = run("findmnt", "-rn", "-o", "TARGET,FSTYPE,UUID", "--target", MOUNT_PATH)
    if probe.returncode == 1 and not probe.stdout.strip():
        result["state"] = "not-mounted"
        return result, None
    fields = probe.stdout.strip().split()
    if probe.returncode != 0 or len(fields) != 3 or fields[0] != MOUNT_PATH:
        return result, "MOUNT_OBSERVATION_FAILED"
    filesystem_type, filesystem_uuid = fields[1], fields[2]
    result["filesystem_type"] = filesystem_type
    result["filesystem_uuid"] = filesystem_uuid
    result["state"] = (
        "expected"
        if filesystem_type == EXPECTED_FILESYSTEM_TYPE
        and filesystem_uuid == EXPECTED_FILESYSTEM_UUID
        else "mismatch"
    )
    try:
        metadata = os.stat(MOUNT_PATH, follow_symlinks=False)
    except OSError:
        return result, "MOUNT_METADATA_FAILED"
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        return result, "MOUNT_PATH_INVALID"
    result["root_uid"] = metadata.st_uid
    result["root_gid"] = metadata.st_gid
    result["root_mode"] = format(stat.S_IMODE(metadata.st_mode), "04o")
    return result, None


def observe_unit(unit: str) -> tuple[str, Optional[str]]:
    probe = run(
        "systemctl",
        "show",
        unit,
        "--property=LoadState",
        "--property=ActiveState",
        "--value",
    )
    values = probe.stdout.splitlines()
    if probe.returncode != 0 or len(values) != 2:
        return "unknown", "SYSTEMD_OBSERVATION_FAILED"
    load_state, active_state = values
    if load_state == "not-found":
        return "not-found", None
    if load_state != "loaded":
        return "unknown", "SYSTEMD_LOAD_STATE_UNKNOWN"
    if active_state in {"active", "inactive", "failed", "activating", "deactivating"}:
        return active_state, None
    return "unknown", "SYSTEMD_ACTIVE_STATE_UNKNOWN"


def absent_container() -> dict[str, Any]:
    return {
        "state": "not-found",
        "container_id": None,
        "name": None,
        "image_reference": None,
        "image_digest": None,
        "restart_policy": None,
        "health": "not-applicable",
        "oom_killed": None,
        "restart_count": None,
        "published_ports": {},
    }


def active_game_not_applicable() -> dict[str, Any]:
    return {"state": "not-applicable", "game_id": None, "binding_consistency": "not-applicable"}


def observe_active_game(document: dict[str, Any]) -> dict[str, Any]:
    """Read Host Runtime labels and verify their declared /data bind without path inference."""
    unknown = {"state": "unknown", "game_id": None, "binding_consistency": "unknown"}
    try:
        config = document["Config"]
        labels = config["Labels"]
        mounts = document["Mounts"]
        if not isinstance(labels, dict) or not isinstance(mounts, list):
            return unknown
        game_id = labels.get(_GAME_ID_LABEL)
        declared_source = labels.get(_GAME_DATA_SOURCE_LABEL)
        if (
            not isinstance(game_id, str)
            or _GAME_ID_PATTERN.fullmatch(game_id) is None
            or not isinstance(declared_source, str)
            or not declared_source.startswith(f"{MOUNT_PATH}/games/")
        ):
            return unknown
        data_mounts = [
            item for item in mounts if isinstance(item, dict) and item.get("Destination") == "/data"
        ]
        if len(data_mounts) != 1:
            return unknown
        data_mount = data_mounts[0]
        source = data_mount.get("Source")
        if data_mount.get("Type") != "bind" or not isinstance(source, str):
            return unknown
        expected_source = f"{MOUNT_PATH}/games/{game_id}/server"
        return {
            "state": "observed",
            "game_id": game_id,
            "binding_consistency": (
                "consistent"
                if declared_source == expected_source and source == declared_source
                else "mismatch"
            ),
        }
    except (KeyError, TypeError):
        return unknown


def observe_container(
    docker_state: str,
) -> tuple[dict[str, Any], dict[str, Any], Optional[str]]:
    if docker_state != "active":
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return result, {"state": "unknown", "game_id": None, "binding_consistency": "unknown"}, None
    listed = run(
        "docker",
        "ps",
        "--all",
        "--filter",
        f"label=com.docker.compose.project={COMPOSE_PROJECT}",
        "--filter",
        f"label=com.docker.compose.service={COMPOSE_SERVICE}",
        "--format",
        "{{.ID}}",
    )
    if listed.returncode != 0:
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return (
            result,
            {"state": "unknown", "game_id": None, "binding_consistency": "unknown"},
            "CONTAINER_LIST_FAILED",
        )
    identifiers = [line for line in listed.stdout.splitlines() if line]
    if not identifiers:
        return absent_container(), active_game_not_applicable(), None
    if len(identifiers) != 1:
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return (
            result,
            {"state": "unknown", "game_id": None, "binding_consistency": "unknown"},
            "CONTAINER_DUPLICATE",
        )
    inspected = run("docker", "inspect", identifiers[0])
    if inspected.returncode != 0:
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return (
            result,
            {"state": "unknown", "game_id": None, "binding_consistency": "unknown"},
            "CONTAINER_INSPECT_FAILED",
        )
    try:
        documents = json.loads(inspected.stdout)
        document = documents[0] if isinstance(documents, list) and len(documents) == 1 else None
        if not isinstance(document, dict):
            raise ValueError
        config = document["Config"]
        state = document["State"]
        host_config = document["HostConfig"]
        network = document["NetworkSettings"]
        if not all(isinstance(value, dict) for value in (config, state, host_config, network)):
            raise ValueError
        image_reference = config["Image"]
        raw_status = state["Status"]
        restart_policy = host_config["RestartPolicy"]["Name"]
        health_object = state.get("Health")
        health = (
            health_object.get("Status", "unknown")
            if isinstance(health_object, dict)
            else "not-configured"
        )
        if not isinstance(image_reference, str) or not isinstance(raw_status, str):
            raise ValueError
        if not isinstance(restart_policy, str) or not isinstance(health, str):
            raise ValueError
        status_value = "running" if raw_status == "running" else "stopped"
        digest_match = _DIGEST_PATTERN.search(image_reference)
        ports = host_config.get("PortBindings")
        published_ports = ports if isinstance(ports, dict) else {}
        container = {
            "state": status_value,
            "container_id": str(document["Id"]),
            "name": str(document["Name"]).removeprefix("/"),
            "image_reference": image_reference,
            "image_digest": digest_match.group("digest") if digest_match else None,
            "restart_policy": restart_policy or "no",
            "health": health,
            "oom_killed": state["OOMKilled"],
            "restart_count": document["RestartCount"],
            "published_ports": published_ports,
        }
        active_game = (
            observe_active_game(document)
            if status_value == "running"
            else active_game_not_applicable()
        )
        return container, active_game, None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return (
            result,
            {"state": "unknown", "game_id": None, "binding_consistency": "unknown"},
            "CONTAINER_SCHEMA_INVALID",
        )


def protocol_not_applicable() -> dict[str, Any]:
    return {
        "attempted": False,
        "result": "not-applicable",
        "compatible_response": False,
        "host": MINECRAFT_HOST,
        "port": MINECRAFT_PORT,
        "reported_version": None,
        "protocol_version": None,
        "player_count": None,
        "version_match": None,
        "observed_at": None,
    }


def version_matches_expected(reported_version: str) -> bool:
    pattern = rf"(?:^|[^0-9.]){re.escape(EXPECTED_MINECRAFT_VERSION)}(?:$|[^0-9.])"
    return re.search(pattern, reported_version) is not None


def observe_protocol(container_id: str) -> tuple[dict[str, Any], str, bool]:
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    observation: dict[str, Any] = {
        "attempted": True,
        "result": "unknown",
        "compatible_response": False,
        "host": MINECRAFT_HOST,
        "port": MINECRAFT_PORT,
        "reported_version": None,
        "protocol_version": None,
        "player_count": None,
        "version_match": None,
        "observed_at": observed_at,
    }
    probe = run(
        "docker",
        "exec",
        container_id,
        "mc-monitor",
        "status",
        "--json",
        "--host",
        MINECRAFT_HOST,
        "--port",
        str(MINECRAFT_PORT),
        "--timeout",
        PROTOCOL_TIMEOUT,
    )
    if probe.returncode in {124, 127}:
        observation["result"] = "unavailable"
        return observation, "unknown", False
    if probe.returncode != 0:
        observation["result"] = "failed"
        return observation, "not-ready", False
    try:
        document = json.loads(probe.stdout)
        if not isinstance(document, dict):
            raise ValueError
        if document.get("host") != MINECRAFT_HOST or document.get("port") != MINECRAFT_PORT:
            raise ValueError
        server_info = document.get("server_info")
        if not isinstance(server_info, dict):
            raise ValueError
        version = server_info.get("version")
        players = server_info.get("players")
        if not isinstance(version, dict):
            raise ValueError
        reported_version = version.get("name")
        protocol_version = version.get("protocol")
        raw_player_count = players.get("online") if isinstance(players, dict) else None
        player_count = (
            raw_player_count
            if isinstance(raw_player_count, int)
            and not isinstance(raw_player_count, bool)
            and raw_player_count >= 0
            else None
        )
        if (
            not isinstance(reported_version, str)
            or not reported_version
            or len(reported_version) > 128
            or not isinstance(protocol_version, int)
            or isinstance(protocol_version, bool)
            or protocol_version <= 0
        ):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return observation, "unknown", False
    version_match = version_matches_expected(reported_version)
    observation.update(
        {
            "result": "success",
            "compatible_response": True,
            "reported_version": reported_version,
            "protocol_version": protocol_version,
            "player_count": player_count,
            "version_match": version_match,
        }
    )
    return observation, "ready" if version_match else "not-ready", version_match


def main() -> int:
    errors: list[str] = []
    observed_instance_id, identity_error = instance_id()
    if identity_error:
        errors.append(identity_error)
    mount, mount_error = observe_mount()
    if mount_error:
        errors.append(mount_error)
    docker_state, docker_error = observe_unit(DOCKER_UNIT)
    if docker_error:
        errors.append(docker_error)
    runtime_state, runtime_error = observe_unit(HOST_RUNTIME_UNIT)
    if runtime_error:
        errors.append(runtime_error)
    container, active_game, container_error = observe_container(docker_state)
    if container_error:
        errors.append(container_error)
    if container["state"] in {"stopped", "not-found"}:
        minecraft = {
            "runtime_state": "not-running",
            "protocol_state": "not-applicable",
            "protocol": protocol_not_applicable(),
            "ready": False,
        }
    elif container["state"] == "running" and isinstance(container["container_id"], str):
        protocol, protocol_state, ready = observe_protocol(container["container_id"])
        minecraft = {
            "runtime_state": "running",
            "protocol_state": protocol_state,
            "protocol": protocol,
            "ready": ready,
        }
    else:
        minecraft = {
            "runtime_state": "unknown",
            "protocol_state": "unknown",
            "protocol": {
                **protocol_not_applicable(),
                "result": "unknown",
            },
            "ready": False,
        }
    document = {
        "schema_version": SCHEMA_VERSION,
        "probe_version": PROBE_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "identity": {
            "instance_id": observed_instance_id,
            "runtime_id": RUNTIME_ID,
            "compose_project": COMPOSE_PROJECT,
            "compose_service": COMPOSE_SERVICE,
        },
        "mount": mount,
        "docker": {"state": docker_state},
        "host_runtime": {"unit": HOST_RUNTIME_UNIT, "state": runtime_state},
        "container": container,
        "active_game": active_game,
        "minecraft": minecraft,
        "errors": sorted(errors),
    }
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
