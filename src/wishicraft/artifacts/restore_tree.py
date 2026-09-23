"""Stopped, operator-controlled source tree to durable prepared generation.

Caller holds host flock and a valid maintenance lease, verifies both EBS identities,
and supplies a read-only snapshot mount. This module never changes a Game pointer.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from wishicraft.artifacts import game_package as packages
    from wishicraft.artifacts import reset_worlds as worlds
    from wishicraft.artifacts import world_import as imported
    from wishicraft.artifacts import world_nbt
except ImportError:
    import importlib

    packages = importlib.import_module("game_package")
    worlds = importlib.import_module("reset_worlds")
    imported = importlib.import_module("world_import")
    world_nbt = importlib.import_module("world_nbt")


def source_path(mount: Path, plan: dict[str, Any]) -> Path:
    game = plan["game_id"]
    world = plan["source_world"].get("current_id")
    # Resolve the stored reference against the existing canonical layout, not filenames.
    expected = worlds.GAMES / game
    expected = expected / "worlds" / world / "server" if world else expected / "server"
    if str(expected) != plan["source_data_source"]:
        raise ValueError("RESTORE_SOURCE_BINDING")
    path = mount / expected.relative_to(worlds.GAMES.parent)
    candidate = mount
    for part in ("", *path.relative_to(mount).parts[:-1]):
        candidate = candidate / part
        if not stat.S_ISDIR(candidate.lstat().st_mode):
            raise ValueError("RESTORE_SOURCE_ANCESTOR")
    worlds.tree(path, device=mount.stat().st_dev)
    if world:
        owner = worlds.record(worlds.owner_path(path.parent))
        if (
            owner.get("phase") != "initialized"
            or owner["plan"]["target"]["game_id"] != game
            or owner["plan"]["target"]["data_source"] != str(expected)
        ):
            raise ValueError("RESTORE_SOURCE_OWNER")
    else:
        initial = mount / "games" / (game + ".initial-owner.json")
        if plan.get("source_creation") is not None and not initial.exists():
            raise ValueError("RESTORE_SOURCE_OWNER_MISSING")
        if initial.exists() or initial.is_symlink():
            owner = worlds.record(initial)
            if (
                owner.get("phase") != "initialized"
                or owner["plan"]["game_id"] != game
                or owner["plan"]["data_source"] != str(expected)
                or owner["plan"].get("creation") != plan.get("source_creation")
            ):
                raise ValueError("RESTORE_SOURCE_OWNER")
    return Path(path)


def level_name(plan: dict[str, Any]) -> str:
    package = packages.validate(plan["package"])
    if packages.digest(package) != plan["package_digest"]:
        raise ValueError("RESTORE_PACKAGE_DIGEST")
    return package["loader"].get("level_name", "world")  # type: ignore[no-any-return]


def inspect(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    level = level_name(plan)
    worlds.tree(root, device=root.stat().st_dev)
    document = world_nbt.read(root / level / "level.dat")["Data"]
    if document.get("Version", {}).get("Name") != plan["package"]["minecraft_version"]:
        raise ValueError("RESTORE_WORLD_VERSION")
    if not any((root / level).rglob("*.mca")):
        raise ValueError("RESTORE_WORLD_REGIONS_MISSING")
    return imported.tree(root)


def prepare(
    plan: dict[str, Any],
    mount: Path,
    *,
    atomic: Callable[[Path, str], None],
    verify: Callable[[], None],
    uid: int = 993,
    gid: int = 993,
) -> dict[str, Any]:
    def guarded_atomic(path: Path, value: str) -> None:
        verify()
        original_atomic(path, value)

    original_atomic = atomic
    atomic = guarded_atomic
    verify()
    source = source_path(mount, plan)
    level = level_name(plan)
    target = worlds.parent(plan["game_id"], plan["operation_id"])
    if str(target / "server") != plan["target_data_source"]:
        raise ValueError("RESTORE_TARGET_BINDING")
    current = Path(plan["previous_data_source"])
    if current == target / "server" or source == current:
        raise ValueError("RESTORE_IN_PLACE_FORBIDDEN")
    worlds.directory(worlds.GAMES)
    worlds.directory(worlds.GAMES / plan["game_id"])
    if not target.parent.exists():
        target.parent.mkdir(mode=0o700)
    worlds.directory(target.parent)
    owner_file = worlds.owner_path(target)
    if owner_file.exists() or owner_file.is_symlink():
        owner = worlds.record(owner_file)
        if owner.get("restore") != plan:
            raise ValueError("RESTORE_REQUEST_CONFLICT")
        if owner["phase"] == "initialized":
            raise ValueError("RESTORE_ALREADY_STARTED")
        if owner["phase"] == "prepared":
            if inspect(target / "server", plan) != owner["prepared_tree"]:
                raise ValueError("RESTORE_PREPARED_CHANGED")
            verify()
            cleanup_attempts(target, owner)
            return owner
        if owner["phase"] != "preparing":
            raise ValueError("RESTORE_OWNER_PHASE")
    else:
        if target.exists() or target.is_symlink():
            raise ValueError("RESTORE_UNOWNED_TARGET")
        owner = {
            "phase": "preparing",
            "restore": plan,
            "protected": True,
            "level_name": level,
            "plan": {
                "source": {"game_id": plan["game_id"], "data_source": str(current)},
                "target": {"game_id": plan["game_id"], "data_source": str(target / "server")},
            },
        }
        atomic(owner_file, packages.canonical(owner))
    if not target.exists():
        target.mkdir(mode=0o700)
    worlds.directory(target)
    server = target / "server"
    receipt_path = target / "validated.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        receipt = worlds.record(receipt_path)
        if receipt["restore"] != plan:
            raise ValueError("RESTORE_VALIDATION_CONFLICT")
        candidate = target / receipt["candidate"]
        if candidate.name != receipt["candidate"] or not candidate.name.startswith("staging-"):
            raise ValueError("RESTORE_CANDIDATE_IDENTITY")
    else:
        if server.exists() or server.is_symlink():
            raise ValueError("RESTORE_UNOWNED_COMMIT")
        before = imported.tree(source)
        previous_tree = imported.tree(current)
        if (
            before["expanded_size"] > imported.MAX_BYTES
            or before["file_count"] > imported.MAX_FILES
        ):
            raise ValueError("RESTORE_SOURCE_LIMIT")
        worlds.tree(current, device=worlds.GAMES.stat().st_dev)
        if shutil.disk_usage(target).free < before["expanded_size"] + imported.RESERVE:
            raise ValueError("RESTORE_INSUFFICIENT_CAPACITY")
        inspect(source, plan)
        verify()
        candidate = Path(tempfile.mkdtemp(prefix="staging-", dir=target))
        owner = {**owner, "attempts": [*owner.get("attempts", []), candidate.name]}
        atomic(owner_file, packages.canonical(owner))
        names = {level}
        loader = plan["package"]["loader"]["type"]
        if loader == "neoforge":
            names |= {"config", "defaultconfigs"}
        elif loader == "paper":
            names |= imported.CONFIGS
        for name in sorted(names):
            verify()
            path = source / name
            if not path.exists():
                if name == level or loader == "paper":
                    raise ValueError("RESTORE_WORLD_MISSING")
                continue
            destination = candidate / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                # A copy is private staging, not publication. Recheck after this bounded
                # tree copy; invoking AWS CLI for every file would exhaust the SSM deadline.
                shutil.copytree(path, destination)
                verify()
                if imported.tree(destination) != imported.tree(path):
                    raise ValueError("RESTORE_COPY_HASH")
            else:
                shutil.copyfile(path, destination)
                if imported.sha(destination) != imported.sha(path):
                    raise ValueError("RESTORE_COPY_HASH")
        # Keep current server policy, including OP/ban files. Snapshot access files never enter
        # staging. Whitelist is subsequently projected from the current control plane at START.
        for name in worlds.CONFIG_FILES:
            verify()
            path = current / name
            if path.exists():
                shutil.copyfile(path, candidate / name)
            elif name in {"server.properties", "whitelist.json"}:
                raise ValueError("RESTORE_CURRENT_POLICY_MISSING")
        source_props = properties(source / "server.properties")
        current_props = properties(candidate / "server.properties")
        if source_props.get("level-name") != level or current_props.get("level-name") != level:
            raise ValueError("RESTORE_LEVEL_NAME")
        for key in imported.PROPERTIES:
            if key in source_props:
                current_props[key] = source_props[key]
        (candidate / "server.properties").write_text(
            "".join(k + "=" + v + "\n" for k, v in sorted(current_props.items()))
        )
        if imported.tree(source) != before:
            raise ValueError("RESTORE_SOURCE_CHANGED")
        verify()
        for path in [candidate, *candidate.rglob("*")]:
            os.chown(path, uid, gid)
            path.chmod(0o750 if path.is_dir() else 0o640)
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        for path in [*reversed(sorted(p for p in candidate.rglob("*") if p.is_dir())), candidate]:
            worlds.sync_directory(path)
        receipt = {
            "restore": plan,
            "candidate": candidate.name,
            "source_tree": before,
            "prepared_tree": inspect(candidate, plan),
            "source_world_tree": imported.tree(source / level),
            "previous_tree": previous_tree,
        }
        if imported.tree(candidate / level) != receipt["source_world_tree"]:
            raise ValueError("RESTORE_COPY_HASH")
        atomic(receipt_path, packages.canonical(receipt))
    verify()
    if server.exists() or server.is_symlink():
        if (
            candidate.exists()
            or server.is_symlink()
            or inspect(server, plan) != receipt["prepared_tree"]
        ):
            raise ValueError("RESTORE_COMMIT_CONFLICT")
    else:
        if candidate.is_symlink() or inspect(candidate, plan) != receipt["prepared_tree"]:
            raise ValueError("RESTORE_CANDIDATE_CHANGED")
        verify()
        os.rename(candidate, server)
    worlds.sync_directory(target)
    verify()
    if current.parent.parent.name == "worlds":
        previous_owner = worlds.record(worlds.owner_path(current.parent))
        if previous_owner["plan"]["target"]["data_source"] != str(current):
            raise ValueError("RESTORE_PREVIOUS_OWNER")
        atomic(
            worlds.owner_path(current.parent),
            packages.canonical({**previous_owner, "protected": True}),
        )
    owner = {
        **owner,
        "phase": "prepared",
        **{
            k: receipt[k]
            for k in ("source_tree", "prepared_tree", "source_world_tree", "previous_tree")
        },
    }
    atomic(owner_file, packages.canonical(owner))
    verify()
    cleanup_attempts(target, owner)
    return owner


def cleanup_attempts(target: Path, owner: dict[str, Any]) -> None:
    # Only explicitly recorded failed attempts inside this root-owned generation may go.
    if any(
        p.name not in {"server", "validated.json", *owner.get("attempts", [])}
        for p in target.iterdir()
    ):
        raise ValueError("RESTORE_UNKNOWN_STAGING")
    for attempt in owner.get("attempts", []):
        partial = target / attempt
        if partial.name != attempt or not attempt.startswith("staging-"):
            raise ValueError("RESTORE_PARTIAL_IDENTITY")
        if partial.exists() or partial.is_symlink():
            worlds.tree(partial, device=target.stat().st_dev)
            if not shutil.rmtree.avoids_symlink_attacks:
                raise ValueError("RESTORE_SAFE_CLEANUP_UNAVAILABLE")
            shutil.rmtree(partial)
    worlds.sync_directory(target)


def properties(path: Path) -> dict[str, str]:
    import re

    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith(("#", "!")):
            continue
        match = re.fullmatch(r"([a-z0-9.-]+)=(.*)", line)
        if match is None or match[1] in result or (len(line) - len(line.rstrip("\\"))) % 2:
            raise ValueError("RESTORE_PROPERTIES_UNSUPPORTED")
        result[match[1]] = match[2]
    return result
