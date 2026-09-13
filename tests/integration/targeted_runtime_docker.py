"""Real pinned Minecraft/Compose lifecycle; synthetic data, systemd/AWS stand-ins only.

Run on the existing Linux Docker CI runner after its pinned-image pull.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wishicraft.artifacts import targeted_runtime as host  # noqa: E402

IMAGE = (
    "ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:"
    "6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77"
)


def main() -> None:
    creation = "--creation" in sys.argv
    reset = "--reset" in sys.argv
    two_games = "--two-games" in sys.argv or reset or creation
    root = Path(tempfile.mkdtemp(prefix="wishicraft-targeted-docker-"))
    print("fixture:", root, flush=True)
    data = root / "data"
    game_ids = ["game-ci"]
    if two_games:
        if os.environ.get("CI") != "true" or sys.platform != "linux":
            raise RuntimeError(
                "canonical-path fixture is restricted to the disposable Linux CI runner"
            )
        game_ids = [
            "game-ci-a-" + root.name.split("-")[-1].replace("_", "a"),
            "game-ci-b-" + root.name.split("-")[-1].replace("_", "a"),
        ]
        for game in game_ids:
            directory = Path("/srv/minecraft/games") / game / "server"
            assert not directory.exists()
            subprocess.run(
                [
                    "sudo",
                    "install",
                    "-d",
                    "-m",
                    "0777",
                    "-o",
                    str(os.getuid()),
                    "-g",
                    str(os.getgid()),
                    str(directory),
                ],
                check=True,
            )
            marker = directory.parent / ".wishicraft-initialization.json"
            marker.write_text(json.dumps({"game_id": game, "phase": "prepared"}))
            marker.chmod(0o600)
        if reset:
            for game in game_ids:
                (Path("/srv/minecraft/games") / game).chmod(0o755)
        data = Path("/srv/minecraft/games") / game_ids[0] / "server"
    if not two_games:
        data.mkdir()
    data.chmod(0o777)
    (data / "sentinel").write_text("existing data outside the container layer")
    artifacts = root / "artifacts"
    artifacts.mkdir()
    environment = (
        "EULA=TRUE\nTYPE=VANILLA\nVERSION=26.2\nUID=993\nGID=993\n"
        "INIT_MEMORY=1G\nMAX_MEMORY=2G\nENABLE_RCON=true\n"
        "RCON_PASSWORD=synthetic-ci-only\nSTOP_DURATION=120\n"
    )
    (artifacts / "runtime.env").write_text(environment)
    compose = f"""name: wishicraft-host-runtime
services:
  minecraft:
    image: {IMAGE}
    pull_policy: never
    restart: "no"
    env_file: [runtime.env]
    stop_grace_period: 150s
    volumes:
      - {data}:/data
    labels:
      com.wishicraft.run-id: ${{WISHICRAFT_RUN_ID:?targeted START required}}
      com.wishicraft.active-game-id: game-ci
      com.wishicraft.active-game-data-source: {data}
