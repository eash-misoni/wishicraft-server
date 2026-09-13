"""Host-only v2 boundary. Root-owned fixed paths; no caller paths or shell commands."""

# ruff: noqa: UP045, UP017 -- AL2023 Python 3.9
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/var/lib/wishicraft/runtime")
CONFIG = Path("/etc/wishicraft/runtime-contract.json")
ARTIFACTS = Path("/etc/wishicraft/host-runtime")
UNIT = "wishicraft-host-runtime.service"
RUN_ENV = Path("/run/wishicraft/runtime-run.env")


def execute(args: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("HOST_COMMAND_FAILED")
    return result.stdout


def atomic(path: Path, value: str) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".runtime-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def item(config: dict[str, Any], table: str, key: str, identity: str) -> dict[str, Any]:
    raw = json.loads(
        execute(
            [
                "aws",
                "dynamodb",
                "get-item",
                "--region",
                config["region"],
                "--table-name",
                config[table],
                "--consistent-read",
                "--key",
                json.dumps({key: {"S": identity}}),
                "--output",
                "json",
            ]
        )
    )["Item"]

    def decode(value: dict[str, Any]) -> Any:
        if "S" in value:
            return value["S"]
        if "N" in value:
            return int(value["N"])
        if "M" in value:
            return {k: decode(v) for k, v in value["M"].items()}
        if value.get("NULL"):
            return None
        return value

    return {k: decode(v) for k, v in raw.items()}


def authorize(
    request: dict[str, Any],
    operation: dict[str, Any],
    lease: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
) -> dict[str, str]:
    if set(request) != {"schema_version", "operation_id", "lease_id", "action"}:
        raise ValueError("REQUEST_SCHEMA")
    if request["schema_version"] != 2 or request["action"] not in {
        "START",
        "STOP",
        "RESET_PREPARE",
        "RESET_CLEANUP",
    }:
        raise ValueError("REQUEST_VERSION")
    if (
        operation["operation_id"] != request["operation_id"]
        or operation["lease_id"] != request["lease_id"]
        or operation["operation_type"] not in {request["action"], "SWITCH", "RESET"}
        or operation["status"] != "RUNNING"
        or datetime.fromisoformat(operation["timeout_at"].replace("Z", "+00:00")) <= now
        or lease["owner_operation_id"] != request["operation_id"]
        or lease["lease_id"] != request["lease_id"]
        or lease["resource_id"] != config["system_id"]
        or lease["lease_expires_at"] <= int(now.timestamp())
    ):
        raise ValueError("STALE_OPERATION")
    resetting = operation["operation_type"] == "RESET"
    if request["action"].startswith("RESET_") and not resetting:
        raise ValueError("RESET_OPERATION_REQUIRED")
    if resetting:
        plan = json.loads(operation["reset_plan"])
        if (
            config.get("reset_policies", {}).get(operation["target_game_id"]) != plan["policy"]
            or plan["source"] != operation["switch_source"]
            or plan["target"] != operation["runtime_target"]
            or plan["target"]["run_id"] != operation["operation_id"]
            or plan["source"]["game_id"] != plan["target"]["game_id"]
        ):
            raise ValueError("RESET_PLAN_MISMATCH")
    switching = operation["operation_type"] in {"SWITCH", "RESET"}
    if switching and "games" not in config:
        raise ValueError("SWITCH_NOT_CONFIGURED")
    target = (
        operation["switch_source"]
        if switching and request["action"] == "STOP"
        else operation["runtime_target"]
    )
    for name in ("instance_id", "config_digest"):
        if target[name] != config[name]:
            raise ValueError("TARGET_MISMATCH")
    if "games" in config:
        if (
            target["game_id"] not in config["games"]
            and not (
                config.get("game_creation") is True
                and re.fullmatch(r"game-[0-9a-f]{64}", target["game_id"])
            )
        ) or re.fullmatch(
            re.escape("/srv/minecraft/games/" + target["game_id"] + "/")
            + (
                r"(?:worlds/op-[a-z0-9-]{1,100}/)?server"
                if "reset_policies" in config
                else "server"
            ),
            target["data_source"],
        ) is None:
            raise ValueError("TARGET_MISMATCH")
    elif target["game_id"] != config["game_id"] or target["data_source"] != config["data_source"]:
        raise ValueError("TARGET_MISMATCH")
    if operation["target_game_id"] != operation["runtime_target"]["game_id"]:
        raise ValueError("GAME_MISMATCH")
    if re.fullmatch(r"op-[a-z0-9-]+", target["run_id"]) is None:
        raise ValueError("INVALID_RUN_ID")
    return dict(target)


def inspect() -> list[dict[str, Any]]:
    ids = execute(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=wishicraft-host-runtime",
        ]
    ).split()
    if len(ids) > 1:
        raise ValueError("MULTIPLE_CONTAINERS")
    return json.loads(execute(["docker", "inspect", ids[0]])) if ids else []


