"""Operator-staged, identity-preserving Paper import into a never-started Game.

The caller owns the existing host flock, verified data mount and START lease.
No archive is extracted into a Game directory. No existing world is overwritten.
"""

# ruff: noqa: UP017 -- AL2023 Python 3.9
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from wishicraft.artifacts import game_package as packages
    from wishicraft.artifacts import world_nbt
except ImportError:
    import importlib

    packages = importlib.import_module("game_package")
    world_nbt = importlib.import_module("world_nbt")

STAGING = Path("/srv/minecraft/imports")
MAX_FILES = 100_000
MAX_BYTES = 16 * 1024**3
RESERVE = 4 * 1024**3
LEVEL = "wishinkaiwai"
CONFIGS = {"config/paper-global.yml", "config/paper-world-defaults.yml", "bukkit.yml", "spigot.yml"}
PROPERTIES = {
    "difficulty",
    "gamemode",
    "hardcore",
    "generate-structures",
    "level-seed",
    "level-type",
    "generator-settings",
    "view-distance",
    "simulation-distance",
}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        result = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            result.update(block)
        return result.hexdigest()


def validate(value: Any, package: dict[str, Any]) -> dict[str, Any]:
    packages.validate(package)
    packages.fields(
        value,
        {
            "schema_version",
            "source",
            "archive_sha256",
            "archive_size",
            "file_count",
            "expanded_size",
            "tree_sha256",
            "captured_at",
            "properties",
            "configs",
            "target_package_digest",
            "source_stopped",
            "save_confirmed",
            "filesystem_synced",
        },
    )
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or package["loader"]["type"] != "paper"
        or value["target_package_digest"] != packages.digest(package)
    ):
        raise ValueError("IMPORT_PACKAGE")
    source = value["source"]
    packages.fields(
        source,
        {
            "server_type",
            "minecraft_version",
            "paper_build",
            "paper_commit",
            "jar_sha256",
            "java_version",
            "data_version",
            "level_name",
            "online_mode",
            "seed",
        },
    )
    loader = package["loader"]
    if type(source["seed"]) is not int or not -(2**63) <= source["seed"] < 2**63:
        raise ValueError("IMPORT_SEED")
    if (
        source["server_type"] != "paper"
        or source["minecraft_version"] != package["minecraft_version"]
        or type(source["paper_build"]) is not int
        or source["paper_build"] != loader["build"]
        or source["paper_commit"] != loader["commit"]
        or source["jar_sha256"] != loader["server"]["sha256"]
        or source["level_name"] != LEVEL
        or source["online_mode"] is not True
        or type(source["data_version"]) is not int
        or source["data_version"] != 4790
        or not isinstance(source["java_version"], str)
        or re.fullmatch(r"25\.[0-9A-Za-z.+_-]{1,100}", source["java_version"]) is None
    ):
        raise ValueError("IMPORT_RUNTIME_IDENTITY")
    for key in ("source_stopped", "save_confirmed", "filesystem_synced"):
        if value[key] is not True:
            raise ValueError("IMPORT_SOURCE_NOT_FROZEN")
    for key in ("archive_sha256", "tree_sha256", "target_package_digest"):
        if not isinstance(value[key], str) or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            raise ValueError("IMPORT_DIGEST")
    for key, limit in [
        ("archive_size", MAX_BYTES),
        ("expanded_size", MAX_BYTES),
        ("file_count", MAX_FILES),
    ]:
        if type(value[key]) is not int or not 0 < value[key] <= limit:
            raise ValueError("IMPORT_LIMIT")
    if (
        not isinstance(value["captured_at"], str)
        or not value["captured_at"].endswith("Z")
        or datetime.fromisoformat(value["captured_at"].replace("Z", "+00:00")).tzinfo
        != timezone.utc
    ):
        raise ValueError("IMPORT_TIMESTAMP")
    props = value["properties"]
    packages.fields(props, PROPERTIES)
    if any(
        not isinstance(v, str) or len(v) > 4096 or any(c in v for c in "\r\n\x00")
        for v in props.values()
    ):
        raise ValueError("IMPORT_PROPERTIES")
    if (
        props["difficulty"] not in {"peaceful", "easy", "normal", "hard"}
        or props["gamemode"] not in {"survival", "creative", "adventure", "spectator"}
        or props["hardcore"] not in {"true", "false"}
        or props["generate-structures"] not in {"true", "false"}
        or any(
            re.fullmatch(r"[1-9][0-9]?", props[k]) is None
            for k in ("view-distance", "simulation-distance")
        )
    ):
        raise ValueError("IMPORT_PROPERTIES")
    packages.fields(value["configs"], CONFIGS)
    if any(
        not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
        for v in value["configs"].values()
    ):
        raise ValueError("IMPORT_CONFIG_HASH")
    return dict(value)