"""
    (artifacts / "compose.yaml").write_text(compose)
    if two_games:
        compose = compose.replace(str(data), "${GAME_DIRECTORY:?targeted Game required}").replace(
            "game-ci\n", "${WISHICRAFT_GAME_ID:?targeted Game required}\n"
        )
        (artifacts / "compose.yaml").write_text(compose)
    manifest: dict[str, Any] = {
        "image": IMAGE,
        "compose_sha256": hashlib.sha256(compose.encode()).hexdigest(),
        "runtime_env_sha256": hashlib.sha256(environment.encode()).hexdigest(),
    }
    if two_games:
        manifest["games"] = game_ids
    manifest_bytes = json.dumps(manifest).encode()
    (artifacts / "manifest.json").write_bytes(manifest_bytes)
    target = {
        "instance_id": "i-0123456789abcdef0",
        "game_id": game_ids[0],
        "data_source": str(data),
        "config_digest": hashlib.sha256(manifest_bytes).hexdigest(),
        "run_id": "op-first",
    }
    config: dict[str, Any] = {**target, "system_id": "ci-only", "lock_name": "ci-only"}
    if two_games:
        config["games"] = game_ids
    if reset:
        config["reset_policies"] = {
            game_ids[0]: {"fixed_seed": 0, "retain_previous": 1, "minimum_free_bytes": 1073741824}
        }
    host.ROOT = root
    host.CONFIG = root / "config.json"
    host.CONFIG.write_text(json.dumps(config))
    host.ARTIFACTS = artifacts
    host.RUN_ENV = root / "runtime-run.env"
    host.actual_instance = lambda: target["instance_id"]
    operation: dict[str, Any] = {
        "operation_id": "op-first",
        "lease_id": "lease-ci",
        "operation_type": "START",
        "status": "RUNNING",
        "timeout_at": "2099-01-01T00:00:00Z",
        "runtime_target": target,
        "target_game_id": game_ids[0],
    }
    lease = {
        "owner_operation_id": "op-first",
        "lease_id": "lease-ci",
        "resource_id": "ci-only",
        "lease_expires_at": 4070908800,
    }
    host.item = lambda config, table, key, identity: (
        operation if table == "operations_table" else lease
    )
    real_execute = host.execute
    state: dict[str, Any] = {"unit": "inactive", "stop_observations": 0, "lose_removal": False}

    def compose_command(action: list[str]) -> None:
        env = dict(os.environ)
        env.update(dict(line.split("=", 1) for line in host.RUN_ENV.read_text().splitlines()))
        subprocess.run(
            ["docker", "compose", "--file", str(artifacts / "compose.yaml"), *action],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=210,
        )

    def execute(args: list[str], *, timeout: int = 30) -> str:
        if creation and args == [
            "bash",
            "-c",
            'set -aeu; source /etc/wishicraft/host-runtime.env; "$MOUNT_GUARD" --verify',
        ]:
            assert Path("/srv/minecraft/games").is_dir()
            return ""
        if args[0] == "bash":
            # Exercise the real Compose parsing done by the host filesystem preflight.
            # Platform mount/ownership checks remain replaced by this synthetic boundary.
            expected = (
                operation["switch_source"]
                if operation.get("operation_type") == "RESET"
                and not Path(target["data_source"]).exists()
                else target
            )
            assert args[-4:] == [
                "wishicraft-preflight",
                expected["run_id"],
                expected["game_id"],
                expected["data_source"],
            ]
            assert 'export WISHICRAFT_RUN_ID="$1"' in args[2]
            env = dict(
                os.environ,
                WISHICRAFT_RUN_ID=args[-3],
                WISHICRAFT_GAME_ID=args[-2],
                GAME_DIRECTORY=args[-1],
            )
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--file",
                    str(artifacts / "compose.yaml"),
                    "ps",
                    "--status",
                    "running",
                    "--quiet",
                    "minecraft",
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            print("REAL_PREFLIGHT_COMPOSE_RESOLVED", args[-1], flush=True)
            return ""
        if args[0].endswith(("/rcon-secret-v1", "/rcon-secret-v2")):
            return ""
        if args[:2] == ["systemctl", "show"]:
            return "success" if "--property=Result" in args else str(state["unit"])
        if args[:2] == ["systemctl", "start"]:
            compose_command(["up", "--detach", "--no-build", "--pull", "never"])
            state["unit"] = "active"
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                current = host.inspect()
                if current:
                    try:
                        real_execute(["docker", "exec", current[0]["Id"], "rcon-cli", "list"])
                        return ""
                    except RuntimeError:
                        pass
                time.sleep(2)
            raise RuntimeError("synthetic Minecraft readiness timeout")
        if args[:2] == ["systemctl", "stop"]:
            before = host.inspect()[0]["Id"]
            compose_command(["stop", "--timeout", "150"])
            state["unit"] = "inactive"
            stopped = host.inspect()
            assert len(stopped) == 1 and stopped[0]["Id"] == before
            assert not stopped[0]["State"]["Running"]
            state["stop_observations"] += 1
            print("REAL_COMPOSE_STOP_RETAINS", before, flush=True)
            print(
                "PINNED_CONTAINER_CONFIG",
                json.dumps(
                    {
                        key: stopped[0]["Config"].get(key)
                        for key in ("Image", "WorkingDir", "Entrypoint", "Cmd")
                    }
                ),
                flush=True,
            )
            print("STOPPED_STATE", json.dumps(stopped[0]["State"]), flush=True)
            return ""
        result = real_execute(args, timeout=timeout)
        if args[:2] == ["docker", "rm"] and state["lose_removal"]:
            state["lose_removal"] = False
            raise TimeoutError("real rm succeeded; injected lost reply")
        return result

    missing_env = dict(os.environ)
    missing_env.pop("WISHICRAFT_RUN_ID", None)
    missing_env.update(WISHICRAFT_GAME_ID=target["game_id"], GAME_DIRECTORY=target["data_source"])
    missing = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            str(artifacts / "compose.yaml"),
            "ps",
            "--status",
            "running",
            "--quiet",
            "minecraft",
        ],
        env=missing_env,
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0 and "WISHICRAFT_RUN_ID" in missing.stderr
    print("REAL_PREFLIGHT_REJECTS_MISSING_RUN", flush=True)
    host.execute = execute
    assert not host.inspect(), "preexisting project: refuse to touch it"
    container_ids = []
    b_saved: dict[str, str] = {}
    for index in range(1 if reset else (3 if two_games else 2)):
        if two_games:
            game_id = game_ids[index % 2]
            data = Path("/srv/minecraft/games") / game_id / "server"
            target = {**target, "game_id": game_id, "data_source": str(data)}
            if index == 1:
                (data / "sentinel").write_text("existing data outside the container layer")
        operation["runtime_target"] = target
        operation["target_game_id"] = target["game_id"]
        operation["operation_id"] = target["run_id"] = f"op-start-{index}"
        lease["owner_operation_id"] = operation["operation_id"]
        operation["operation_type"] = "SWITCH" if two_games and index > 0 else "START"
        request = {
            "schema_version": 2,
            "operation_id": operation["operation_id"],
            "lease_id": "lease-ci",
            "action": "START",
        }
        host.apply(request)
        container = host.inspect()[0]
        assert container["Id"] not in container_ids
        container_ids.append(container["Id"])
        host.validate_container(container, target)
        if index == 0 or (two_games and index == 1):
            real_execute(
                [
                    "docker",
                    "exec",
                    container["Id"],
                    "rcon-cli",
                    "scoreboard",
                    "objectives",
                    "add",
                    "restore_ci",
                    "dummy",
                ]
            )
            real_execute(
                [
                    "docker",
                    "exec",
                    container["Id"],
                    "rcon-cli",
                    "scoreboard",
                    "players",
                    "set",
                    "sentinel",
                    "restore_ci",
                    str(42 + index),
                ]
            )
        else:
            result = real_execute(
                [
                    "docker",
                    "exec",
                    container["Id"],
                    "rcon-cli",
                    "scoreboard",
                    "players",
                    "get",
                    "sentinel",
                    "restore_ci",
                ]
            )
            assert "42" in result, result
        operation["operation_type"] = request["action"] = "STOP"
        if two_games and index < 2 and not reset:
            operation["switch_source"] = dict(target)
            destination_game = game_ids[(index + 1) % 2]
            operation["runtime_target"] = {
                **target,
                "game_id": destination_game,
                "data_source": f"/srv/minecraft/games/{destination_game}/server",
                "run_id": f"op-start-{index + 1}",
            }
            operation["target_game_id"] = destination_game
            operation["operation_type"] = "SWITCH"
            operation["operation_id"] = request["operation_id"] = lease["owner_operation_id"] = (
                f"op-start-{index + 1}"
            )
        state["lose_removal"] = index == 1
        try:
            host.apply(request)
        except TimeoutError:
            assert index == 1 and not host.inspect()
            assert json.loads((root / "receipt.json").read_text())["phase"] == "stopping"
            host.apply(request)
        assert not host.inspect() and state["unit"] == "inactive"
        assert json.loads((root / "receipt.json").read_text())["phase"] == "stopped"
        assert (data / "world/level.dat").is_file()
        assert (data / "world/players/data").is_dir()  # Synthetic world; no human player claim.
        assert (data / "sentinel").read_text() == "existing data outside the container layer"
        if two_games and index == 1:
            b_saved = {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (data / "world").rglob("*")
                if p.is_file()
            }
    if two_games and not reset:
        assert b_saved and all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
            for p, digest in b_saved.items()
        )
        print("B saved world unchanged during A restart", flush=True)
    assert len(set(container_ids)) == len(container_ids)
    assert state["stop_observations"] == (1 if reset else (3 if two_games else 2))
    print(
        "PASS real v2 START/STOP/new-run START, saved scoreboard=42, rm reply loss, bind preserved"
    )
    if creation:
        from datetime import UTC, datetime

        from web.local_operations import MemoryDynamo, service
        from wishicraft.game_creation import create
        from wishicraft.operation import WebOperationContext
        from wishicraft.web_status import decode

        db = MemoryDynamo()
        domain = service(db)
        config.update(
            game_creation=True, games_table="games", reset_policies={}, initial_whitelist=[]
        )
        host.CONFIG.write_text(json.dumps(config))
        host.item = lambda config, table, key, identity: (
            {k: decode(v) for k, v in db.records["games", identity].items()}
            if table == "games_table"
            else operation
            if table == "operations_table"
            else lease
        )
        for number in range(2):
            created_result = create(
                domain._repository,
                value={
                    "display_name": "CI persistent synthetic fixture",
                    "seed": "42",
                    "reset": True,
                },
                key="web:" + hashlib.sha256((root.name + str(number)).encode()).hexdigest(),
                actor=WebOperationContext("9", "CI", "a" * 64, "b" * 64),
                now=datetime.now(UTC),
                defaults={
                    "package": {
                        "package_id": "vanilla",
                        "package_version": "initial-fixed-version",
                    },
                    "runtime": {"class": "default", "idle_shutdown_minutes": 30},
                    "config_digest": target["config_digest"],
                },
            )
            game_id = db.records["operation", str(created_result["operation_id"])][
                "target_game_id"
            ]["S"]
            destination = Path("/srv/minecraft/games") / game_id / "server"
            assert not destination.exists(), "CREATE must not materialize"
            source = dict(target)
            target = {
                **target,
                "game_id": game_id,
                "data_source": str(destination),
                "run_id": f"op-create-start-{number}",
            }
            operation.update(
                operation_id=target["run_id"],
                operation_type="SWITCH" if number else "START",
                target_game_id=game_id,
                runtime_target=target,
            )
            lease["owner_operation_id"] = target["run_id"]
            request.update(operation_id=target["run_id"], action="START")
            if number:
                operation["switch_source"] = source
                destination_target = target
                target = source
                request["action"] = "STOP"
                host.apply(request)
                target = destination_target
                request["action"] = "START"
            host.apply(request)
            host.apply(request)  # Same target/run and same initial owner, no second directory.
            current = host.inspect()[0]
            assert "42" in real_execute(["docker", "exec", current["Id"], "rcon-cli", "seed"])
            assert destination.joinpath("world/level.dat").is_file()
            print("CREATE_FIRST_MATERIALIZED", number, game_id, flush=True)
        operation["operation_type"] = request["action"] = "STOP"
        host.apply(request)
        target = {**target, "run_id": "op-created-restart"}
        operation.update(
            operation_id=target["run_id"], operation_type="START", runtime_target=target
        )
        lease["owner_operation_id"] = target["run_id"]
        request.update(operation_id=target["run_id"], action="START")
        host.apply(request)
        operation["operation_type"] = request["action"] = "STOP"
        host.apply(request)
        assert b_saved and all(
            hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
            for p, digest in b_saved.items()
        )
        print(
            "PASS metadata CREATE / first START / first SWITCH / retry / STOP / restart / "
            "A-B noninterference",
            flush=True,
        )
    if reset:
        # The existing adapter performs every real Docker save/stop/removal/start below.
        anchor = data
        target = {**target, "run_id": "op-reset-source"}
        operation.update(
            operation_id=target["run_id"], operation_type="START", runtime_target=target
        )
        lease["owner_operation_id"] = target["run_id"]
        request.update(operation_id=target["run_id"], action="START")
        host.apply(request)
        for number in range(3):
            source = dict(target)
            destination = anchor.parent / "worlds" / f"op-reset-{number}" / "server"
            target = {**source, "data_source": str(destination), "run_id": f"op-reset-{number}"}
            plan = {
                "schema_version": 1,
                "source": source,
                "target": target,
                "seed": 100 + number,
                "policy": config["reset_policies"][game_ids[0]],
            }
            operation.update(
                operation_id=target["run_id"],
                operation_type="RESET",
                runtime_target=target,
                switch_source=source,
                reset_plan=json.dumps(plan),
            )
            lease["owner_operation_id"] = target["run_id"]
            request.update(operation_id=target["run_id"], action="STOP")
            # The preflight is source-bound during STOP, destination-bound during START.
            target_for_start = target
            target = source
            host.apply(request)
            target = target_for_start
            request["action"] = "RESET_PREPARE"
            host.apply(request)
            assert not (destination / "world").exists()
            request["action"] = "START"
            host.apply(request)
            current = host.inspect()[0]
            assert current["Id"] not in container_ids
            container_ids.append(current["Id"])
            seed_observed = real_execute(["docker", "exec", current["Id"], "rcon-cli", "seed"])
            assert str(100 + number) in seed_observed, seed_observed
            absent = real_execute(
                ["docker", "exec", current["Id"], "rcon-cli", "scoreboard", "objectives", "list"]
            )
            assert "restore_ci" not in absent
            real_execute(
                [
                    "docker",
                    "exec",
                    current["Id"],
                    "rcon-cli",
                    "scoreboard",
                    "objectives",
                    "add",
                    "reset_ci",
                    "dummy",
                ]
            )
            real_execute(
                [
                    "docker",
                    "exec",
                    current["Id"],
                    "rcon-cli",
                    "scoreboard",
                    "players",
                    "set",
                    "sentinel",
                    "reset_ci",
                    str(100 + number),
                ]
            )
            request["action"] = "RESET_CLEANUP"
            host.apply(request)
            print("REAL_RESET_READY", number, current["Id"], str(destination), flush=True)
        assert (anchor / "world/level.dat").is_file()
        assert not (anchor.parent / "worlds/op-reset-0/server").exists()
        assert (anchor.parent / "worlds/op-reset-1/server/world/level.dat").is_file()
        operation.update(operation_type="STOP")
        request["action"] = "STOP"
        host.apply(request)
        target = {**target, "run_id": "op-reset-normal-start"}
        operation.update(
            operation_id=target["run_id"], operation_type="START", runtime_target=target
        )
        lease["owner_operation_id"] = target["run_id"]
        request.update(operation_id=target["run_id"], action="START")
        host.apply(request)
        current = host.inspect()[0]
        saved = real_execute(
            [
                "docker",
                "exec",
                current["Id"],
                "rcon-cli",
                "scoreboard",
                "players",
                "get",
                "sentinel",
                "reset_ci",
            ]
        )
        assert "102" in saved
        operation["operation_type"] = request["action"] = "STOP"
        host.apply(request)
        assert not host.inspect()
        print(
            "PASS real Reset generation/seed/config/old retention/exact cleanup/"
            "normal restart saved=102",
            flush=True,
        )
    # Containers have already been removed by the real adapter. Keep runner-local evidence.


if __name__ == "__main__":
    main()