def validate_container(container: dict[str, Any], target: dict[str, str]) -> None:
    labels = container["Config"]["Labels"]
    binds = [m for m in container["Mounts"] if m["Destination"] == "/data"]
    if (
        labels.get("com.docker.compose.project") != "wishicraft-host-runtime"
        or labels.get("com.docker.compose.service") != "minecraft"
        or labels.get("com.wishicraft.run-id") != target["run_id"]
        or labels.get("com.wishicraft.active-game-id") != target["game_id"]
        or labels.get("com.wishicraft.active-game-data-source") != target["data_source"]
        or len(binds) != 1
        or binds[0]["Type"] != "bind"
        or binds[0]["Source"] != target["data_source"]
    ):
        raise ValueError("CONTAINER_TARGET_MISMATCH")


def validate_persistence(container: dict[str, Any], target: dict[str, str]) -> None:
    """Pinned vanilla /image/scripts/start stores world, players and configuration under /data."""
    data = Path(target["data_source"])
    config = container["Config"]
    if (
        config.get("WorkingDir") != "/data"
        or config.get("Entrypoint") != ["/image/scripts/start"]
        or config.get("Cmd") not in (None, [])
        or any(
            m["Destination"].startswith("/data/")
            and (m["Destination"], m["Type"], m["Source"])
            not in {
                ("/data/.rcon-cli.env", "bind", "/run/wishicraft/rcon-cli.env"),
                ("/data/.rcon-cli.yaml", "bind", "/run/wishicraft/rcon-cli.yaml"),
            }
            for m in container["Mounts"]
        )
        or data.is_symlink()
        or not data.is_dir()
    ):
        raise ValueError("PERSISTENCE_UNPROVEN")
    # No custom world path or symlink may redirect persistent data into the image layer.
    properties = (data / "server.properties").read_text()
    levels = [
        line.partition("=")[2] for line in properties.splitlines() if line.startswith("level-name=")
    ]
    if levels != ["world"] or not (data / "world/level.dat").is_file():
        raise ValueError("PERSISTENCE_UNPROVEN")
    for path in data.rglob("*"):
        if path.is_symlink() and data.resolve() not in path.resolve().parents:
            raise ValueError("PERSISTENCE_UNPROVEN")


def stopped_environment() -> None:
    for field, expected in [("ActiveState", "inactive"), ("Result", "success")]:
        if (
            execute(["systemctl", "show", UNIT, "--property=" + field, "--value"]).strip()
            != expected
        ):
            raise ValueError("STOP_RESULT_UNKNOWN")
    for port in ("25565", "25575"):
        if execute(["ss", "-H", "-ltn", "sport = :" + port]).strip():
            raise ValueError("STOP_LISTENER_REMAINS")


def initial_world_permission(target: dict[str, str], *, stopped: bool = False) -> Path:
    path = Path(target["data_source"]).parent / ".wishicraft-initialization.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("EXISTING_WORLD_MISSING")
    info = path.stat()
    document = json.loads(path.read_text())
    phases = ("prepared", "initialized") if stopped else ("prepared",)
    if (
        info.st_uid != 0
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
        or document not in [{"game_id": target["game_id"], "phase": phase} for phase in phases]
    ):
        raise ValueError("INITIAL_WORLD_PERMISSION_INVALID")
    return path


