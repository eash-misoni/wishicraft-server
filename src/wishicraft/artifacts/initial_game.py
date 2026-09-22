"""First materialization under operation-v2's host lock and verified mount."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from wishicraft.artifacts import reset_worlds as worlds
except ImportError:
    import importlib

    worlds = importlib.import_module("reset_worlds")


def prepare(
    game: dict[str, Any],
    config: dict[str, Any],
    target: dict[str, str],
    atomic: Callable[[Path, str], None],
    *,
    uid: int = 993,
    gid: int = 993,
    verify: Callable[[], None] | None = None,
) -> None:
    game_id = game["game_id"]
    creation = game["creation"]
    if (
        re.fullmatch(r"game-[0-9a-f]{64}", game_id) is None
        or target["game_id"] != game_id
        or target["data_source"] != str(worlds.GAMES / game_id / "server")
        or not _config_matches(game, target)
        or creation["operation_id"] != "op-" + game_id[5:]
        or type(game["world"]["seed"]) is not int
        or not -(2**63) <= game["world"]["seed"] < 2**63
    ):
        raise ValueError("INITIAL_GAME_IDENTITY")
    worlds.directory(worlds.GAMES)
    if "import" in creation:
        try:
            from wishicraft.artifacts import world_import
        except ImportError:
            import importlib

            world_import = importlib.import_module("world_import")
        if verify is None:
            raise ValueError("IMPORT_AUTHORIZATION_REQUIRED")
        world_import.prepare(game, target, atomic, uid=uid, gid=gid, verify=verify)
        return
    parent = worlds.GAMES / game_id
    owner = worlds.GAMES / (game_id + ".initial-owner.json")
    plan = {
        "creation": creation,
        "game_id": game_id,
        "seed": game["world"]["seed"],
        "data_source": target["data_source"],
    }
    content = {
        "server.properties": "level-name=world\nonline-mode=true\nwhite-list=true\n"
        "enforce-whitelist=true\nlevel-seed=" + str(plan["seed"]) + "\n",
        "whitelist.json": json.dumps(config["initial_whitelist"], sort_keys=True) + "\n",
    }
    hashes = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in content.items()}
    if owner.exists() or owner.is_symlink():
        record = worlds.record(owner)
        if record.get("plan") != plan or record.get("files") != hashes:
            raise ValueError("INITIAL_OWNER_CONFLICT")
    else:
        if parent.exists() or parent.is_symlink():
            raise ValueError("INITIAL_UNOWNED_DATA")
        if shutil.disk_usage(worlds.GAMES).free < 4294967296:
            raise ValueError("INITIAL_INSUFFICIENT_CAPACITY")
        record = {"plan": plan, "phase": "preparing", "files": hashes}
        atomic(owner, json.dumps(record))
    if record["phase"] in {"prepared", "initialized"}:
        worlds.directory(parent)
        server = parent / "server"
        worlds.directory(server, owner=uid)
        if (
            record["phase"] == "initialized" or game["materialization_state"] == "MATERIALIZED"
        ) and not (server / "world/level.dat").is_file():
            raise ValueError("INITIAL_WORLD_MISSING")
        return
    if record["phase"] != "preparing":
        raise ValueError("INITIAL_OWNER_PHASE")
    parent.mkdir(mode=0o755, exist_ok=True)
    worlds.directory(parent)
    server = parent / "server"
    server.mkdir(mode=0o750, exist_ok=True)
    if (
        server.is_symlink()
        or server.stat().st_dev != worlds.GAMES.stat().st_dev
        or any(p.name not in content for p in server.iterdir())
    ):
        raise ValueError("INITIAL_UNKNOWN_DATA")
    for name, value in content.items():
        path = server / name
        if path.exists() or path.is_symlink():
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_nlink != 1
                or path.read_text() != value
            ):
                raise ValueError("INITIAL_FILE_CONFLICT")
        else:
            atomic(path, value)
        os.chown(path, uid, gid)
        path.chmod(0o640)
    os.chown(server, uid, gid)
    worlds.sync_directory(server)
    worlds.sync_directory(parent)
    atomic(owner, json.dumps({**record, "phase": "prepared"}))


def _config_matches(game: dict[str, Any], target: dict[str, str]) -> bool:
    created = game["creation"]["config_digest"]
    if created == target["config_digest"]:
        return True
    try:
        from wishicraft.artifacts.game_package import compatible_config
    except ImportError:
        import importlib

        compatible_config = importlib.import_module("game_package").compatible_config
    return bool(
        compatible_config(
            created, target["config_digest"], game.get("package", {}).get("definition", {})
        )
    )


def initialized(target: dict[str, str], atomic: Callable[[Path, str], None]) -> bool:
    """Return false only for legacy Games; never grant regeneration of initialized data."""
    owner = worlds.GAMES / (target["game_id"] + ".initial-owner.json")
    if not owner.exists() and not owner.is_symlink():
        return False
    record = worlds.record(owner)
    if (
        record["plan"]["game_id"] != target["game_id"]
        or record["plan"]["data_source"] != target["data_source"]
    ):
        raise ValueError("INITIAL_OWNER_TARGET")
    if record["phase"] not in {"prepared", "initialized"}:
        raise ValueError("INITIAL_NOT_PREPARED")
    level = (
        record["plan"]["creation"].get("import", {}).get("source", {}).get("level_name", "world")
    )
    if (Path(target["data_source"]) / level / "level.dat").is_file():
        atomic(owner, json.dumps({**record, "phase": "initialized"}))
    elif record["phase"] == "initialized":
        raise ValueError("INITIAL_WORLD_MISSING")
    return True
