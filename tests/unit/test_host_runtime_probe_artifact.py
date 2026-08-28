"""Tests for the container-local Minecraft protocol observation artifact."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wishicraft.artifacts import host_runtime_probe

CONTAINER_ID = "9a83cb71c92d225eb436448dbe94eefe4e7a207ec350c967ec05e72982b0dad6"
GAME_SOURCE = "/srv/minecraft/games/game-vanilla-main/server"


def result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("docker",), returncode, stdout, stderr)


def successful_mc_monitor_json(version: str = "26.2", player_count: object = 0) -> str:
    return json.dumps(
        {
            "host": "localhost",
            "port": 25565,
            "server_info": {
                "version": {"name": version, "protocol": 772},
                "players": {
                    "max": 20,
                    "online": player_count,
                    "sample": [{"name": "must-not-propagate", "id": "private-player-id"}],
                },
                "description": {"text": "must not be propagated"},
            },
        }
    )


def container_document(
    *, game_id: object = "game-vanilla-main", source: str = GAME_SOURCE
) -> dict[str, object]:
    return {
        "Config": {
            "Labels": {
                "com.wishicraft.active-game-id": game_id,
                "com.wishicraft.active-game-data-source": GAME_SOURCE,
            }
        },
        "Mounts": [{"Type": "bind", "Source": source, "Destination": "/data"}],
    }


def test_active_game_uses_explicit_runtime_labels_and_matching_bind() -> None:
    observation = host_runtime_probe.observe_active_game(container_document())

    assert observation == {
        "state": "observed",
        "game_id": "game-vanilla-main",
        "binding_consistency": "consistent",
    }


def test_active_game_binding_mismatch_is_explicit() -> None:
    observation = host_runtime_probe.observe_active_game(
        container_document(source="/srv/minecraft/games/game-fabric-test/server")
    )

    assert observation["state"] == "observed"
    assert observation["binding_consistency"] == "mismatch"


def test_active_game_identity_must_match_declared_game_directory() -> None:
    observation = host_runtime_probe.observe_active_game(
        container_document(game_id="game-fabric-test")
    )

    assert observation["state"] == "observed"
    assert observation["game_id"] == "game-fabric-test"
    assert observation["binding_consistency"] == "mismatch"


@pytest.mark.parametrize("game_id", [None, "", "../world", "game_Invalid"])
def test_missing_or_malformed_active_game_is_unknown(game_id: object) -> None:
    observation = host_runtime_probe.observe_active_game(container_document(game_id=game_id))

    assert observation == {
        "state": "unknown",
        "game_id": None,
        "binding_consistency": "unknown",
    }


def test_active_game_probe_does_not_read_minecraft_internal_files() -> None:
    source = host_runtime_probe.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    assert "server.properties" not in text
    assert "level.dat" not in text
    assert "world/" not in text


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
    assert observation["player_count"] == 0
    assert "description" not in observation
    assert "players" not in observation
    assert state == "ready"
    assert ready is True


def test_protocol_success_normalizes_positive_player_count_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host_runtime_probe,
        "run",
        lambda *command: result(0, successful_mc_monitor_json(player_count=3)),
    )

    observation, state, ready = host_runtime_probe.observe_protocol(CONTAINER_ID)

    assert observation["player_count"] == 3
    assert "players" not in observation
    assert "sample" not in observation
    assert "must-not-propagate" not in json.dumps(observation)
    assert "private-player-id" not in json.dumps(observation)
    assert state == "ready"
    assert ready is True


@pytest.mark.parametrize("player_count", [-1, True, "0", None])
def test_malformed_player_count_is_null_without_changing_protocol_ready(
    monkeypatch: pytest.MonkeyPatch, player_count: object
) -> None:
    monkeypatch.setattr(
        host_runtime_probe,
        "run",
        lambda *command: result(0, successful_mc_monitor_json(player_count=player_count)),
    )

    observation, state, ready = host_runtime_probe.observe_protocol(CONTAINER_ID)

    assert observation["result"] == "success"
    assert observation["player_count"] is None
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
