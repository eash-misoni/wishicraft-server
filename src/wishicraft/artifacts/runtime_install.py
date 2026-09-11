"""Inactive-only fixed bundle installer; approved SSM invocation required."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

BUNDLE = Path("/var/tmp/wishicraft-targeted-runtime-v1")
RECEIPTS = Path("/var/lib/wishicraft/runtime")


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FILE_IDENTITY")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str]) -> str:
    return subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()


def validate_entry(entry: dict[str, Any]) -> bool:
    source, target = BUNDLE / entry["source"], Path(entry["destination"])
    if digest(source) != entry["sha256"]:
        raise ValueError("SOURCE_DIGEST")
    if target.exists() or target.is_symlink():
        current = digest(target)
        info = target.stat()
        if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != entry["mode"]:
            raise ValueError("TARGET_OWNER_MODE")
        if current == entry["sha256"]:
            return False
        if current != entry["predecessor"]:
            raise ValueError("UNKNOWN_PREDECESSOR")
    elif entry["predecessor"] is not None:
        raise ValueError("MISSING_PREDECESSOR")
    return True


def require_no_container() -> None:
    """Legacy stopped containers require the separately approved migration cleanup."""
    if run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=wishicraft-host-runtime",
        ]
    ):
        raise ValueError("CONTAINER_REMAINS")


def verify_stopped_predecessor(manifest: dict[str, Any]) -> None:
    """A later cutover preserves its exact completed receipt; never erase it to install."""
    path = RECEIPTS / "receipt.json"
    expected = manifest.get("receipt_predecessor")
    if expected is None:
        if path.exists() or path.is_symlink():
            raise ValueError("EXECUTION_ALREADY_RECORDED_NO_REINSTALL")
        return
    digest(path)
    info = path.stat()
    receipt = json.loads(path.read_text())
    if info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("RECEIPT_OWNER_MODE")
    if receipt != expected or receipt.get("phase") != "stopped":
        raise ValueError("UNEXPECTED_EXECUTION_RECEIPT")
    proof = receipt.get("stop", {})
    if proof.get("save_confirmed") is not True or proof.get("removal_ready") is not True:
        raise ValueError("RECEIPT_STOP_UNPROVEN")


def install() -> None:
    if os.geteuid() != 0:
        raise ValueError("ROOT_REQUIRED")
    manifest = json.loads((BUNDLE / "install.json").read_text())
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
        if response.read().decode("ascii") != manifest["instance_id"]:
            raise ValueError("HOST_IDENTITY_MISMATCH")
    context = manifest.get("receipt_predecessor", {}).get("target")
    preflight_context = (
        [] if context is None else [context["run_id"], context["game_id"], context["data_source"]]
    )
    run(
        [
            "bash",
            "-c",
            "set -aeu; source /etc/wishicraft/host-runtime.env; "
            + (
                'export WISHICRAFT_RUN_ID="$1" WISHICRAFT_GAME_ID="$2" GAME_DIRECTORY="$3"; '
                if context is not None
                else ""
            )
            + "/usr/local/lib/wishicraft-host-runtime/filesystem_preflight.sh",
            "wishicraft-install-preflight",
            *preflight_context,
        ]
    )
    # Transport must verify the complete approved bundle digest before invoking this file.
    if run(
        [
            "systemctl",
            "show",
            "wishicraft-host-runtime.service",
            "--property=ActiveState",
            "--value",
        ]
    ) not in {"inactive", "failed"}:
        raise ValueError("RUNTIME_NOT_INACTIVE")
    require_no_container()
    if run(["ss", "-H", "-ltn", "sport = :25565 or sport = :25575"]):
        raise ValueError("LISTENER_REMAINS")
    for entry in manifest["files"]:
        validate_entry(entry)
    RECEIPTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    verify_stopped_predecessor(manifest)
    backup_root = RECEIPTS
    if "backup_namespace" in manifest:
        namespace = manifest["backup_namespace"]
        if namespace != "two-game-v1":
            raise ValueError("UNKNOWN_BACKUP_NAMESPACE")
        backup_root = RECEIPTS / namespace
        if backup_root.is_symlink():
            raise ValueError("BACKUP_DIRECTORY_IDENTITY")
        backup_root.mkdir(mode=0o700, exist_ok=True)
    for entry in manifest["files"]:
        if not validate_entry(entry):
            continue
        source, target = BUNDLE / entry["source"], Path(entry["destination"])
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if target.exists():
            backup = backup_root / ("predecessor-" + entry["source"])
            if backup.exists():
                if digest(backup) != entry["predecessor"]:
                    raise ValueError("PREDECESSOR_BACKUP_MISMATCH")
            else:
                with backup.open("xb") as stream:
                    stream.write(target.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                backup.chmod(0o600)
        descriptor, temporary = tempfile.mkstemp(prefix=".targeted-", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, entry["mode"])
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    run(["systemctl", "daemon-reload"])
    for entry in manifest["files"]:
        if validate_entry(entry):
            raise ValueError("INSTALL_INCOMPLETE")
    print("TARGETED_RUNTIME_INSTALLED_INACTIVE")


def main() -> None:
    if os.geteuid() != 0:
        raise ValueError("ROOT_REQUIRED")
    RECEIPTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (RECEIPTS / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install()


if __name__ == "__main__":
    main()