def properties(value: dict[str, Any]) -> str:
    # Source access files, RCON, network and identity settings are never projected.
    return (
        "level-name=" + LEVEL + "\nonline-mode=true\nwhite-list=true\n"
        "enforce-whitelist=true\n"
        + "".join(k + "=" + v + "\n" for k, v in sorted(value["properties"].items()))
    )


def member_path(name: str) -> str:
    name = name.removesuffix("/")
    parts = name.split("/")
    if (
        not name
        or len(name) > 1024
        or len(parts) > 32
        or any(p in {"", ".", ".."} for p in parts)
        or "\\" in name
        or ":" in name
        or unicodedata.normalize("NFC", name) != name
        or any(unicodedata.category(c).startswith("C") for c in name)
    ):
        raise ValueError("IMPORT_ARCHIVE_PATH")
    if parts[0] != LEVEL and name not in CONFIGS | {"config"}:
        raise ValueError("IMPORT_ARCHIVE_LAYOUT")
    return name


def tree(root: Path) -> dict[str, Any]:
    entries: list[list[Any]] = []
    count = size = 0
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        name = str(path.relative_to(root))
        if stat.S_ISDIR(info.st_mode):
            entries.append([name, "directory"])
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            count += 1
            size += info.st_size
            entries.append([name, info.st_size, sha(path)])
        else:
            raise ValueError("IMPORT_TREE_TYPE")
    return {"file_count": count, "expanded_size": size, "tree_sha256": packages.digest(entries)}


def extract(archive: Path, parent: Path, manifest: dict[str, Any]) -> Path:
    """Each attempt has a fresh private root; failed attempts remain diagnostic evidence."""
    packages.regular(archive)
    if (
        archive.stat().st_size != manifest["archive_size"]
        or sha(archive) != manifest["archive_sha256"]
    ):
        raise ValueError("IMPORT_ARCHIVE_HASH")
    if shutil.disk_usage(parent).free < manifest["expanded_size"] + RESERVE:
        raise ValueError("IMPORT_DISK_FREE")
    check_tar_headers(archive)
    output = Path(tempfile.mkdtemp(prefix="extract-", dir=parent))
    seen: dict[str, tuple[str, bool]] = {}
    explicit = set()
    count = size = members = 0
    with tarfile.open(archive, mode="r|") as tar:
        for entry in tar:
            members += 1
            if members > MAX_FILES * 2:
                raise ValueError("IMPORT_MEMBER_LIMIT")
            name = member_path(entry.name)
            if (
                not (entry.isdir() or entry.isreg())
                or entry.issparse()
                or entry.size < 0
                or entry.size > MAX_BYTES
            ):
                raise ValueError("IMPORT_ARCHIVE_TYPE")
            if name in explicit:
                raise ValueError("IMPORT_DUPLICATE_PATH")
            explicit.add(name)
            parts = name.split("/")
            for i in range(1, len(parts) + 1):
                prefix = "/".join(parts[:i])
                is_dir = i < len(parts) or entry.isdir()
                key = prefix.casefold()
                prior = seen.get(key)
                if prior is not None and prior != (prefix, is_dir):
                    raise ValueError("IMPORT_CASE_OR_TYPE_COLLISION")
                seen[key] = (prefix, is_dir)
            path = output / name
            if entry.isdir():
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            count += 1
            size += entry.size
            if count > manifest["file_count"] or size > manifest["expanded_size"]:
                raise ValueError("IMPORT_EXPANDED_LIMIT")
            if shutil.disk_usage(parent).free < entry.size + RESERVE:
                raise ValueError("IMPORT_DISK_FREE")
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = tar.extractfile(entry)
            if source is None:
                raise ValueError("IMPORT_ARCHIVE_FILE")
            with source, path.open("xb") as target:
                remaining = entry.size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("IMPORT_TRUNCATED")
                    target.write(block)
                    remaining -= len(block)
                target.flush()
                os.fsync(target.fileno())
    if tree(output) != {k: manifest[k] for k in ("file_count", "expanded_size", "tree_sha256")}:
        raise ValueError("IMPORT_TREE_HASH")
    inspect_world(output, manifest)
    return output


