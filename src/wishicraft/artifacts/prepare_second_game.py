"""Operator-only B materialization; no AWS calls and no changes to A or existing B data."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from wishicraft.artifacts import targeted_runtime as host


def materialize(parent: Path, files: dict[str, str], *, uid: int, gid: int) -> dict[str, str]:
    """Caller establishes exact host/mount/catalog under the host lock before entry."""
    if parent.is_symlink() or parent.parent.is_symlink():
        raise ValueError("GAME_PARENT_SYMLINK")
    parent.mkdir(mode=0o755, exist_ok=True)
    server, staging = parent / "server", parent / ".prepare-two-game-v1"
    hashes = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in files.items()}
    if any(name not in {"server.properties", "whitelist.json"} for name in files):
        raise ValueError("UNEXPECTED_GAME_FILE")
    if server.exists() or server.is_symlink():
        if server.is_symlink() or not server.is_dir():
            raise ValueError("GAME_DATA_IDENTITY")
        if {p.name for p in server.iterdir()} != set(files):
            raise ValueError("EXISTING_GAME_DATA_REQUIRES_OBSERVATION")
        for name, expected in hashes.items():
            path = server / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("EXISTING_GAME_FILE_MISMATCH")
        return hashes
    if staging.is_symlink():
        raise ValueError("STAGING_IDENTITY")
    staging.mkdir(mode=0o700, exist_ok=True)
    if any(p.name not in files for p in staging.iterdir()):
        raise ValueError("UNKNOWN_STAGING_DATA")
    for name, content in files.items():
        path = staging / name
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.read_text() != content:
                raise ValueError("STAGING_CONTENT_MISMATCH")
        else:
            with path.open("x") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        os.chown(path, uid, gid)
        path.chmod(0o640)
    os.chown(staging, uid, gid)
    staging.chmod(0o750)
    os.rename(staging, server)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return hashes


def prepare(document: dict[str, Any]) -> dict[str, object]:
    if os.geteuid() != 0:
        raise ValueError("ROOT_REQUIRED")
    with (host.ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(host.CONFIG.read_text())
        game_id = document["game_id"]
        if (
            host.actual_instance() != config["instance_id"]
            or config.get("games", [None, None])[1] != game_id
        ):
            raise ValueError("SECOND_GAME_IDENTITY")
        if (
            host.inspect()
            or host.execute(
                ["systemctl", "show", host.UNIT, "--property=ActiveState", "--value"]
            ).strip()
            != "inactive"
        ):
            raise ValueError("RUNTIME_NOT_INACTIVE")
        host.execute(
            [
                "bash",
                "-c",
                'set -aeu; source /etc/wishicraft/host-runtime.env; "$MOUNT_GUARD" --verify',
            ]
        )
        hashes = materialize(
            Path("/srv/minecraft/games") / game_id, document["files"], uid=993, gid=993
        )
        initialization = Path("/srv/minecraft/games") / game_id / ".wishicraft-initialization.json"
        expected = {"game_id": game_id, "phase": "prepared"}
        if initialization.exists() or initialization.is_symlink():
            if initialization.is_symlink() or json.loads(initialization.read_text()) != expected:
                raise ValueError("INITIALIZATION_ALREADY_CHANGED")
        else:
            host.atomic(initialization, json.dumps(expected))
        return {
            "schema_version": 1,
            "game_id": game_id,
            "data_source": "/srv/minecraft/games/" + game_id + "/server",
            "files": hashes,
        }
