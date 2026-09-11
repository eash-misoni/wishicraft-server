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
from wishicraft.artifacts import targeted_runtime as host  # noqa: E402

IMAGE = (
    "ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:"
    "6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77"
)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wishicraft-targeted-docker-"))
    print("fixture:", root, flush=True)
    data = root / "data"
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
      com.wishicraft.run-id: ${{WISHICRAFT_RUN_ID}}
      com.wishicraft.active-game-id: game-ci
      com.wishicraft.active-game-data-source: {data}
"""
    (artifacts / "compose.yaml").write_text(compose)
    manifest = {
        "image": IMAGE,
        "compose_sha256": hashlib.sha256(compose.encode()).hexdigest(),
        "runtime_env_sha256": hashlib.sha256(environment.encode()).hexdigest(),
    }
    manifest_bytes = json.dumps(manifest).encode()
    (artifacts / "manifest.json").write_bytes(manifest_bytes)
    target = {
        "instance_id": "i-0123456789abcdef0",
        "game_id": "game-ci",
        "data_source": str(data),
        "config_digest": hashlib.sha256(manifest_bytes).hexdigest(),
        "run_id": "op-first",
    }
    config = {**target, "system_id": "ci-only", "lock_name": "ci-only"}
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
        "target_game_id": "game-ci",
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
        if args[0] == "bash" or args[0].endswith("/rcon-secret-v1"):
            # No production filesystem/secret paths or credentials on this runner.
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
            return ""
        result = real_execute(args, timeout=timeout)
        if args[:2] == ["docker", "rm"] and state["lose_removal"]:
            state["lose_removal"] = False
            raise TimeoutError("real rm succeeded; injected lost reply")
        return result

    host.execute = execute
    assert not host.inspect(), "preexisting project: refuse to touch it"
    for index in range(2):
        operation["operation_id"] = target["run_id"] = f"op-start-{index}"
        lease["owner_operation_id"] = operation["operation_id"]
        operation["operation_type"] = "START"
        request = {
            "schema_version": 2,
            "operation_id": operation["operation_id"],
            "lease_id": "lease-ci",
            "action": "START",
        }
        host.apply(request)
        container = host.inspect()[0]
        host.validate_container(container, target)
        if index == 0:
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
                    "42",
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
        assert (data / "world/playerdata").is_dir()  # Synthetic world; no human player claim.
        assert (data / "sentinel").read_text() == "existing data outside the container layer"
    assert state["stop_observations"] == 2
    print(
        "PASS real v2 START/STOP/new-run START, saved scoreboard=42, rm reply loss, bind preserved"
    )
    # Containers have already been removed by the real adapter. Keep runner-local evidence.


if __name__ == "__main__":
    main()
