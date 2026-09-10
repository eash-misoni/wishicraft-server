from __future__ import annotations

import json
import os
import stat
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from tests.probe_fixtures import runtime_stopped_document
from wishicraft.artifacts import host_runtime_probe as probe
from wishicraft.probe import ProbeContractError, parse_host_runtime_probe


def setup_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, ...]], dict[str, Any]]:
    calls: list[tuple[str, ...]] = []
    state: dict[str, Any] = {
        "findmnt": f"/srv/minecraft /dev/nvme1n1 xfs {probe.EXPECTED_FILESYSTEM_UUID}\n",
        "serial": probe.EXPECTED_DATA_VOLUME_ID.replace("-", "") + "\n",
        "usage": SimpleNamespace(f_frsize=4096, f_blocks=1000, f_bfree=200, f_bavail=180),
    }

    def run(*command: str) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = state["findmnt"] if command[0] == "findmnt" else state["serial"]
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(probe, "run", run)
    monkeypatch.setattr(os, "open", lambda *args: 77)
    monkeypatch.setattr(os, "close", lambda fd: None)
    monkeypatch.setattr(os, "fstat", lambda fd: SimpleNamespace(st_dev=259))
    original_stat = os.stat
    monkeypatch.setattr(
        os,
        "stat",
        lambda path, **kwargs: (
            SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=259)
            if path == "/dev/nvme1n1"
            else original_stat(path, **kwargs)
        ),
    )
    monkeypatch.setattr(os, "fstatvfs", lambda fd: state["usage"])
    return calls, state


def test_real_probe_uses_data_volume_serial_fd_statvfs_and_rechecks_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = setup_filesystem(monkeypatch)
    result = probe.observe_telemetry()
    assert result["state"] == "observed"
    assert result["total_bytes"] == 4096000
    assert result["used_bytes"] == 3276800
    assert result["available_bytes"] == 737280
    assert [call[0] for call in calls] == ["findmnt", "lsblk", "findmnt"]
    assert calls[1][-1] == "/dev/nvme1n1"


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("findmnt", "/ /dev/nvme0n1 xfs root-uuid\n", "MOUNT_IDENTITY_MISMATCH"),
        ("findmnt", "", "MOUNT_UNAVAILABLE"),
        ("serial", "volfffffffffffffffff\n", "VOLUME_IDENTITY_MISMATCH"),
    ],
)
def test_root_missing_mount_and_wrong_volume_never_read_capacity(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str, error: str
) -> None:
    _, state = setup_filesystem(monkeypatch)
    state[field] = value
    monkeypatch.setattr(os, "fstatvfs", lambda fd: pytest.fail("must not read wrong filesystem"))
    result = probe.observe_telemetry()
    assert result["state"] == "unknown"
    assert result["error"] == error
    assert result["used_bytes"] is None


def test_statvfs_failure_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_filesystem(monkeypatch)

    def failed(fd: int) -> None:
        raise OSError("unavailable")

    monkeypatch.setattr(os, "fstatvfs", failed)
    result = probe.observe_telemetry()
    assert result["error"] == "FILESYSTEM_OBSERVATION_FAILED"
    assert result["total_bytes"] is None


def test_mount_changes_during_sampling_invalidates_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _, state = setup_filesystem(monkeypatch)

    def changed(fd: int) -> object:
        state["findmnt"] = "/ /dev/nvme0n1 xfs other\n"
        return state["usage"]

    monkeypatch.setattr(os, "fstatvfs", changed)
    assert probe.observe_telemetry()["state"] == "unknown"


def test_v14_probe_parser_preserves_capacity_without_changing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_filesystem(monkeypatch)
    document = runtime_stopped_document()
    document["probe_version"] = "1.4.0"
    document["telemetry"] = probe.observe_telemetry()
    identity = document["identity"]
    assert isinstance(identity, dict)
    result = parse_host_runtime_probe(
        json.dumps(document), expected_instance_id=str(identity["instance_id"])
    )
    assert result.telemetry is not None
    assert result.telemetry["used_bytes"] == 3276800
    telemetry = document["telemetry"]
    assert isinstance(telemetry, dict)
    telemetry["unapproved_extra"] = "not-persisted"
    with pytest.raises(ProbeContractError, match="telemetry schema"):
        parse_host_runtime_probe(
            json.dumps(document), expected_instance_id=str(identity["instance_id"])
        )
