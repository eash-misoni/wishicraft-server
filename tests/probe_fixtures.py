"""Secret-free Host Runtime probe fixtures shared by status and parser tests."""

from __future__ import annotations

import json

TARGET_INSTANCE_ID = "i-04fc0629dc4ea466e"
EXPECTED_UUID = "420cea6d-0520-4436-bb5a-db1191f1e63b"


def runtime_stopped_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "probe_version": "1.1.0",
        "observed_at": "2026-08-27T00:00:00Z",
        "identity": {
            "instance_id": TARGET_INSTANCE_ID,
            "runtime_id": "wishicraft-host-runtime",
            "compose_project": "wishicraft-host-runtime",
            "compose_service": "minecraft",
        },
        "mount": {
            "state": "expected",
            "mount_path": "/srv/minecraft",
            "filesystem_type": "xfs",
            "filesystem_uuid": EXPECTED_UUID,
            "expected_filesystem_type": "xfs",
            "expected_filesystem_uuid": EXPECTED_UUID,
            "root_uid": 0,
            "root_gid": 0,
            "root_mode": "0755",
        },
        "docker": {"state": "active"},
        "host_runtime": {
            "unit": "wishicraft-host-runtime.service",
            "state": "inactive",
        },
        "container": {
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
        },
        "minecraft": {
            "runtime_state": "not-running",
            "protocol_state": "not-applicable",
            "protocol": {
                "attempted": False,
                "result": "not-applicable",
                "compatible_response": False,
                "host": "localhost",
                "port": 25565,
                "reported_version": None,
                "protocol_version": None,
                "version_match": None,
                "observed_at": None,
            },
            "ready": False,
        },
        "errors": [],
    }
    document.update(overrides)
    return document


def runtime_stopped_json(**overrides: object) -> str:
    return json.dumps(runtime_stopped_document(**overrides), separators=(",", ":"))


def runtime_running_document(
    *,
    protocol_result: str = "success",
    reported_version: str | None = "26.2",
    protocol_version: int | None = 772,
    version_match: bool | None = True,
) -> dict[str, object]:
    document = runtime_stopped_document()
    document["host_runtime"] = {
        "unit": "wishicraft-host-runtime.service",
        "state": "active",
    }
    document["container"] = {
        "state": "running",
        "container_id": "9a83cb71c92d225eb436448dbe94eefe4e7a207ec350c967ec05e72982b0dad6",
        "name": "wishicraft-host-runtime-minecraft-1",
        "image_reference": "ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:"
        "6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77",
        "image_digest": "sha256:6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77",
        "restart_policy": "no",
        "health": "healthy",
        "oom_killed": False,
        "restart_count": 0,
        "published_ports": {},
    }
    successful = protocol_result == "success"
    document["minecraft"] = {
        "runtime_state": "running",
        "protocol_state": (
            "ready"
            if successful and version_match
            else "not-ready"
            if protocol_result in {"success", "failed"}
            else "unknown"
        ),
        "protocol": {
            "attempted": True,
            "result": protocol_result,
            "compatible_response": successful,
            "host": "localhost",
            "port": 25565,
            "reported_version": reported_version if successful else None,
            "protocol_version": protocol_version if successful else None,
            "version_match": version_match if successful else None,
            "observed_at": "2026-08-27T00:00:01Z",
        },
        "ready": successful and version_match is True,
    }
    return document


def runtime_running_json(
    *,
    protocol_result: str = "success",
    reported_version: str | None = "26.2",
    protocol_version: int | None = 772,
    version_match: bool | None = True,
) -> str:
    return json.dumps(
        runtime_running_document(
            protocol_result=protocol_result,
            reported_version=reported_version,
            protocol_version=protocol_version,
            version_match=version_match,
        ),
        separators=(",", ":"),
    )
