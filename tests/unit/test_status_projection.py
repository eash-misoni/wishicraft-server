from __future__ import annotations

import json

import pytest

from wishicraft.status_projection import project_status


def state(
    *,
    desired: str = "STOPPED",
    ec2: str = "stopped",
    ready: bool = False,
    health: str = "HEALTHY",
    dns: str = "absent",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "desired_state": desired,
        "health": health,
        "observed_at": "2026-08-31T00:00:00.000000Z",
        "observation": {
            "ec2_state": ec2,
            "runtime_ready": ready,
            "dns_state": dns,
            "dns_record_name": "mc-dev.wishicraft.net.",
        },
        "discrepancies": [],
        "observation_errors": [],
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (state(), "stopped"),
        (state(desired="RUNNING", ec2="pending", health="DEGRADED"), "starting"),
        (
            state(desired="RUNNING", ec2="running", ready=True, dns="present"),
            "online",
        ),
        (state(desired="STOPPED", ec2="stopping", health="DEGRADED"), "stopping"),
        (state(desired="RUNNING", ec2="running", health="DEGRADED"), "degraded"),
        (state(desired="RUNNING", ec2="unknown", health="UNKNOWN"), "unknown"),
    ],
)
def test_existing_state_axes_project_to_safe_status(
    value: dict[str, object], expected: str
) -> None:
    projection = project_status(value)
    assert projection["status"] == expected
    assert projection["endpoint"] == ("mc-dev.wishicraft.net" if expected == "online" else None)


def test_projection_does_not_include_internal_or_raw_values() -> None:
    value = state(desired="RUNNING", ec2="unknown", health="UNKNOWN")
    value["observation_errors"] = ["SSM_OBSERVATION_FAILED"]
    value["discrepancies"] = ["internal-discrepancy"]
    value["target_instance_id"] = "i-00000000000000000"
    projection = project_status(value)
    rendered = json.dumps(projection)
    for forbidden in ("SSM_", "internal-discrepancy", "i-000", "arn:", "secret", "password"):
        assert forbidden not in rendered