def finish_stop(
    receipt_path: Path, receipt: dict[str, Any], target: dict[str, str], manifest: dict[str, Any]
) -> None:
    """Caller holds the host lock. A durable removal intent closes rm reply loss."""
    stopped_environment()
    current = inspect()
    proof = receipt.get("stop", {})
    if current:
        container = current[0]
        validate_container(container, target)
        configured_container(container, manifest)
        state = container["State"]
        if (
            receipt["phase"] != "stopping"
            or proof.get("save_confirmed") is not True
            or proof.get("container_id") != container["Id"]
            or re.fullmatch(r"[0-9a-f]{64}", container["Id"]) is None
            or proof.get("started_at") != state["StartedAt"]
            or state["Running"]
            or state["Status"] != "exited"
            or state["ExitCode"] != 0
            or state["OOMKilled"]
            or state["Error"]
        ):
            raise ValueError("STOP_PROOF_MISMATCH")
        validate_persistence(container, target)
        initial_owner = Path(target["data_source"]).parent.parent / (
            target["game_id"] + ".initial-owner.json"
        )
        if "/worlds/" not in target["data_source"] and initial_owner.exists():
            initial_module().initialized(target, atomic)
        initialization = Path(target["data_source"]).parent / ".wishicraft-initialization.json"
        if "games" in manifest and initialization.exists():
            initial_world_permission(target, stopped=True)
            atomic(
                initialization, json.dumps({"game_id": target["game_id"], "phase": "initialized"})
            )
        proof["removal_ready"] = True
        atomic(receipt_path, json.dumps(receipt))
        execute(["docker", "rm", container["Id"]])
    elif receipt["phase"] != "stopped" and not proof.get("removal_ready"):
        raise ValueError("STOP_PROOF_MISMATCH")
    if inspect():
        raise ValueError("STOP_RESULT_UNKNOWN")
    stopped_environment()
    helper = "rcon-secret-v2" if "games" in manifest else "rcon-secret-v1"
    execute(["/usr/local/libexec/wishicraft/" + helper, "remove"])
    atomic(receipt_path, json.dumps({**receipt, "phase": "stopped"}))


