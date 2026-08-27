#!/usr/bin/env python3
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
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = 1
PROBE_VERSION = "1.0.0"
MOUNT_PATH = "/srv/minecraft"
EXPECTED_FILESYSTEM_TYPE = "xfs"
EXPECTED_FILESYSTEM_UUID = "420cea6d-0520-4436-bb5a-db1191f1e63b"
DOCKER_UNIT = "docker.service"
HOST_RUNTIME_UNIT = "wishicraft-host-runtime.service"
RUNTIME_ID = "wishicraft-host-runtime"
COMPOSE_PROJECT = "wishicraft-host-runtime"
COMPOSE_SERVICE = "minecraft"
_DIGEST_PATTERN = re.compile(r"@(?P<digest>sha256:[0-9a-f]{64})$")


def run(*command: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(command, 127, "", "")


def instance_id() -> tuple[str | None, str | None]:
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


def observe_mount() -> tuple[dict[str, Any], str | None]:
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


def observe_unit(unit: str) -> tuple[str, str | None]:
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
        "published_ports": [],
    }


def observe_container(docker_state: str) -> tuple[dict[str, Any], str | None]:
    if docker_state != "active":
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return result, None
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
        return result, "CONTAINER_LIST_FAILED"
    identifiers = [line for line in listed.stdout.splitlines() if line]
    if not identifiers:
        return absent_container(), None
    if len(identifiers) != 1:
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return result, "CONTAINER_DUPLICATE"
    inspected = run("docker", "inspect", identifiers[0])
    if inspected.returncode != 0:
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return result, "CONTAINER_INSPECT_FAILED"
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
        return {
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
        }, None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        result = absent_container()
        result["state"] = "unknown"
        result["health"] = "unknown"
        return result, "CONTAINER_SCHEMA_INVALID"


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
    container, container_error = observe_container(docker_state)
    if container_error:
        errors.append(container_error)
    if container["state"] in {"stopped", "not-found"}:
        minecraft = {
            "runtime_state": "not-running",
            "protocol_state": "not-applicable",
            "ready": False,
        }
    else:
        minecraft = {"runtime_state": "unknown", "protocol_state": "unknown", "ready": False}
    document = {
        "schema_version": SCHEMA_VERSION,
        "probe_version": PROBE_VERSION,
        "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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
        "minecraft": minecraft,
        "errors": sorted(errors),
    }
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
