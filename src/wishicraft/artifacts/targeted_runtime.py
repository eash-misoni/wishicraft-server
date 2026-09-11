"""Host-only v2 boundary. Root-owned fixed paths; no caller paths or shell commands."""

# ruff: noqa: UP045, UP017 -- AL2023 Python 3.9
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
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
    if request["schema_version"] != 2 or request["action"] not in {"START", "STOP"}:
        raise ValueError("REQUEST_VERSION")
    if (
        operation["operation_id"] != request["operation_id"]
        or operation["lease_id"] != request["lease_id"]
        or operation["operation_type"] != request["action"]
        or operation["status"] != "RUNNING"
        or datetime.fromisoformat(operation["timeout_at"].replace("Z", "+00:00")) <= now
        or lease["owner_operation_id"] != request["operation_id"]
        or lease["lease_id"] != request["lease_id"]
        or lease["resource_id"] != config["system_id"]
        or lease["lease_expires_at"] <= int(now.timestamp())
    ):
        raise ValueError("STALE_OPERATION")
    target = operation["runtime_target"]
    for name in ("instance_id", "game_id", "data_source", "config_digest"):
        if target[name] != config[name]:
            raise ValueError("TARGET_MISMATCH")
    if operation["target_game_id"] != target["game_id"]:
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
        labels.get("com.wishicraft.run-id") != target["run_id"]
        or labels.get("com.wishicraft.active-game-id") != target["game_id"]
        or labels.get("com.wishicraft.active-game-data-source") != target["data_source"]
        or len(binds) != 1
        or binds[0]["Type"] != "bind"
        or binds[0]["Source"] != target["data_source"]
    ):
        raise ValueError("CONTAINER_TARGET_MISMATCH")


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
        execute(
            [
                "bash",
                "-c",
                "set -aeu; source /etc/wishicraft/host-runtime.env; "
                "/usr/local/lib/wishicraft-host-runtime/filesystem_preflight.sh",
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
        if containers:
            validate_container(containers[0], target)
            configured_container(containers[0], manifest)
        if request["action"] == "START":
            if receipt and receipt["target"] != target and receipt["phase"] != "stopped":
                raise ValueError("UNRESOLVED_RUNTIME")
            if receipt and receipt["target"] == target and receipt["phase"] == "stopped":
                raise ValueError("STOPPED_RUN_CANNOT_RESTART")
            atomic(receipt_path, json.dumps({"target": target, "phase": "starting"}))
            RUN_ENV.parent.mkdir(mode=0o700, exist_ok=True)
            atomic(
                RUN_ENV,
                "WISHICRAFT_RUN_ID=" + target["run_id"] + "\n",
            )
            if not containers:
                execute(["/usr/local/libexec/wishicraft/rcon-secret-v1", "prepare"])
            execute(["systemctl", "start", UNIT], timeout=300)
            current = inspect()
            if len(current) != 1 or not current[0]["State"]["Running"]:
                raise ValueError("START_RESULT_UNKNOWN")
            validate_container(current[0], target)
            configured_container(current[0], manifest)
            atomic(receipt_path, json.dumps({"target": target, "phase": "running"}))
        else:
            if not receipt or receipt["target"] != target:
                raise ValueError("STOP_TARGET_UNKNOWN")
            if containers and containers[0]["State"]["Running"]:
                execute(
                    ["docker", "exec", containers[0]["Id"], "rcon-cli", "save-all", "flush"],
                    timeout=60,
                )
                atomic(receipt_path, json.dumps({"target": target, "phase": "stopping"}))
                execute(["systemctl", "stop", UNIT], timeout=210)
            elif receipt["phase"] not in {"stopping", "stopped"}:
                raise ValueError("STOP_REQUIRES_RECOVERY_OBSERVATION")
            if (
                inspect()
                or execute(["systemctl", "show", UNIT, "--property=ActiveState", "--value"]).strip()
                != "inactive"
            ):
                raise ValueError("STOP_RESULT_UNKNOWN")
            for port in ("25565", "25575"):
                if execute(["ss", "-H", "-ltn", "sport = :" + port]).strip():
                    raise ValueError("STOP_LISTENER_REMAINS")
            execute(["/usr/local/libexec/wishicraft/rcon-secret-v1", "remove"])
            atomic(receipt_path, json.dumps({"target": target, "phase": "stopped"}))


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
