"""Immutable Vanilla/NeoForge/Paper packages and inactive, Game-private artifact preparation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

GAMES = Path("/srv/minecraft/games")
OWNER_UID, OWNER_GID = 0, 0


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fields(value: Any, names: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != names:
        raise ValueError("PACKAGE_SCHEMA")


def artifact(value: Any, *, mod: bool, version: str = "") -> None:
    names = {"filename", "url", "size", "sha256"}
    if mod:
        names |= {
            "mod_id",
            "version",
            "client_required",
            "source",
            "project_id",
            "version_id",
            "file_id",
        }
    fields(value, names)
    if (
        not isinstance(value["filename"], str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,160}\.jar", value["filename"]) is None
        or type(value["size"]) is not int
        or not 0 < value["size"] <= 128 * 1024 * 1024
        or not isinstance(value["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("PACKAGE_ARTIFACT")
    if mod:
        if (
            value["source"] != "modrinth"
            or type(value["client_required"]) is not bool
            or not isinstance(value["mod_id"], str)
            or re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value["mod_id"]) is None
            or not isinstance(value["version"], str)
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value["version"]) is None
            or any(
                not isinstance(value[k], str) or re.fullmatch(r"[A-Za-z0-9]{8}", value[k]) is None
                for k in ("project_id", "version_id", "file_id")
            )
        ):
            raise ValueError("PACKAGE_MOD_IDENTITY")
        url = (
            "https://cdn.modrinth.com/data/"
            + value["project_id"]
            + "/versions/"
            + value["version_id"]
            + "/"
            + value["filename"]
        )
    else:
        filename = "neoforge-" + version + "-installer.jar"
        if value["filename"] != filename:
            raise ValueError("PACKAGE_INSTALLER_VERSION")
        url = (
            "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
            + version
            + "/"
            + filename
        )
    if value["url"] != url:
        raise ValueError("PACKAGE_CANONICAL_URL")


def paper_artifact(loader: dict[str, Any], version: str) -> None:
    fields(loader, {"type", "build", "commit", "server", "level_name"})
    if (
        version != "26.1.2"
        or type(loader["build"]) is not int
        or loader["build"] != 53
        or loader["commit"] != "39a1aa5c7fa9742accf82c247a0ea18014788b5f"
        or loader["level_name"] != "wishinkaiwai"
    ):
        raise ValueError("UNSUPPORTED_PAPER_PACKAGE")
    spec = loader["server"]
    fields(spec, {"filename", "url", "size", "sha256"})
    checksum = "6934188878fc351e1be5bfba5f2b8c4591224886e4b34e3de09dbec68a351caf"
    filename = "paper-26.1.2-53.jar"
    if (
        spec
        != {
            "filename": filename,
            "size": 52926064,
            "sha256": checksum,
            "url": "https://fill-data.papermc.io/v1/objects/" + checksum + "/" + filename,
        }
        or type(spec["size"]) is not int
    ):
        raise ValueError("PAPER_ARTIFACT_PIN")


def validate(package: Any) -> dict[str, Any]:
    fields(package, {"package_id", "package_version", "minecraft_version", "loader", "mods"})
    for name, pattern in [
        ("package_id", r"[a-z][a-z0-9-]{1,63}"),
        ("package_version", r"(?:[1-9][0-9]*|initial-fixed-version)"),
        ("minecraft_version", r"[0-9]+(?:\.[0-9]+){1,2}"),
    ]:
        if not isinstance(package[name], str) or re.fullmatch(pattern, package[name]) is None:
            raise ValueError("PACKAGE_FIXED_VERSION")
    loader = package["loader"]
    if not isinstance(loader, dict) or not isinstance(package["mods"], list):
        raise ValueError("PACKAGE_LOADER")
    if loader.get("type") == "vanilla":
        fields(loader, {"type"})
        if package["mods"]:
            raise ValueError("VANILLA_WITH_MODS")
    elif loader.get("type") == "paper":
        paper_artifact(loader, package["minecraft_version"])
        if package["mods"]:
            raise ValueError("PAPER_WITH_MODS")
    elif loader.get("type") == "neoforge":
        fields(loader, {"type", "version", "installer"})
        if (
            package["minecraft_version"] != "1.21.1"
            or not isinstance(loader["version"], str)
            or re.fullmatch(r"21\.1\.[0-9]+", loader["version"]) is None
            or not 1 <= len(package["mods"]) <= 8
        ):
            raise ValueError("UNSUPPORTED_NEOFORGE_PACKAGE")
        artifact(loader["installer"], mod=False, version=loader["version"])
        for entry in package["mods"]:
            artifact(entry, mod=True)
        for field in ("mod_id", "filename", "project_id"):
            if len({m[field] for m in package["mods"]}) != len(package["mods"]):
                raise ValueError("DUPLICATE_PACKAGE_MOD")
    else:
        raise ValueError("UNSUPPORTED_PACKAGE_LOADER")
    return dict(package)


def catalog(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("PACKAGE_CATALOG")
    result = [validate(p) for p in value]
    if len({(p["package_id"], p["package_version"]) for p in result}) != len(result):
        raise ValueError("PACKAGE_CATALOG_DUPLICATE")
    return result


def load() -> list[dict[str, Any]]:
    document = json.loads(Path(__file__).with_name("game-packages.json").read_text())
    fields(document, {"schema_version", "packages"})
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("PACKAGE_CATALOG_SCHEMA")
    return catalog(document["packages"])


def select(packages: Any, reference: Any) -> dict[str, Any]:
    if not isinstance(reference, dict):
        raise ValueError("PACKAGE_REFERENCE")
    matches = [
        p
        for p in catalog(packages)
        if all(reference.get(k) == p[k] for k in ("package_id", "package_version"))
    ]
    if len(matches) != 1:
        raise ValueError("PACKAGE_NOT_DEPLOYED")
    return matches[0]


def registered(
    game: dict[str, Any], manifest: dict[str, Any], config_digest: str
) -> dict[str, Any]:
    package = select(manifest["packages"], game["package"])
    if game.get("runtime", {}).get("class") != "default":
        raise ValueError("PACKAGE_RUNTIME_CLASS")
    if "creation" in game:
        creation = game["creation"]
        if (
            not compatible_config(creation.get("config_digest"), config_digest, package)
            or creation.get("package_digest") != digest(package)
            or game["package"].get("definition") != package
        ):
            raise ValueError("PACKAGE_REGISTRATION_MISMATCH")
        if "import" in creation:
            try:
                from wishicraft.artifacts import world_import
            except ImportError:
                import importlib

                world_import = importlib.import_module("world_import")
            world_import.validate(creation["import"], package)
            if creation.get("reset_policy") is not None:
                raise ValueError("IMPORT_RESET_NOT_SUPPORTED")
    elif game["game_id"] not in manifest["games"] or package["loader"]["type"] != "vanilla":
        raise ValueError("PACKAGE_LEGACY_MISMATCH")
    return package


def compatible_config(created: Any, current: str, package: dict[str, Any]) -> bool:
    """Accept only the reviewed complete append-only catalog transition.

    Creation and on-disk owner provenance remain immutable. This does not authorize
    an old Operation/receipt to execute under a different runtime target digest.
    """
    if created == current:
        return True
    paper_path = Path(__file__).with_name("paper-transition.json")
    if paper_path.is_file() and not paper_path.is_symlink():
        frozen = paper_path.read_bytes()
        if (
            hashlib.sha256(frozen).hexdigest()
            != "1701549bcc821d4af471c118ba6c1192493b92a0fd217e97d426eca5390cb65b"
        ):
            raise ValueError("PAPER_TRANSITION_INTEGRITY")
        edge = json.loads(frozen)
        if current == digest(edge["successor"]):
            return any(
                created == digest(edge[k]) and package in edge[k]["packages"]
                for k in ("historical", "predecessor")
            )
    path = Path(__file__).with_name("catalog-transition.json")
    if not path.is_file() or path.is_symlink():
        return False
    transition = json.loads(path.read_text())
    fields(transition, {"schema_version", "predecessor", "successor"})
    if type(transition["schema_version"]) is not int or transition["schema_version"] != 1:
        raise ValueError("CATALOG_TRANSITION_SCHEMA")
    before, after = transition["predecessor"], transition["successor"]
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("CATALOG_TRANSITION_SCHEMA")
    previous, following = catalog(before["packages"]), catalog(after["packages"])
    if (
        {k: v for k, v in before.items() if k != "packages"}
        != {k: v for k, v in after.items() if k != "packages"}
        or len(following) != len(previous) + 1
        or following[:-1] != previous
        or following[-1]["package_id"] in {p["package_id"] for p in previous}
    ):
        raise ValueError("CATALOG_TRANSITION_NOT_APPEND_ONLY")
    return created == digest(before) and current == digest(after) and package in previous


def location(game_id: str) -> Path:
    if re.fullmatch(r"game-[a-z0-9-]+", game_id) is None:
        raise ValueError("PACKAGE_GAME_ID")
    return GAMES / game_id / "package-cache"


def client_requirements(game: dict[str, Any]) -> dict[str, Any] | None:
    """Read-only client instructions from immutable registration, without host paths."""
    definition = game.get("package", {}).get("definition")
    if definition is None:
        return None
    package = validate(definition)
    if game.get("creation", {}).get("package_digest") != digest(package):
        raise ValueError("PACKAGE_REGISTRATION_MISMATCH")
    return {
        "minecraft_version": package["minecraft_version"],
        "loader": {
            key: value
            for key, value in package["loader"].items()
            if key not in {"installer", "server"}
        },
        "mods": [
            {
                key: mod[key]
                for key in ("mod_id", "version", "filename", "sha256", "client_required", "url")
            }
            for mod in package["mods"]
        ],
    }


def directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != OWNER_UID
        or info.st_gid != OWNER_GID
        or info.st_mode & 0o022
        or info.st_dev != GAMES.stat().st_dev
    ):
        raise ValueError("PACKAGE_DIRECTORY_IDENTITY")


def regular(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != OWNER_UID
        or info.st_gid != OWNER_GID
        or info.st_mode & 0o022
    ):
        raise ValueError("PACKAGE_FILE_IDENTITY")


def verify_file(path: Path, spec: dict[str, Any]) -> None:
    regular(path)
    if (
        path.stat().st_size != spec["size"]
        or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]
    ):
        raise ValueError("PACKAGE_HASH_MISMATCH")


def fetch(spec: dict[str, Any]) -> bytes:
    request = urllib.request.Request(
        spec["url"], headers={"User-Agent": "Wishicraft/1.0 (https://wishicraft.net)"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.geturl() != spec["url"]:
            raise ValueError("PACKAGE_REDIRECT")
        value = response.read(spec["size"] + 1)
    if len(value) != spec["size"] or hashlib.sha256(value).hexdigest() != spec["sha256"]:
        raise ValueError("PACKAGE_DOWNLOAD_HASH")
    return bytes(value)


def prepare(game_id: str, package: dict[str, Any], atomic: Callable[[Path, str], None]) -> Path:
    """Caller holds verified mount, host flock and runtime lease; no container may be present."""
    validate(package)
    base = location(game_id)
    directory(GAMES)
    directory(base.parent)
    owner = base.parent / "package-owner.json"
    plan = {"game_id": game_id, "package": package}
    if owner.exists() or owner.is_symlink():
        regular(owner)
        if json.loads(owner.read_text()) != plan:
            raise ValueError("PACKAGE_OWNER_CONFLICT")
    else:
        if base.exists() or base.is_symlink():
            raise ValueError("PACKAGE_UNOWNED_CACHE")
        atomic(owner, canonical(plan))
    base.mkdir(mode=0o755, exist_ok=True)
    directory(base)
    mods = base / "mods"
    mods.mkdir(mode=0o755, exist_ok=True)
    directory(mods)
    entries = [(mods / m["filename"], m) for m in package["mods"]]
    if package["loader"]["type"] == "neoforge":
        installer = package["loader"]["installer"]
        entries.append((base / installer["filename"], installer))
    if package["loader"]["type"] == "paper":
        server = package["loader"]["server"]
        entries.append((base / server["filename"], server))
    expected = {p for p, _ in entries}
    allowed = expected | {Path(str(p) + ".partial") for p in expected} | {mods}
    if any(p not in allowed for p in [*base.iterdir(), *mods.iterdir()]):
        raise ValueError("PACKAGE_UNKNOWN_CACHE_FILE")
    for path, spec in entries:
        partial = Path(str(path) + ".partial")
        if partial.exists() or partial.is_symlink():
            regular(partial)
            partial.unlink()
        if path.exists() or path.is_symlink():
            verify_file(path, spec)
        else:
            value = fetch(spec)
            with partial.open("xb") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
            partial.chmod(0o444)
            verify_file(partial, spec)
            os.replace(partial, path)
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return base


def environment(package: dict[str, Any]) -> dict[str, str]:
    validate(package)
    loader = package["loader"]
    neo = loader["type"] == "neoforge"
    if loader["type"] == "paper":
        return {
            "TYPE": "PAPER",
            "VERSION": package["minecraft_version"],
            "NEOFORGE_VERSION": "",
            "NEOFORGE_INSTALLER": "",
            "NEOFORGE_FORCE_REINSTALL": "false",
            "PAPER_BUILD": str(loader["build"]),
            "PAPER_CUSTOM_JAR": "/wishicraft-package/" + loader["server"]["filename"],
            "SKIP_DOWNLOAD_DEFAULTS": "true",
            "LEVEL": loader["level_name"],
        }
    return {
        "TYPE": "NEOFORGE" if neo else "VANILLA",
        "VERSION": package["minecraft_version"],
        "NEOFORGE_VERSION": loader["version"] if neo else "",
        "NEOFORGE_INSTALLER": "/wishicraft-package/" + loader["installer"]["filename"]
        if neo
        else "",
        "NEOFORGE_FORCE_REINSTALL": "true" if neo else "false",
    }


def materialize_mods(
    target: dict[str, str],
    package: dict[str, Any],
    atomic: Callable[[Path, str], None],
    *,
    uid: int = 993,
    gid: int = 993,
) -> None:
    """Only this selected Game/generation gets copies; never remove unknown or corrupt data."""
    base = prepare(target["game_id"], package, atomic)
    server = Path(target["data_source"])
    prefix = re.escape(str(GAMES / target["game_id"]))
    if re.fullmatch(prefix + r"/(?:worlds/op-[a-z0-9-]+/)?server", str(server)) is None:
        raise ValueError("PACKAGE_DATA_SOURCE")
    directory(server.parent)
    info = server.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_dev != GAMES.stat().st_dev:
        raise ValueError("PACKAGE_SERVER_IDENTITY")
    owner = server.parent / "package-projection.json"
    plan = {"data_source": str(server), "package_digest": digest(package)}
    mods = server / "mods"
    if owner.exists() or owner.is_symlink():
        regular(owner)
        if json.loads(owner.read_text()) != plan:
            raise ValueError("PACKAGE_PROJECTION_CONFLICT")
    else:
        if mods.exists() or mods.is_symlink():
            info = mods.lstat()
            if (
                package["loader"]["type"] != "vanilla"
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != uid
                or any(mods.iterdir())
            ):
                raise ValueError("PACKAGE_UNOWNED_MODS")
        atomic(owner, canonical(plan))
    mods.mkdir(mode=0o755, exist_ok=True)
    info = mods.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_dev != server.stat().st_dev:
        raise ValueError("PACKAGE_MOD_DIRECTORY")
    os.chown(mods, uid, gid)
    expected = {m["filename"] for m in package["mods"]}
    if any(p.name not in expected | {n + ".partial" for n in expected} for p in mods.iterdir()):
        raise ValueError("PACKAGE_UNEXPECTED_MOD")
    for spec in package["mods"]:
        path = mods / spec["filename"]
        partial = Path(str(path) + ".partial")
        if partial.exists() or partial.is_symlink():
            info = partial.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (info.st_uid, info.st_gid) not in {(OWNER_UID, OWNER_GID), (uid, gid)}
            ):
                raise ValueError("PACKAGE_PARTIAL_IDENTITY")
            partial.unlink()
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != uid
                or info.st_gid != gid
                or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]
            ):
                raise ValueError("PACKAGE_MATERIALIZED_HASH")
            continue
        with partial.open("xb") as output:
            output.write((base / "mods" / spec["filename"]).read_bytes())
            output.flush()
            os.fsync(output.fileno())
        os.chown(partial, uid, gid)
        partial.chmod(0o640)
        os.replace(partial, path)
    descriptor = os.open(mods, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def projection(game_id: str, package: dict[str, Any]) -> dict[str, str]:
    return {
        "GAME_PACKAGE_DIRECTORY": str(location(game_id)),
        "WISHICRAFT_PACKAGE_DIGEST": digest(package),
        **{"WISHICRAFT_PACKAGE_" + k: v for k, v in environment(package).items()},
    }


def observed(
    actual: dict[str, Any], manifest: dict[str, Any], target: dict[str, str]
) -> dict[str, Any]:
    """Exact runtime settings and readonly Game-local mounts, not the presence of a jar name."""
    base = location(target["game_id"])
    owner = base.parent / "package-owner.json"
    directory(base)
    regular(owner)
    plan = json.loads(owner.read_text())
    package = select(manifest["packages"], plan["package"])
    if plan != {"game_id": target["game_id"], "package": package}:
        raise ValueError("PACKAGE_OBSERVATION_OWNER")
    env = dict(v.split("=", 1) for v in actual["Config"]["Env"])
    if any(env.get(k) != v for k, v in environment(package).items()):
        raise ValueError("PACKAGE_OBSERVATION_ENV")
    if actual["Config"]["Labels"].get("com.wishicraft.package-digest") != digest(package):
        raise ValueError("PACKAGE_OBSERVATION_DIGEST")
    for destination, source in [("/wishicraft-package", base)]:
        mounts = [m for m in actual["Mounts"] if m["Destination"] == destination]
        if len(mounts) != 1 or mounts[0]["Source"] != str(source) or mounts[0]["RW"]:
            raise ValueError("PACKAGE_OBSERVATION_MOUNT")
    mods = base / "mods"
    directory(mods)
    if {p.name for p in mods.iterdir()} != {m["filename"] for m in package["mods"]}:
        raise ValueError("PACKAGE_OBSERVATION_MODS")
    for mod in package["mods"]:
        verify_file(mods / mod["filename"], mod)
    projected = Path(target["data_source"]) / "mods"
    if not stat.S_ISDIR(projected.lstat().st_mode):
        raise ValueError("PACKAGE_MOD_DIRECTORY")
    if {p.name for p in projected.iterdir()} != {m["filename"] for m in package["mods"]}:
        raise ValueError("PACKAGE_MATERIALIZED_MODS")
    for mod in package["mods"]:
        path = projected / mod["filename"]
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or hashlib.sha256(path.read_bytes()).hexdigest() != mod["sha256"]
        ):
            raise ValueError("PACKAGE_MATERIALIZED_HASH")
    if package["loader"]["type"] == "neoforge":
        spec = package["loader"]["installer"]
        verify_file(base / spec["filename"], spec)
    if package["loader"]["type"] == "paper":
        spec = package["loader"]["server"]
        verify_file(base / spec["filename"], spec)
    return package
