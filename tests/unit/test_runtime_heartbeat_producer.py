from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wishicraft import runtime_heartbeat_producer as producer
from wishicraft.runtime_heartbeat import ProtocolState, RuntimeHeartbeat, derive_heartbeat

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def record() -> RuntimeHeartbeat:
    return RuntimeHeartbeat(
        system_id="wishicraft-main",
        schema_version=1,
        instance_id="i-04fc0629dc4ea466e",
        runtime_id="wishicraft-host-runtime",
        boot_id="12345678-1234-1234-1234-123456789abc",
        active_game_id="game-vanilla-main",
        protocol_state=ProtocolState.READY,
        player_count=0,
        empty_since=NOW,
        observed_at=NOW,
        expires_at=int(NOW.timestamp()) + 86_400,
    )


def test_save_is_whole_record_conditional_put_with_no_update_or_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(0, "{}")

    monkeypatch.setattr(producer, "run", fake_run)
    assert producer.save(
        record(), table="wc-dev-runtime-heartbeats", region="ap-northeast-1", previous=None
    )
    command = calls[0]
    assert command[:3] == ["aws", "dynamodb", "put-item"]
    assert "update-item" not in command
    condition = command[command.index("--condition-expression") + 1]
    assert "attribute_not_exists(system_id)" in condition
    assert "observed_at < :new" in condition


