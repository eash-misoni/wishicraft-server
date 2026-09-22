"""Inactive-only fixed bundle installer; approved SSM invocation required."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

BUNDLE = Path("/var/tmp/wishicraft-targeted-runtime-v1")
RECEIPTS = Path("/var/lib/wishicraft/runtime")
GAMES = Path("/srv/minecraft/games")
PACKAGE_OWNER_UID, PACKAGE_OWNER_GID = 0, 0


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


def verify_package_context(manifest: dict[str, Any]) -> None:
    """Validate the reviewed Game package cache before any managed file is replaced."""
    context = manifest.get("package_context")
    environment = manifest.get("package_environment")
    if context is None:
        return
    if not isinstance(context, dict) or not isinstance(environment, dict):
        raise ValueError("PACKAGE_CONTEXT_SCHEMA")
    required = {
        "game_id",
        "data_source",
        "generation",
        "package",
        "package_digest",
        "package_directory",
        "artifacts",
    }
    if (
        set(context) != required
        or context["game_id"] != manifest["receipt_predecessor"]["target"]["game_id"]
    ):
        raise ValueError("PACKAGE_CONTEXT_SCHEMA")
    game_id = context["game_id"]
    if not isinstance(game_id, str) or re.fullmatch(r"game-[a-z0-9-]+", game_id) is None:
        raise ValueError("PACKAGE_CONTEXT_IDENTITY")
    root = GAMES / game_id
    package_directory = root / "package-cache"
    if (
        context["package_directory"] != str(package_directory)
        or environment.get("GAME_PACKAGE_DIRECTORY") != str(package_directory)
        or context["data_source"] != manifest["receipt_predecessor"]["target"]["data_source"]
        or environment.get("WISHICRAFT_PACKAGE_DIGEST") != context["package_digest"]
    ):
        raise ValueError("PACKAGE_CONTEXT_IDENTITY")
    package = context["package"]
    canonical = json.dumps(package, sort_keys=True, separators=(",", ":")) + "\n"
    if hashlib.sha256(canonical.encode()).hexdigest() != context["package_digest"]:
        raise ValueError("PACKAGE_CONTEXT_DIGEST")
    loader = package.get("loader")
    mods = package.get("mods")
    if not isinstance(loader, dict) or not isinstance(mods, list):
        raise ValueError("PACKAGE_CONTEXT_SCHEMA")
    neo = loader.get("type") == "neoforge"
    paper = loader.get("type") == "paper"
    if not neo and not paper and loader != {"type": "vanilla"}:
        raise ValueError("PACKAGE_CONTEXT_SCHEMA")
    expected_environment = {
        "GAME_PACKAGE_DIRECTORY": str(package_directory),
        "WISHICRAFT_PACKAGE_DIGEST": context["package_digest"],
        "WISHICRAFT_PACKAGE_TYPE": "NEOFORGE" if neo else "VANILLA",
        "WISHICRAFT_PACKAGE_VERSION": package.get("minecraft_version"),
        "WISHICRAFT_PACKAGE_NEOFORGE_VERSION": loader.get("version", ""),
        "WISHICRAFT_PACKAGE_NEOFORGE_INSTALLER": (
            "/wishicraft-package/" + loader.get("installer", {}).get("filename", "") if neo else ""
        ),
        "WISHICRAFT_PACKAGE_NEOFORGE_FORCE_REINSTALL": "true" if neo else "false",
    }
    if paper:
        expected_environment.update(
            {
                "WISHICRAFT_PACKAGE_TYPE": "PAPER",
                "WISHICRAFT_PACKAGE_PAPER_BUILD": str(loader["build"]),
                "WISHICRAFT_PACKAGE_PAPER_CUSTOM_JAR": "/wishicraft-package/"
                + loader["server"]["filename"],
                "WISHICRAFT_PACKAGE_SKIP_DOWNLOAD_DEFAULTS": "true",
                "WISHICRAFT_PACKAGE_LEVEL": loader["level_name"],
            }
        )
    if environment != expected_environment:
        raise ValueError("PACKAGE_ENVIRONMENT_MISMATCH")
    owner = root / "package-owner.json"
    if (
        digest(owner)
        != hashlib.sha256(
            (
                json.dumps(
                    {"game_id": game_id, "package": package}, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            ).encode()
        ).hexdigest()
    ):
        raise ValueError("PACKAGE_OWNER_MISMATCH")
    owner_info = owner.stat()
    if (
        owner_info.st_uid != PACKAGE_OWNER_UID
        or owner_info.st_gid != PACKAGE_OWNER_GID
        or owner_info.st_nlink != 1
        or owner_info.st_mode & 0o022
    ):
        raise ValueError("PACKAGE_OWNER_IDENTITY")
    package_info = package_directory.lstat()
    if (
        not stat.S_ISDIR(package_info.st_mode)
        or package_info.st_uid != PACKAGE_OWNER_UID
        or package_info.st_gid != PACKAGE_OWNER_GID
        or package_info.st_mode & 0o022
    ):
        raise ValueError("PACKAGE_DIRECTORY_IDENTITY")
    artifacts = context["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("PACKAGE_CONTEXT_SCHEMA")
    expected_specs = [
        {key: artifact[key] for key in ("filename", "size", "sha256")}
        for artifact in ([*mods, loader["installer"]] if neo else mods)
    ]
    if paper:
        expected_specs.append(
            {key: loader["server"][key] for key in ("filename", "size", "sha256")}
        )
    if artifacts != expected_specs:
        raise ValueError("PACKAGE_ARTIFACT_IDENTITY")
    mod_names = {mod["filename"] for mod in mods}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"filename", "size", "sha256"}:
            raise ValueError("PACKAGE_CONTEXT_SCHEMA")
        filename = artifact["filename"]
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("PACKAGE_ARTIFACT_IDENTITY")
        path = package_directory / ("mods" if filename in mod_names else "") / filename
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != PACKAGE_OWNER_UID
            or info.st_gid != PACKAGE_OWNER_GID
            or info.st_nlink != 1
            or info.st_mode & 0o222
            or info.st_size != artifact["size"]
            or digest(path) != artifact["sha256"]
        ):
            raise ValueError("PACKAGE_ARTIFACT_IDENTITY")


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
        (
            ["env", *(key + "=" + value for key, value in manifest["package_environment"].items())]
            if "package_environment" in manifest
            else []
        )
        + [
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
    verify_package_context(manifest)
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
