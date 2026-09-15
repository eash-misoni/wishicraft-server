"""Same old container, fresh save proof, and interrupted canonical finalization."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wishicraft import interrupted_stop_recovery as recovery
from wishicraft.artifacts import targeted_runtime as host


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    games = tmp_path / "games"
    monkeypatch.setattr(recovery, "GAMES", games)
    root, artifacts = tmp_path / "runtime", tmp_path / "artifacts"
    root.mkdir()
    artifacts.mkdir()
    for name in ("compose.yaml", "runtime.env"):
        (artifacts / name).write_text(name)
    manifest = {
        field: hashlib.sha256((artifacts / name).read_bytes()).hexdigest()
        for name, field in (
            ("compose.yaml", "compose_sha256"),
            ("runtime.env", "runtime_env_sha256"),
        )
    }
    (artifacts / "manifest.json").write_text(json.dumps(manifest))
    game_id = "game-" + "a" * 64
    data = games / game_id / "server"
    (data / "world").mkdir(parents=True)
    (data / "world/level.dat").write_bytes(b"existing saved world")
    (data / "server.properties").write_text("level-name=world\n")
    target = {
        "instance_id": "i-0123456789abcdef0",
        "game_id": game_id,
        "run_id": "op-original",
        "data_source": str(data),
        "config_digest": hashlib.sha256((artifacts / "manifest.json").read_bytes()).hexdigest(),
    }
    config = {**target, "lock_name": "global"}
    (root / "config.json").write_text(json.dumps(config))
    receipt = {"target": target, "phase": "running"}
    (root / "receipt.json").write_text(json.dumps(receipt))
    owner_path = games / (game_id + ".initial-owner.json")
    owner = {
        "phase": "prepared",
        "plan": {"game_id": game_id, "data_source": str(data)},
        "files": {"original": "hash"},
    }
    owner_path.write_text(json.dumps(owner))
    game = {
        "game_id": game_id,
        "lifecycle_state": "ACTIVE",
        "materialization_state": "UNMATERIALIZED",
        "world": {"generation": 1},
    }
    package = {"minecraft_version": "1.21.1"}
    plan = {
        "schema_version": 1,
        "target": target,
        "container_id": "c" * 64,
        "original_started_at": "old-started-at",
        "game_sha256": recovery.digest(game),
        "prepared_owner_sha256": recovery.digest(owner),
        "package_digest": recovery.digest(package),
        "world_directory_inode": (data / "world").stat().st_ino,
    }
    c: dict[str, Any] = {
        "Id": plan["container_id"],
        "Config": {
            "Labels": {
                "com.docker.compose.project": "wishicraft-host-runtime",
                "com.docker.compose.service": "minecraft",
                "com.wishicraft.run-id": target["run_id"],
                "com.wishicraft.active-game-id": game_id,
                "com.wishicraft.active-game-data-source": str(data),
            },
            "WorkingDir": "/data",
            "Entrypoint": ["/image/scripts/start"],
            "Cmd": None,
        },
        "Mounts": [{"Destination": "/data", "Type": "bind", "Source": str(data)}],
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "State": {
            "Status": "exited",
            "Running": False,
            "ExitCode": 0,
            "OOMKilled": False,
            "Error": "",
            "StartedAt": "old-started-at",
            "Health": {"Status": "healthy"},
        },
    }
    x = SimpleNamespace(
        plan=plan,
        game=game,
        owner=owner,
        owner_path=owner_path,
        root=root,
        data=data,
        containers=[c],
        calls=[],
        lock={},
        fail_after=None,
        gate_error=False,
        response="Saving the game (this may take a moment!)\n\x1b[0mSaved the game\n\x1b[0m\n",
    )

    def atomic(path: Path, value: str) -> None:
        path.write_text(value)
        phase = json.loads(value).get("phase") if path.suffix == ".json" else None
        if x.fail_after == (path.name, phase):
            x.fail_after = None
            raise RuntimeError("injected process interruption after durable write")

    def execute(args: list[str], *, timeout: int = 30) -> str:
        x.calls.append(args)
        if args[:3] == ["docker", "ps", "-aq"]:
            return "\n".join(v["Id"] for v in x.containers)
        if args[:2] == ["systemctl", "show"]:
            return "success" if "--property=Result" in args else "inactive"
        if args[:2] == ["docker", "start"]:
            c["State"].update(Running=True, Status="running", StartedAt="fresh-started-at")
            if x.fail_after == "container-start":
                x.fail_after = None
                raise RuntimeError("injected start reply loss")
        if args[-2:] == ["rcon-cli", "list"]:
            return "There are 0 of a max of 20 players online: \n\x1b[0m\n"
        if args[-2:] == ["save-all", "flush"]:
            if x.fail_after == "save-response":
                x.fail_after = None
                raise RuntimeError("injected save reply loss")
            return str(x.response)
        if args[:2] == ["docker", "stop"]:
            c["State"].update(Running=False, Status="exited")
            if x.fail_after == "graceful-stop":
                x.fail_after = None
                raise RuntimeError("injected reply loss")
        if args[:2] == ["docker", "rm"]:
            x.containers.clear()
            if x.fail_after == "container-removal":
                x.fail_after = None
                raise RuntimeError("injected reply loss")
        return ""

    def item(config: Any, table: str, key: str, identity: str) -> Any:
        if table == "locks_table":
            return x.lock
        if table == "games_table":
            return x.game
        return {"status": "FAILED", "operation_type": "START", "runtime_target": target}

    def initialized(target: Any, atomic: Any) -> None:
        atomic(owner_path, json.dumps({**owner, "phase": "initialized"}))

    def gate() -> None:
        if x.gate_error:
            raise ValueError("ACTIVE_OPERATION")

    x.gate = gate
    for k, v in {
        "ROOT": root,
        "CONFIG": root / "config.json",
        "ARTIFACTS": artifacts,
        "RUN_ENV": root / "runtime-run.env",
        "actual_instance": lambda: target["instance_id"],
        "atomic": atomic,
        "execute": execute,
        "item": item,
        "inspect": lambda: copy.deepcopy(x.containers),
        "configured_container": lambda c, m: None,
        "initial_module": lambda: SimpleNamespace(
            worlds=SimpleNamespace(record=lambda p: json.loads(p.read_text())),
            initialized=initialized,
        ),
        "package_module": lambda: SimpleNamespace(
            registered=lambda *a: package,
            digest=recovery.digest,
            observed=lambda *a: package,
            projection=lambda *a: {},
        ),
    }.items():
        monkeypatch.setattr(host, k, v)
    return x


def run(x: Any) -> None:
    recovery.recover(host, x.plan, operator_gate=x.gate, sleep=lambda _: None)


def test_fresh_proof_closes_same_container_and_preserves_unmaterialized_world(fixture: Any) -> None:
    x = fixture
    run(x)
    receipt = json.loads((x.root / "receipt.json").read_text())
    assert receipt["phase"] == "stopped"
    assert receipt["target"] == x.plan["target"]
    assert receipt["stop"]["started_at"] == "fresh-started-at"
    assert receipt["stop"]["save_confirmed"] and receipt["stop"]["removal_ready"]
    assert not x.containers
    assert x.game["materialization_state"] == "UNMATERIALIZED"
    assert x.game["world"]["generation"] == 1
    assert (x.data / "world/level.dat").read_bytes() == b"existing saved world"
    assert json.loads(x.owner_path.read_text())["plan"] == x.owner["plan"]
    effects = list(x.calls)
    run(x)
    assert not any(
        c[:2] in (["docker", "start"], ["docker", "stop"], ["docker", "rm"])
        for c in x.calls[len(effects) :]
    )


@pytest.mark.parametrize(
    "checkpoint",
    [
        ("interrupted-stop.json", "saved"),
        ("receipt.json", "stopping"),
        "graceful-stop",
        "container-removal",
        ("receipt.json", "stopped"),
    ],
)
def test_durable_boundaries_retry_without_a_second_start_or_save(
    fixture: Any, checkpoint: Any
) -> None:
    x = fixture
    x.fail_after = checkpoint
    with pytest.raises(RuntimeError, match="injected"):
        run(x)
    run(x)
    assert json.loads((x.root / "receipt.json").read_text())["phase"] == "stopped"
    assert sum(c[:2] == ["docker", "start"] for c in x.calls) == 1
    assert sum(c[-2:] == ["save-all", "flush"] for c in x.calls) == 1


def test_invalid_save_response_never_becomes_proof(fixture: Any) -> None:
    x = fixture
    x.response = "unknown response"
    with pytest.raises(ValueError, match="SAVE_RESPONSE_UNKNOWN"):
        run(x)
    assert json.loads((x.root / "receipt.json").read_text())["phase"] == "running"
    assert "proof" not in json.loads((x.root / "interrupted-stop.json").read_text())
    assert not any(c[:2] == ["docker", "rm"] for c in x.calls)


@pytest.mark.parametrize(
    "mismatch", ["run", "game", "generation", "package", "owner", "lock", "operation"]
)
def test_mismatched_identity_or_concurrency_fails_before_restart(
    fixture: Any, mismatch: str
) -> None:
    x = fixture
    if mismatch == "run":
        x.containers[0]["Config"]["Labels"]["com.wishicraft.run-id"] = "op-other"
    elif mismatch == "game":
        x.game["game_id"] = "game-other"
    elif mismatch == "generation":
        x.game["world"]["generation"] = 2
    elif mismatch == "package":
        x.plan["package_digest"] = "0" * 64
    elif mismatch == "owner":
        x.plan["prepared_owner_sha256"] = "0" * 64
    elif mismatch == "lock":
        x.lock = {"owner_operation_id": "op-other"}
    else:
        x.gate_error = True
    with pytest.raises(ValueError):
        run(x)
    assert not any(
        c[:2] in (["docker", "start"], ["docker", "stop"], ["docker", "rm"]) for c in x.calls
    )


def test_existing_canonical_proof_does_not_restart_container(fixture: Any) -> None:
    x = fixture
    proof = {
        "container_id": x.plan["container_id"],
        "started_at": "old-started-at",
        "save_confirmed": True,
        "removal_ready": False,
    }
    (x.root / "interrupted-stop.json").write_text(
        json.dumps({"plan": x.plan, "phase": "saved", "proof": proof})
    )
    run(x)
    assert not any(c[:2] == ["docker", "start"] or c[-2:] == ["save-all", "flush"] for c in x.calls)
    assert json.loads((x.root / "receipt.json").read_text())["phase"] == "stopped"


@pytest.mark.parametrize("checkpoint", ["container-start", "save-response"])
def test_uncertain_response_reobserves_old_container_and_gets_fresh_proof(
    fixture: Any, checkpoint: str
) -> None:
    x = fixture
    x.fail_after = checkpoint
    with pytest.raises(RuntimeError, match="injected"):
        run(x)
    assert json.loads((x.root / "receipt.json").read_text())["phase"] == "running"
    run(x)
    assert sum(c[:2] == ["docker", "start"] for c in x.calls) == 1
    assert json.loads((x.root / "receipt.json").read_text())["phase"] == "stopped"


def test_canonical_stopping_receipt_finalizes_without_restarting(fixture: Any) -> None:
    x = fixture
    proof = {
        "container_id": x.plan["container_id"],
        "started_at": "old-started-at",
        "save_confirmed": True,
        "removal_ready": False,
    }
    (x.root / "receipt.json").write_text(
        json.dumps({"target": x.plan["target"], "phase": "stopping", "stop": proof})
    )
    run(x)
    assert not any(c[:2] == ["docker", "start"] for c in x.calls)
