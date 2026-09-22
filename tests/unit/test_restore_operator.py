from __future__ import annotations

import base64
import shlex
import zlib
from datetime import timedelta
from typing import Any

import pytest

from tests.unit.test_restore_repository import NOW, setup
from wishicraft.restore_operator import host_command, lifecycle


@pytest.mark.parametrize(
    "change", ["running", "operation", "lock", "expired", "foreign", "missing"]
)
def test_lifecycle_fail_closed(change: str) -> None:
    _, _, lease, _ = setup()
    state: dict[str, Any] = {"desired_state": "STOPPED", "maintenance": lease}
    lock: dict[str, Any] = {}
    now = NOW
    assert lifecycle(state, lock, maintenance_id=lease["id"], stage="dev", now=now) == lease
    if change == "running":
        state["desired_state"] = "RUNNING"
    elif change == "operation":
        state["current_operation_id"] = "op-active"
    elif change == "lock":
        lock["lease_expires_at"] = 0
    elif change == "expired":
        now += timedelta(hours=1)
    elif change == "foreign":
        lease["stage"] = "other"
    elif change == "missing":
        state.pop("maintenance")
    with pytest.raises(ValueError):
        lifecycle(state, lock, maintenance_id=lease["id"], stage="dev", now=now)


def test_generated_host_payload_is_fixed_python_not_shell_input() -> None:
    command = host_command({"plan": {"request_id": "$(touch /not-allowed)"}})
    args = shlex.split(command)
    assert args[:2] == ["python3", "-c"] and len(args) == 3
    encoded = args[2].split("b64decode('")[1].split("'")[0]
    payload = zlib.decompress(base64.b64decode(encoded)).decode()
    compile(payload, "restore-host-payload", "exec")
    assert "ro,nouuid,norecovery,nodev,nosuid,noexec" in payload
    assert "$(touch /not-allowed)" in payload
    assert "from wishicraft.artifacts import targeted_runtime as host" not in payload