def check_tar_headers(archive: Path) -> None:
    """Reject compressed/PAX/GNU extension records before tarfile can expand metadata.

    The operator produces an uncompressed USTAR archive. Fixed 512-byte headers
    and bounded seeks also bound work on malformed or malicious extension payloads.
    """
    length = archive.stat().st_size
    with archive.open("rb") as stream:
        for _ in range(MAX_FILES * 2 + 1):
            block = stream.read(512)
            if block == bytes(512):
                if stream.read(512) != bytes(512):
                    raise ValueError("IMPORT_TAR_TERMINATOR")
                while tail := stream.read(1024 * 1024):
                    if any(tail):
                        raise ValueError("IMPORT_TAR_TRAILING")
                return
            if len(block) != 512:
                raise ValueError("IMPORT_TAR_TRUNCATED")
            entry = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            if entry.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}:
                raise ValueError("IMPORT_ARCHIVE_TYPE")
            if not 0 <= entry.size <= MAX_BYTES or (entry.isdir() and entry.size):
                raise ValueError("IMPORT_ARCHIVE_SIZE")
            position = stream.tell() + ((entry.size + 511) // 512) * 512
            if position > length:
                raise ValueError("IMPORT_TAR_TRUNCATED")
            stream.seek(position)
    raise ValueError("IMPORT_MEMBER_LIMIT")


def inspect_world(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    for name, expected in manifest["configs"].items():
        if sha(root / name) != expected:
            raise ValueError("IMPORT_CONFIG_HASH")
        # These are reviewed source configs, not an arbitrary config upload facility.
        for line in (root / name).read_text().splitlines():
            if re.search(r"(?i)(?:secret|password|token):", line) and not re.search(
                r":\s*(?:''|\"\"|null)?\s*$", line
            ):
                raise ValueError("IMPORT_CONFIG_SECRET")
    world = root / LEVEL
    level = world_nbt.read(world / "level.dat")["Data"]
    if (
        level.get("DataVersion") != manifest["source"]["data_version"]
        or level.get("Version", {}).get("Name") != manifest["source"]["minecraft_version"]
        or level.get("LevelName") != LEVEL
    ):
        raise ValueError("IMPORT_WORLD_IDENTITY")
    dimensions = world / "dimensions/minecraft"
    if {p.name for p in (world / "dimensions").iterdir()} != {"minecraft"} or {
        p.name for p in dimensions.iterdir()
    } != {"overworld", "the_nether", "the_end"}:
        raise ValueError("IMPORT_CUSTOM_DIMENSIONS_REVIEW_REQUIRED")
    for name in ("overworld", "the_nether", "the_end"):
        if not any((dimensions / name / "region").glob("*.mca")):
            raise ValueError("IMPORT_DIMENSION_MISSING")
    settings = world_nbt.read(dimensions / "overworld/data/minecraft/world_gen_settings.dat")[
        "data"
    ]
    if settings.get("seed") != manifest["source"]["seed"]:
        raise ValueError("IMPORT_SEED")
    players = []
    for path in sorted((world / "players/data").glob("*.dat")):
        player = world_nbt.read(path)
        if not 0 < player.get("DataVersion", 0) <= manifest["source"]["data_version"]:
            raise ValueError("IMPORT_PLAYER_VERSION")
        players.append(
            {
                "uuid": path.stem,
                "sha256": sha(path),
                "inventory_items": len(player.get("Inventory", [])),
                "ender_items": len(player.get("EnderItems", [])),
                "position": player.get("Pos"),
            }
        )
    return {"data_version": level["DataVersion"], "players": players}


def expected_level(target: dict[str, str]) -> str:
    owner = packages.GAMES / (target["game_id"] + ".initial-owner.json")
    if not owner.exists() and not owner.is_symlink():
        return "world"
    packages.regular(owner)
    record = json.loads(owner.read_text())
    if (
        record["plan"]["data_source"] != target["data_source"]
        or record["plan"]["game_id"] != target["game_id"]
    ):
        raise ValueError("IMPORT_OWNER_TARGET")
    imported = record["plan"]["creation"].get("import")
    return LEVEL if imported is not None else "world"


def prepare(
    game: dict[str, Any],
    target: dict[str, str],
    atomic: Callable[[Path, str], None],
    *,
    uid: int,
    gid: int,
    verify: Callable[[], None],
) -> None:
    verify()
    manifest = validate(game["creation"]["import"], game["package"]["definition"])
    if (
        game["world"]["generation"] != 1
        or game["creation"]["reset_policy"] is not None
        or game["world"]["seed"] != manifest["source"]["seed"]
        or target["data_source"] != str(packages.GAMES / game["game_id"] / "server")
    ):
        raise ValueError("IMPORT_GAME_IDENTITY")
    parent = Path(target["data_source"]).parent
    server = parent / "server"
    owner = packages.GAMES / (game["game_id"] + ".initial-owner.json")
    plan = {
        "creation": game["creation"],
        "game_id": game["game_id"],
        "seed": game["world"]["seed"],
        "data_source": str(server),
    }
    if owner.exists() or owner.is_symlink():
        packages.regular(owner)
        record = json.loads(owner.read_text())
        if record.get("plan") != plan:
            raise ValueError("IMPORT_OWNER_CONFLICT")
        if record.get("phase") in {"prepared", "initialized"}:
            packages.directory(parent)
            if (
                server.is_symlink()
                or not server.is_dir()
                or (server / LEVEL).is_symlink()
                or (server / LEVEL / "level.dat").is_symlink()
                or not (server / LEVEL / "level.dat").is_file()
            ):
                raise ValueError("IMPORT_WORLD_MISSING")
            level = world_nbt.read(server / LEVEL / "level.dat")["Data"]
            if (
                level.get("DataVersion") != manifest["source"]["data_version"]
                or level.get("Version", {}).get("Name") != manifest["source"]["minecraft_version"]
                or level.get("LevelName") != LEVEL
            ):
                raise ValueError("IMPORT_WORLD_IDENTITY")
            return
        if record.get("phase") != "preparing":
            raise ValueError("IMPORT_OWNER_PHASE")
    else:
        if (
            parent.exists()
            or parent.is_symlink()
            or game["materialization_state"] != "UNMATERIALIZED"
        ):
            raise ValueError("IMPORT_EXISTING_GAME")
        record = {"plan": plan, "phase": "preparing"}
        atomic(owner, packages.canonical(record))
    packages.directory(STAGING)
    staged = STAGING / manifest["archive_sha256"]
    packages.directory(staged)
    parent.mkdir(mode=0o755, exist_ok=True)
    packages.directory(parent)
    receipt = staged / (game["game_id"] + ".validated.json")
    if receipt.exists() or receipt.is_symlink():
        packages.regular(receipt)
        validated = json.loads(receipt.read_text())
        if validated.get("plan") != plan:
            raise ValueError("IMPORT_VALIDATION_CONFLICT")
        candidate = staged / validated["candidate"]
        if (
            validated["candidate"] != candidate.name
            or re.fullmatch(r"extract-[a-z0-9_]+", candidate.name) is None
        ):
            raise ValueError("IMPORT_CANDIDATE")
    else:
        if server.exists() or server.is_symlink():
            raise ValueError("IMPORT_UNOWNED_COMMIT")
        candidate = extract(staged / "source.tar", staged, manifest)
        (candidate / "server.properties").write_text(properties(manifest))
        (candidate / "whitelist.json").write_text("[]\n")
        for path in [candidate, *candidate.rglob("*")]:
            os.chown(path, uid, gid)
            path.chmod(0o750 if path.is_dir() else 0o640)
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        for path in [*reversed(sorted(p for p in candidate.rglob("*") if p.is_dir())), candidate]:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        validated = {
            "plan": plan,
            "candidate": candidate.name,
            "tree": tree(candidate),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic(receipt, packages.canonical(validated))
    verify()
    # Rename is the sole visibility boundary. Receipt precedes it for crash recovery.
    if server.exists() or server.is_symlink():
        if candidate.exists() or server.is_symlink() or tree(server) != validated["tree"]:
            raise ValueError("IMPORT_COMMIT_CONFLICT")
    else:
        if candidate.is_symlink() or tree(candidate) != validated["tree"]:
            raise ValueError("IMPORT_CANDIDATE_CHANGED")
        verify()
        os.rename(candidate, server)
    for path in (parent, staged):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    verify()
    atomic(owner, packages.canonical({**record, "phase": "prepared", "import": validated}))