def actual_instance() -> str:
    token_request = urllib.request.Request(
        "http://169.254.169.254/latest/api/token",
        method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
    )
    with urllib.request.urlopen(token_request, timeout=3) as response:
        token = response.read().decode("ascii")
    request = urllib.request.Request(
        "http://169.254.169.254/latest/meta-data/instance-id",
        headers={"X-aws-ec2-metadata-token": token},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return str(response.read().decode("ascii"))


def configured_container(container: dict[str, Any], manifest: dict[str, Any]) -> None:
    if container["Config"]["Image"] != manifest["image"]:
        raise ValueError("CONTAINER_CONFIG_MISMATCH")
    actual = dict(entry.split("=", 1) for entry in container["Config"]["Env"])
    expected = dict(
        entry.split("=", 1) for entry in (ARTIFACTS / "runtime.env").read_text().splitlines()
    )
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError("CONTAINER_ENV_MISMATCH")


def apply(request: dict[str, Any]) -> None:
    # Installer creates this root-owned directory. No fallback or initial migration here.
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(CONFIG.read_text())
        if actual_instance() != config["instance_id"]:
            raise ValueError("HOST_IDENTITY_MISMATCH")
        operation = item(config, "operations_table", "operation_id", request["operation_id"])
        lease = item(config, "locks_table", "lock_name", config["lock_name"])
        game = None
        if config.get("game_creation") is True:
            game = item(config, "games_table", "game_id", operation["target_game_id"])
            if game.get("lifecycle_state") != "ACTIVE":
                raise ValueError("GAME_NOT_REGISTERED")
            if operation["target_game_id"] not in config["games"]:
                creation = game["creation"]
                if creation["config_digest"] != config["config_digest"]:
                    raise ValueError("GAME_CONFIG_MISMATCH")
                config = {**config, "reset_policies": {**config["reset_policies"]}}
                if creation["reset_policy"] is not None:
                    if (
                        game["materialization_state"] != "MATERIALIZED"
                        and operation["operation_type"] == "RESET"
                    ):
                        raise ValueError("RESET_UNMATERIALIZED")
                    config["reset_policies"][game["game_id"]] = creation["reset_policy"]
        target = authorize(request, operation, lease, config, datetime.now(timezone.utc))
        manifest_bytes = (ARTIFACTS / "manifest.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != target["config_digest"]:
            raise ValueError("CONFIG_MISMATCH")
        manifest = json.loads(manifest_bytes)
        for name, field in [
            ("compose.yaml", "compose_sha256"),
            ("runtime.env", "runtime_env_sha256"),
        ]:
            if hashlib.sha256((ARTIFACTS / name).read_bytes()).hexdigest() != manifest[field]:
                raise ValueError("ARTIFACT_MISMATCH")
        if (
            request["action"] == "START"
            and game
            and "creation" in game
            and "/worlds/" not in target["data_source"]
        ):
            # Mount verification precedes all first-data writes; full filesystem preflight follows.
            execute(
                [
                    "bash",
                    "-c",
                    'set -aeu; source /etc/wishicraft/host-runtime.env; "$MOUNT_GUARD" --verify',
                ]
            )
            existing_receipt = ROOT / "receipt.json"
            receipt_before = (
                json.loads(existing_receipt.read_text()) if existing_receipt.exists() else None
            )
            containers_before = inspect()
            if containers_before:
                validate_container(containers_before[0], target)
            elif (
                receipt_before
                and receipt_before["phase"] != "stopped"
                and receipt_before["target"] != target
            ):
                raise ValueError("UNRESOLVED_RUNTIME")
            if not containers_before:
                stopped_environment()
            initial_module().prepare(game, config, target, atomic)
        preflight_target = (
            operation["switch_source"] if request["action"] == "RESET_PREPARE" else target
        )
        execute(
            [
                "bash",
                "-c",
                'set -aeu; export WISHICRAFT_RUN_ID="$1"; '
                "source /etc/wishicraft/host-runtime.env; "
                'export WISHICRAFT_GAME_ID="$2" GAME_DIRECTORY="$3"; '
                "/usr/local/lib/wishicraft-host-runtime/filesystem_preflight.sh",
                "wishicraft-preflight",
                preflight_target["run_id"],
                preflight_target["game_id"],
                preflight_target["data_source"],
            ]
        )
        unit_state = execute(
            ["systemctl", "show", UNIT, "--property=ActiveState", "--value"]
        ).strip()
        if unit_state not in {"active", "inactive", "failed"}:
            raise ValueError("RUNTIME_JOB_PENDING")
        receipt_path = ROOT / "receipt.json"
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        containers = inspect()
        if request["action"] == "RESET_PREPARE":
            if containers:
                raise ValueError("RESET_SOURCE_CONTAINER_REMAINS")
            stopped_environment()
            reset_module().prepare(
                json.loads(operation["reset_plan"]), receipt=receipt or {}, atomic=atomic
            )
            return
        if containers:
            validate_container(containers[0], target)
            configured_container(containers[0], manifest)
        if request["action"] == "RESET_CLEANUP":
            if not containers or not containers[0]["State"]["Running"]:
                raise ValueError("RESET_CLEANUP_RUNTIME_UNKNOWN")
            # Readiness is independently checked by the CP before sending this action.
            try:
                removed = reset_module().cleanup(
                    json.loads(operation["reset_plan"]), receipt=receipt or {}, atomic=atomic
                )
                result: dict[str, Any] = {"cleanup_pending": False, "removed_count": len(removed)}
            except (ValueError, OSError):
                # Successful runtime replacement is never undone to make cleanup look atomic.
                result = {"cleanup_pending": True, "removed_count": None}
            atomic(
                ROOT / "reset-cleanup.json",
                json.dumps({"operation_id": request["operation_id"], **result}),
            )
            print(json.dumps(result))
            return
        if request["action"] == "START":
            managed = "/worlds/" in target["data_source"]
            if managed:
                reset_module().initialized(target, atomic, require=False)
            if (
                "games" in config
                and not managed
                and not (Path(target["data_source"]) / "world/level.dat").is_file()
            ):
                if not (
                    config.get("game_creation") is True
                    and initial_module().initialized(target, atomic)
                ):
                    initial_world_permission(target)
            if receipt and receipt["phase"] == "stopping":
                raise ValueError("UNRESOLVED_RUNTIME")
            if receipt and receipt["target"] != target and receipt["phase"] != "stopped":
                raise ValueError("UNRESOLVED_RUNTIME")
            if receipt and receipt["target"] == target and receipt["phase"] == "stopped":
                raise ValueError("STOPPED_RUN_CANNOT_RESTART")
            atomic(receipt_path, json.dumps({"target": target, "phase": "starting"}))
            RUN_ENV.parent.mkdir(mode=0o700, exist_ok=True)
            atomic(
                RUN_ENV,
                "WISHICRAFT_RUN_ID="
                + target["run_id"]
                + "\n"
                + "WISHICRAFT_GAME_ID="
                + target["game_id"]
                + "\n"
                + "GAME_DIRECTORY="
                + target["data_source"]
                + "\n",
            )
            if not containers:
                secret_helper = "rcon-secret-v2" if "games" in config else "rcon-secret-v1"
                execute(["/usr/local/libexec/wishicraft/" + secret_helper, "prepare"])
            execute(["systemctl", "start", UNIT], timeout=300)
            current = inspect()
            if len(current) != 1 or not current[0]["State"]["Running"]:
                raise ValueError("START_RESULT_UNKNOWN")
            validate_container(current[0], target)
            configured_container(current[0], manifest)
            if managed:
                reset_module().initialized(target, atomic, require=False)
            if config.get("game_creation") is True and not managed:
                initial_module().initialized(target, atomic)
            atomic(receipt_path, json.dumps({"target": target, "phase": "running"}))
        else:
            if not receipt or receipt["target"] != target:
                raise ValueError("STOP_TARGET_UNKNOWN")
            if containers and containers[0]["State"]["Running"]:
                if operation["operation_type"] in {"SWITCH", "RESET"}:
                    players = execute(["docker", "exec", containers[0]["Id"], "rcon-cli", "list"])
                    if (
                        re.fullmatch(
                            r"There are 0 of a max of [0-9]+ players online: ?\s*", players
                        )
                        is None
                    ):
                        raise ValueError("SWITCH_PLAYERS_NOT_CONFIRMED_EMPTY")
                if receipt["phase"] == "stopped" or (
                    receipt.get("stop")
                    and (
                        receipt["stop"]["container_id"] != containers[0]["Id"]
                        or receipt["stop"]["started_at"] != containers[0]["State"]["StartedAt"]
                    )
                ):
                    raise ValueError("STOP_PROOF_MISMATCH")
                execute(
                    ["docker", "exec", containers[0]["Id"], "rcon-cli", "save-all", "flush"],
                    timeout=60,
                )
                receipt = {
                    "target": target,
                    "phase": "stopping",
                    "stop": {
                        "container_id": containers[0]["Id"],
                        "started_at": containers[0]["State"]["StartedAt"],
                        "save_confirmed": True,
                        "removal_ready": False,
                    },
                }
                atomic(receipt_path, json.dumps(receipt))
                execute(["systemctl", "stop", UNIT], timeout=210)
            elif receipt["phase"] not in {"stopping", "stopped"}:
                raise ValueError("STOP_REQUIRES_RECOVERY_OBSERVATION")
            finish_stop(receipt_path, receipt, target, manifest)


def initial_module() -> Any:
    try:
        from wishicraft.artifacts import initial_game

        return initial_game
    except ImportError:
        import importlib

        return importlib.import_module("initial_game")


def reset_module() -> Any:
    if __package__:
        from wishicraft.artifacts import reset_worlds

        return reset_worlds
    import importlib

    return importlib.import_module("reset_worlds")


def main() -> int:
    try:
        if os.geteuid() != 0 or len(sys.argv) != 2:
            raise ValueError("INVOCATION")
        request = json.loads(base64.b64decode(sys.argv[1], validate=True))
        apply(request)
    except Exception as error:
        codes = {
            "STALE_OPERATION",
            "TARGET_MISMATCH",
            "GAME_MISMATCH",
            "HOST_IDENTITY_MISMATCH",
            "CONFIG_MISMATCH",
            "ARTIFACT_MISMATCH",
            "CONTAINER_TARGET_MISMATCH",
            "CONTAINER_CONFIG_MISMATCH",
            "CONTAINER_ENV_MISMATCH",
            "RUNTIME_JOB_PENDING",
            "UNRESOLVED_RUNTIME",
            "STOPPED_RUN_CANNOT_RESTART",
            "START_RESULT_UNKNOWN",
            "STOP_TARGET_UNKNOWN",
            "STOP_PROOF_MISMATCH",
            "PERSISTENCE_UNPROVEN",
            "STOP_REQUIRES_RECOVERY_OBSERVATION",
            "STOP_RESULT_UNKNOWN",
            "STOP_LISTENER_REMAINS",
            "MULTIPLE_CONTAINERS",
            "HOST_COMMAND_FAILED",
        }
        code = (
            str(error)
            if isinstance(error, (ValueError, RuntimeError)) and str(error) in codes
            else "TARGETED_RUNTIME_FAILED"
        )
        print(json.dumps({"schema_version": 2, "status": "failed", "error_code": code}))
        return 1
    print('{"schema_version":2,"status":"succeeded"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
