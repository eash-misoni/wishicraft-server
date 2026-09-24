"""Bounded supplemental RESTORE evidence; read-only, never a selection validator."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from wishicraft.artifacts import world_import as imported
from wishicraft.artifacts import world_nbt

MAX_ENTRIES = 100_000
MAX_BYTES = 16 * 1024**3
MAX_OUTPUT = 20_000
MAX_DEPTH = 32
SAMPLES = 4


def bounded_files(root: Path) -> list[Path]:
    """Check before hashing; never traverse a link, mount, special file or hardlink."""
    for ancestor in (root, *root.parents):
        if not stat.S_ISDIR(ancestor.lstat().st_mode):
            raise ValueError("READER_ANCESTOR")
    device = root.stat().st_dev
    pending = [(root, 0)]
    files: list[Path] = []
    count = size = 0
    while pending:
        parent, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise ValueError("READER_DEPTH_LIMIT")
        with os.scandir(parent) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError("READER_ENTRY_LIMIT")
                info = entry.stat(follow_symlinks=False)
                if info.st_dev != device:
                    raise ValueError("READER_OTHER_DEVICE")
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    pending.append((path, depth + 1))
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    size += info.st_size
                    if size > MAX_BYTES:
                        raise ValueError("READER_BYTE_LIMIT")
                    files.append(path)
                else:
                    raise ValueError("READER_TREE_TYPE")
    return sorted(files)


def opaque(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, (bytes, str, dict, list)):
        result["length"] = len(value)
    if isinstance(value, bytes):
        result["sha256"] = hashlib.sha256(value).hexdigest()
    return result


def field(parent: dict[str, Any], key: str, expected: type) -> dict[str, Any]:
    if key not in parent:
        return {"state": "missing"}
    value = parent[key]
    if value is None:
        return {"state": "null"}
    if type(value) is expected and (
        expected is int or (expected is str and isinstance(value, str) and len(value) <= 128)
    ):
        return {"state": "value", "value": value}
    return {"state": "unsupported", **opaque(value)}


def nbt_summary(level: Path) -> dict[str, Any]:
    if not level.exists():
        return {"state": "missing"}
    try:
        data = world_nbt.read(level).get("Data")
        if not isinstance(data, dict):
            return {"state": "unsupported", **opaque(data)}
        spawn = data.get("spawn")
        # The parser returns NBT arrays as bytes without their tag type. Do not
        # reinterpret them as coordinates or seed, or dump an entire compound.
        modern_spawn = field(data, "spawn", dict)
        if isinstance(spawn, dict):
            modern_spawn["selected_fields"] = {
                "dimension": field(spawn, "dimension", str),
                "pos": field(spawn, "pos", bytes),
            }
        legacy = data.get("WorldGenSettings")
        seed = (
            field(legacy, "seed", int)
            if isinstance(legacy, dict)
            else {"state": "missing" if "WorldGenSettings" not in data else "unsupported"}
        )
        version = data.get("Version")
        return {
            "state": "read",
            "version_name": field(version, "Name", str)
            if isinstance(version, dict)
            else {"state": "unsupported"},
            "data_version": field(data, "DataVersion", int),
            "level_name": field(data, "LevelName", str),
            "time": field(data, "Time", int),
            "spawn": modern_spawn,
            "legacy_seed": {"location": "Data.WorldGenSettings.seed", **seed},
            "seed_interpretation": "Only the named legacy field is decoded; absence is not no seed",
        }
    except (OSError, ValueError, EOFError):
        return {"state": "read_failed", "error": "NBT_READ_FAILED"}


def fingerprint(path: Path) -> dict[str, Any]:
    before = path.stat()
    digest = imported.sha(path)
    after = path.stat()
    stable = (before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    return {
        "state": "read" if stable else "changed_during_read",
        "size": after.st_size,
        "sha256": digest,
    }


def inspect_server(server: Path, level_name: str, *, full_tree: bool) -> dict[str, Any]:
    if not level_name or Path(level_name).name != level_name or level_name in {".", ".."}:
        raise ValueError("READER_LEVEL_NAME")
    files = bounded_files(server)
    level = server / level_name
    if not level.is_dir():
        raise ValueError("READER_WORLD_MISSING")
    # Real 26.2 worlds use dimensions/<namespace>/<dimension>/region; include that
    # layout and legacy regions without mistaking entities/poi for terrain.
    regions = [
        p
        for p in files
        if p.is_relative_to(level) and p.parent.name == "region" and p.suffix == ".mca"
    ]
    result = {
        "server_path": str(server),
        "world_path": str(level),
        "nbt": nbt_summary(level / "level.dat"),
        "terrain_region_count": len(regions),
        "terrain_samples": {str(p.relative_to(level)): fingerprint(p) for p in regions[:SAMPLES]},
    }
    policies = {}
    for name in ("whitelist.json", "ops.json", "banned-players.json", "banned-ips.json"):
        path = server / name
        if not path.exists():
            policies[name] = {"state": "missing"}
        else:
            if path.stat().st_size > 65536:
                raise ValueError("READER_POLICY_LIMIT")
            policies[name] = {"state": "read", "sha256": imported.sha(path)}
    result["policy_file_hashes"] = policies
    if full_tree:
        result["server_tree"] = imported.tree(server)
        result["world_tree"] = imported.tree(level)
    return result


def output(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_OUTPUT:
        raise ValueError("READER_OUTPUT_LIMIT")
    return encoded


def managed_records(server: Path) -> dict[str, Any]:
    """Only fixed owner/validation locations; no world contents or property text."""
    if server.parent.parent.name != "worlds":
        return {"state": "not_applicable"}
    parent = server.parent
    paths = {
        "owner": parent.parent / (parent.name + ".owner.json"),
        "validated": parent / "validated.json",
    }
    result: dict[str, Any] = {}
    for label, path in paths.items():
        if not path.exists() and not path.is_symlink():
            result[label] = {"state": "missing"}
            continue
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != 0
            or info.st_gid != 0
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 65536
        ):
            raise ValueError("READER_RECORD_IDENTITY")
        value = json.loads(path.read_text())
        # Do not output arbitrary new fields from a record, including any future secret.
        selected = {
            key: value[key]
            for key in (
                "phase",
                "protected",
                "restore",
                "plan",
                "source_tree",
                "previous_tree",
                "prepared_tree",
                "source_world_tree",
                "candidate",
            )
            if key in value
        }
        result[label] = {
            "state": "read",
            "path": str(path),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": oct(stat.S_IMODE(info.st_mode)),
            "sha256": imported.sha(path),
            "record": selected,
        }
    result["staging"] = sorted(p.name for p in parent.glob("staging-*"))[:8]
    return result


def host_evidence() -> dict[str, Any]:
    """Fixed local runtime identities only; never Docker environment or secret config."""
    import subprocess

    helpers = {}
    for name in ("reset_worlds.py", "world_import.py"):
        path = Path("/usr/local/libexec/wishicraft") / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 131072:
            raise ValueError("READER_HELPER_TYPE")
        helpers[name] = {
            "sha256": imported.sha(path),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": oct(stat.S_IMODE(info.st_mode)),
        }
    receipt_path = Path("/var/lib/wishicraft/runtime/receipt.json")
    if receipt_path.is_symlink() or receipt_path.stat().st_size > 65536:
        raise ValueError("READER_RUNTIME_RECEIPT")
    receipt = json.loads(receipt_path.read_text())
    ids = subprocess.check_output(["docker", "ps", "-q"], text=True, timeout=15).split()
    if len(ids) > 1 or any(not value.isalnum() or len(value) > 64 for value in ids):
        raise ValueError("READER_CONTAINER_COUNT")
    containers = []
    for identity in ids:
        raw = json.loads(
            subprocess.check_output(["docker", "inspect", identity], text=True, timeout=15)
        )[0]
        containers.append(
            {
                "id": identity,
                "image": raw["Config"]["Image"],
                "running": raw["State"]["Running"],
                "mounts": [
                    {k: v[k] for k in ("Type", "Source", "Destination", "RW")}
                    for v in raw["Mounts"]
                ],
            }
        )
    return {
        "helpers": helpers,
        "runtime_receipt": {k: receipt.get(k) for k in ("phase", "target")},
        "containers": containers,
    }
