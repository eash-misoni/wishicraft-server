"""Secret-free Host Runtime probe fixtures shared by status and parser tests."""

from __future__ import annotations

import json

TARGET_INSTANCE_ID = "i-04fc0629dc4ea466e"
EXPECTED_UUID = "420cea6d-0520-4436-bb5a-db1191f1e63b"


def runtime_stopped_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "probe_version": "1.0.0",
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
            "ready": False,
        },
        "errors": [],
    }
    document.update(overrides)
    return document


def runtime_stopped_json(**overrides: object) -> str:
    return json.dumps(runtime_stopped_document(**overrides), separators=(",", ":"))