def test_conditional_conflict_is_safe_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    def conflict(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return completed(254, stderr="ConditionalCheckFailedException")

    monkeypatch.setattr(producer, "run", conflict)
    assert not producer.save(
        record(), table="wc-dev-runtime-heartbeats", region="ap-northeast-1", previous=None
    )


def test_observation_failure_does_not_write_or_stop_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("RUNTIME_HEARTBEATS_TABLE", "wc-dev-runtime-heartbeats")
    monkeypatch.setenv("SYSTEM_ID", "wishicraft-main")
    monkeypatch.setenv("GAME_ID", "game-vanilla-main")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(producer, "load_previous", lambda **kwargs: None)
    monkeypatch.setattr(
        producer,
        "observe",
        lambda **kwargs: (_ for _ in ()).throw(producer.ProducerError("PROBE_FAILED")),
    )

    def unexpected_run(
        command: list[str], *, timeout: int = 15
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return completed(0)

    monkeypatch.setattr(producer, "run", unexpected_run)
    assert producer.main() == 1
    assert calls == []


def test_decode_round_trip_preserves_boot_and_empty_identity() -> None:
    assert producer._decode(producer._encode(record())) == record()


def test_empty_get_item_output_is_an_absent_previous_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(producer, "run", lambda command: completed(0, ""))
    assert (
        producer.load_previous(
            table="wc-dev-runtime-heartbeats",
            system_id="wishicraft-main",
            region="ap-northeast-1",
        )
        is None
    )


def test_probe_game_mismatch_becomes_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload: dict[str, Any] = {
        "identity": {"instance_id": "i-04fc0629dc4ea466e", "runtime_id": "wishicraft-host-runtime"},
        "active_game": {
            "state": "observed",
            "game_id": "game-other",
            "binding_consistency": "mismatch",
        },
        "minecraft": {"protocol_state": "ready", "protocol": {"player_count": 0}},
        "errors": [],
    }
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("12345678-1234-1234-1234-123456789abc\n")
    monkeypatch.setattr(producer, "BOOT_ID_PATH", boot_id)
    monkeypatch.setattr(producer, "run", lambda command: completed(0, json.dumps(payload)))
    value = producer.observe(now=NOW)
    assert value.active_game_id is None
    assert value.player_count is None
    assert value.protocol_state is ProtocolState.UNKNOWN
    # Domain derivation converts this unbound observation to unknown/null empty state.


@pytest.mark.parametrize(
    ("game_id", "players"),
    [
        ("game-vanilla-main", 0),
        ("game-vanilla-secondary", 3),
        ("game-" + "a" * 64, 0),
        ("game-" + "b" * 64, 4),
    ],
)
def test_registered_run_identity_is_not_limited_to_legacy_games(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, game_id: str, players: int
) -> None:
    payload = {
        "identity": {"instance_id": record().instance_id, "runtime_id": record().runtime_id},
        "active_game": {
            "state": "observed",
            "game_id": game_id,
            "binding_consistency": "consistent",
        },
        "minecraft": {"protocol_state": "ready", "protocol": {"player_count": players}},
        "execution": {
            "phase": "running",
            "process_id": "d" * 64,
            "target": {
                "game_id": game_id,
                "run_id": "op-new-run",
                "config_digest": "e" * 64,
                "data_source": f"/srv/minecraft/games/{game_id}/server",
            },
        },
        "errors": [],
    }
    boot_id = tmp_path / "boot_id"
    boot_id.write_text(record().boot_id)
    monkeypatch.setattr(producer, "BOOT_ID_PATH", boot_id)
    monkeypatch.setattr(producer, "run", lambda command: completed(0, json.dumps(payload)))
    monkeypatch.setenv("RUNTIME_HEARTBEATS_TABLE", "wc-dev-runtime-heartbeats")
    monkeypatch.setenv("SYSTEM_ID", "wishicraft-main")
    monkeypatch.setenv("GAME_ID", "game-vanilla-main")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    monkeypatch.setattr(producer, "load_previous", lambda **kwargs: None)
    written: list[RuntimeHeartbeat] = []

    def fake_save(value: RuntimeHeartbeat, **kwargs: object) -> bool:
        written.append(value)
        return True

    monkeypatch.setattr(producer, "save", fake_save)

    assert producer.produce_once(now=NOW)
    assert written[0].active_game_id == game_id
    assert written[0].player_count == players
    assert written[0].protocol_state is ProtocolState.READY
    assert (written[0].empty_since is not None) == (players == 0)
    assert producer._decode(producer._encode(written[0])) == written[0]


@pytest.mark.parametrize("mismatch", ["game", "path", "run", "process", "observation"])
def test_untrusted_run_or_player_observation_never_becomes_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mismatch: str
) -> None:
    game_id = "game-" + "c" * 64
    payload: dict[str, Any] = {
        "identity": {"instance_id": record().instance_id, "runtime_id": record().runtime_id},
        "active_game": {
            "state": "observed",
            "game_id": game_id,
            "binding_consistency": "consistent",
        },
        "minecraft": {"protocol_state": "ready", "protocol": {"player_count": 0}},
        "execution": {
            "phase": "running",
            "process_id": "d" * 64,
            "target": {
                "game_id": game_id,
                "run_id": "op-new-run",
                "config_digest": "e" * 64,
                "data_source": f"/srv/minecraft/games/{game_id}/server",
            },
        },
        "errors": [],
    }
    if mismatch == "game":
        payload["execution"]["target"]["game_id"] = "game-other"
    elif mismatch == "path":
        payload["execution"]["target"]["data_source"] = "/srv/minecraft/games/game-other/server"
    elif mismatch == "run":
        payload["execution"]["target"]["run_id"] = "invalid"
    elif mismatch == "process":
        payload["execution"]["process_id"] = "invalid"
    else:
        payload["minecraft"]["protocol"]["player_count"] = None
    boot_id = tmp_path / "boot_id"
    boot_id.write_text(record().boot_id)
    monkeypatch.setattr(producer, "BOOT_ID_PATH", boot_id)
    monkeypatch.setattr(producer, "run", lambda command: completed(0, json.dumps(payload)))
    observation = producer.observe(now=NOW)
    if mismatch != "observation":
        assert observation.active_game_id is None
        assert observation.protocol_state is ProtocolState.UNKNOWN
    value = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id=game_id,
        observation=observation,
        previous=None,
    )
    assert value.player_count is None
    assert value.empty_since is None
