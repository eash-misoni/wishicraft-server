"""Root-owned Reset data operations, called only under operation-v2's host lock.

Ownership and deletion receipts live outside Minecraft's writable server directory.
There is no active-world pointer here: selection belongs to Games in the control plane.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

OWNER_UID, OWNER_GID = 0, 0
GAMES = Path("/srv/minecraft/games")
CONFIG_FILES = (
    "server.properties",
    "whitelist.json",
    "ops.json",
    "banned-players.json",
    "banned-ips.json",
)


def directory(path: Path, *, owner: int | None = None) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != (OWNER_UID if owner is None else owner)
        or info.st_mode & 0o022
    ):
        raise ValueError("RESET_DIRECTORY_IDENTITY")


def record(path: Path) -> dict[str, Any]:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != OWNER_UID
        or info.st_gid != OWNER_GID
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise ValueError("RESET_RECORD_IDENTITY")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("RESET_RECORD_SCHEMA")
    return value


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def owner_path(world: Path) -> Path:
    return world.parent / (world.name + ".owner.json")


def parent(game: str, world: str) -> Path:
    if (
        re.fullmatch(r"game-[a-z0-9-]+", game) is None
        or re.fullmatch(r"op-[a-z0-9-]{1,100}", world) is None
    ):
        raise ValueError("RESET_WORLD_IDENTITY")
    return GAMES / game / "worlds" / world


def tree(path: Path, *, device: int) -> int:
    """Reject redirections, other mounts, hard links and special files before copying/deleting."""
    info = path.lstat()
    if info.st_dev != device or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise ValueError("RESET_UNKNOWN_DATA")
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            raise ValueError("RESET_UNKNOWN_DATA")
        return info.st_size
    return sum(tree(child, device=device) for child in path.iterdir())


def files(source: Path, seed: int) -> dict[str, bytes]:
    if not (source / "world/level.dat").is_file():
        raise ValueError("RESET_SOURCE_WORLD_MISSING")
    result = {}
    for name in CONFIG_FILES:
        path = source / name
        if not path.exists():
            if name in {"server.properties", "whitelist.json"}:
                raise ValueError("RESET_SOURCE_CONFIGURATION_MISSING")
            continue
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_nlink != 1:
            raise ValueError("RESET_SOURCE_CONFIGURATION_IDENTITY")
        result[name] = path.read_bytes()
    text = result["server.properties"].decode()
    lines = text.splitlines()
    # Restrict to the pinned runtime's generated Java properties. No escaped/custom world key.
    values: dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.startswith(("#", "!")):
            continue
        match = re.fullmatch(r"([a-z0-9.-]+)=(.*)", line)
        trailing = len(line) - len(line.rstrip("\\"))
        if match is None or trailing % 2 or match[1] in values:
            raise ValueError("RESET_CUSTOM_PROPERTIES_UNSUPPORTED")
        values[match[1]] = match[2]
    if values.get("level-name") != "world":
        raise ValueError("RESET_CUSTOM_PROPERTIES_UNSUPPORTED")
    lines = [line for line in lines if not line.startswith("level-seed=")]
    result["server.properties"] = ("\n".join([*lines, "level-seed=" + str(seed)]) + "\n").encode()
    return result


def prepare(
    plan: dict[str, Any],
    *,
    receipt: dict[str, Any],
    atomic: Callable[[Path, str], None],
    uid: int = 993,
    gid: int = 993,
) -> None:
    game, world = plan["target"]["game_id"], plan["target"]["run_id"]
    target = parent(game, world)
    if str(target / "server") != plan["target"]["data_source"]:
        raise ValueError("RESET_DESTINATION_IDENTITY")
    directory(GAMES)
    directory(GAMES / game)
    if not target.parent.exists():
        target.parent.mkdir(mode=0o700)
    directory(target.parent)
    if target.exists() or target.is_symlink():
        directory(target)
    if owner_path(target).exists() or owner_path(target).is_symlink():
        existing = record(owner_path(target))
        if existing.get("plan") != plan:
            raise ValueError("RESET_WORLD_ALREADY_OWNED")
        if existing["phase"] in {"prepared", "initialized"}:
            if not (target / "server").is_dir() or (target / "server").is_symlink():
                raise ValueError("RESET_PREPARED_DATA_MISSING")
            return
        if existing["phase"] != "preparing":
            raise ValueError("RESET_WORLD_NOT_PREPARING")
    if (
        receipt.get("phase") != "stopped"
        or receipt.get("target") != plan["source"]
        or receipt.get("stop", {}).get("save_confirmed") is not True
        or receipt.get("stop", {}).get("removal_ready") is not True
    ):
        raise ValueError("RESET_SOURCE_STOP_UNPROVEN")
    source = Path(plan["source"]["data_source"])
    used = tree(source, device=GAMES.stat().st_dev)
    if shutil.disk_usage(GAMES).free < max(plan["policy"]["minimum_free_bytes"], 2 * used):
        raise ValueError("RESET_INSUFFICIENT_CAPACITY")
    content = files(source, plan["seed"])
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in content.items()}
    if not owner_path(target).exists():
        if target.exists():
            raise ValueError("RESET_UNOWNED_DIRECTORY")
        atomic(
            owner_path(target), json.dumps({"plan": plan, "phase": "preparing", "files": hashes})
        )
    if not target.exists():
        target.mkdir(mode=0o700)
    existing = record(owner_path(target))
    if existing["files"] != hashes:
        raise ValueError("RESET_SOURCE_CHANGED_DURING_PREPARATION")
    server = target / "server"
    server.mkdir(mode=0o750, exist_ok=True)
    if server.is_symlink() or any(p.name not in content for p in server.iterdir()):
        raise ValueError("RESET_UNKNOWN_PREPARATION_DATA")
    for name, value in content.items():
        path = server / name
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.read_bytes() != value:
                raise ValueError("RESET_PREPARATION_FILE_CONFLICT")
        else:
            # Same-directory atomic replacement is used only for a previously absent file.
            atomic(path, value.decode())
        os.chown(path, uid, gid)
        path.chmod(0o640)
    os.chown(server, uid, gid)
    sync_directory(target)
    atomic(owner_path(target), json.dumps({**existing, "phase": "prepared"}))


def initialized(
    target: dict[str, str], atomic: Callable[[Path, str], None], *, require: bool
) -> None:
    """A prepared world can be generated once; an initialized world's absence is corruption."""
    data = Path(target["data_source"])
    if data.parent.parent.name != "worlds":
        return
    directory(data.parent)
    info = record(owner_path(data.parent))
    owned = info["plan"]["target"]
    if any(owned[key] != target[key] for key in ("game_id", "data_source")):
        raise ValueError("RESET_OWNER_MISMATCH")
    if info["phase"] not in {"prepared", "initialized"}:
        raise ValueError("RESET_WORLD_UNAVAILABLE")
    if not (data / "world/level.dat").is_file():
        if require or info["phase"] != "prepared":
            raise ValueError("EXISTING_WORLD_MISSING")
    else:
        atomic(owner_path(data.parent), json.dumps({**info, "phase": "initialized"}))


