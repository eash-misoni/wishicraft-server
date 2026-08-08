"""Deterministic, allowlisted bootstrap archive construction."""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path

FILES = (
    "data_volume_mount.sh",
    "java_runtime_install.sh",
    "minecraft_artifact_install.sh",
    "minecraft_game_setup.sh",
    "minecraft_rcon_configure.sh",
    "minecraft_rcon_firewall.sh",
)


def member_list() -> str:
    """Return the newline-delimited member allowlist for the bootstrap runner."""

    return "\n".join(FILES)


def build_bundle(directory: Path) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name in FILES:
                data = (directory / name).read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime, info.uid, info.gid = len(data), 0o755, 0, 0, 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def bundle_sha256(bundle: bytes) -> str:
    return hashlib.sha256(bundle).hexdigest()
