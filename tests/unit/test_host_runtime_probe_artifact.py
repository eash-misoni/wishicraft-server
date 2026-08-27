"""Tests for the container-local Minecraft protocol observation artifact."""

from __future__ import annotations

import json
import subprocess

import pytest

from wishicraft.artifacts import host_runtime_probe

CONTAINER_ID = "9a83cb71c92d225eb436448dbe94eefe4e7a207ec350c967ec05e72982b0dad6"


def result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("docker",), returncode, stdout, stderr)


def successful_mc_monitor_json(version: str = "26.2") -> str:
    return json.dumps(
        {
            "host": "localhost",
            "port": 25565,
            "server_info": {
                "version": {"name": version, "protocol": 772},
                "players": {"max": 20, "online": 0},
                "description": {"text": "must not be propagated"},
            },
        }
    )


def test_protocol_success_uses_only_fixed_container_local_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(*command: str) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return result(0, successful_mc_monitor_json())

    monkeypatch.setattr(host_runtime_probe, "run", fake_run)

    observation, state, ready = host_runtime_probe.observe_protocol(CONTAINER_ID)

    assert calls == [
        (
            "docker",
            "exec",
            CONTAINER_ID,
            "mc-monitor",
            "status",
            "--json",
            "--host",
            "localhost",
            "--port",
            "25565",
            "--timeout",
            "3s",
        )
    ]
    assert observation["result"] == "success"
    assert observation["reported_version"] == "26.2"
    assert observation["protocol_version"] == 772
    assert "description" not in observation
    assert "players" not in observation
    assert state == "ready"
    assert ready is True


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected_result", "expected_state"),
    [
        (1, "", "failed", "not-ready"),
        (124, "", "unavailable", "unknown"),
        (127, "", "unavailable", "unknown"),
        (0, "not-json", "unknown", "unknown"),
        (0, "{}", "unknown", "unknown"),
    ],
)
def test_protocol_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected_result: str,
    expected_state: str,
) -> None:
    monkeypatch.setattr(host_runtime_probe, "run", lambda *command: result(returncode, stdout))

    observation, state, ready = host_runtime_probe.observe_protocol(CONTAINER_ID)

    assert observation["result"] == expected_result
    assert state == expected_state
    assert ready is False


def test_protocol_version_mismatch_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        host_runtime_probe,
        "run",
        lambda *command: result(0, successful_mc_monitor_json("Minecraft 26.3")),
    )

    observation, state, ready = host_runtime_probe.observe_protocol(CONTAINER_ID)

    assert observation["compatible_response"] is True
    assert observation["version_match"] is False
    assert state == "not-ready"
    assert ready is False


@pytest.mark.parametrize("reported", ["26.2", "Minecraft 26.2", "26.2 (Vanilla)"])
def test_expected_version_comparison_allows_observed_label_variants(reported: str) -> None:
    assert host_runtime_probe.version_matches_expected(reported) is True


@pytest.mark.parametrize("reported", ["26.3", "1.26.2", "26.20", "unknown"])
def test_expected_version_comparison_rejects_other_versions(reported: str) -> None:
    assert host_runtime_probe.version_matches_expected(reported) is False