def cleanup(
    plan: dict[str, Any],
    *,
    receipt: dict[str, Any],
    atomic: Callable[[Path, str], None],
) -> list[str]:
    """Delete only the old managed chain, after destination READY, with immutable plan proofs.

    Legacy source is a permanent anchor. The latest N managed predecessors are protected.
    Each deletion intent remains in its root-owned owner record after data removal.
    """
    if receipt.get("phase") != "running" or receipt.get("target") != plan["target"]:
        raise ValueError("RESET_CLEANUP_RUNTIME_MISMATCH")
    initialized(plan["target"], atomic, require=True)
    previous = plan["source"]["data_source"]
    kept, deleted = 0, []
    candidates: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    while previous != str(GAMES / plan["target"]["game_id"] / "server"):
        if previous in seen:
            raise ValueError("RESET_ANCESTRY_CYCLE")
        seen.add(previous)
        if previous == plan["target"]["data_source"]:
            raise ValueError("RESET_CURRENT_WORLD_PROTECTED")
        path = Path(previous)
        game = plan["target"]["game_id"]
        if path.name != "server" or parent(game, path.parent.name) != path.parent:
            raise ValueError("RESET_ANCESTRY_IDENTITY")
        directory(path.parent.parent)
        directory(path.parent)
        info = record(owner_path(path.parent))
        if (
            info["plan"]["target"]["data_source"] != previous
            or info["plan"]["target"]["game_id"] != game
        ):
            raise ValueError("RESET_ANCESTRY_OWNER")
        previous = info["plan"]["source"]["data_source"]
        kept += 1
        if kept <= plan["policy"]["retain_previous"] or info.get("protected") is True:
            if info["phase"] != "initialized" or not (path / "world/level.dat").is_file():
                raise ValueError("RESET_PROTECTED_WORLD_UNAVAILABLE")
            continue
        if info["phase"] not in {"initialized", "deleting", "deleted"}:
            raise ValueError("RESET_CLEANUP_WORLD_NOT_ELIGIBLE")
        if info["phase"] == "deleted":
            if path.exists() or path.is_symlink():
                raise ValueError("RESET_DELETED_WORLD_REAPPEARED")
            continue
        if path.exists() or path.is_symlink():
            tree(path, device=GAMES.stat().st_dev)
        elif info["phase"] != "deleting":
            raise ValueError("RESET_WORLD_MISSING_BEFORE_DELETE")
        candidates.append((path, info))
    for path, info in candidates:
        if record(owner_path(path.parent)) != info:
            raise ValueError("RESET_CLEANUP_OWNER_CHANGED")
        if path.exists() or path.is_symlink():
            tree(path, device=GAMES.stat().st_dev)
        atomic(owner_path(path.parent), json.dumps({**info, "phase": "deleting"}))
        if path.exists():
            # fd-based rmtree refuses symlink substitution; parent is root-only and no runtime
            # can bind this ancestor while the caller owns the global lease and host flock.
            if not shutil.rmtree.avoids_symlink_attacks:
                raise ValueError("RESET_SAFE_DELETE_UNAVAILABLE")
            shutil.rmtree(path)
        sync_directory(path.parent)
        atomic(owner_path(path.parent), json.dumps({**info, "phase": "deleted"}))
        deleted.append(path.parent.name)
    return deleted
