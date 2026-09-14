"""Pinned package integrity, interrupted writes and generation/Game isolation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def filesystem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    games = tmp_path / "games"
    games.mkdir(mode=0o755)
    monkeypatch.setattr(packages, "GAMES", games)
    monkeypatch.setattr(packages, "OWNER_UID", os.getuid())
    monkeypatch.setattr(packages, "OWNER_GID", os.getgid())
    package = packages.load()[1]
    for artifact in [*package["mods"], package["loader"]["installer"]]:
        content = artifact["filename"].encode()
        artifact.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(packages, "fetch", lambda spec: spec["filename"].encode())
    for game in ("game-a", "game-b"):
        server = games / game / "server"
        server.mkdir(parents=True, mode=0o755)
        (server / "world").mkdir()
        (server / "world/level.dat").write_bytes(game.encode())
    return games, package


def materialize(games: Path, package: dict[str, Any], game: str = "game-a") -> None:
    packages.materialize_mods(
        {"game_id": game, "data_source": str(games / game / "server")},
        package,
        atomic,
        uid=os.getuid(),
        gid=os.getgid(),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("minecraft_version", "latest"),
        ("package_version", "^1"),
        ("minecraft_version", "1.21.2"),
    ],
)
def test_floating_and_unsupported_versions(field: str, value: str) -> None:
    candidate = packages.load()[1]
    candidate[field] = value
    with pytest.raises(ValueError):
        packages.validate(candidate)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "f" * 63),
        ("filename", "../mod.jar"),
        ("url", "https://example.com/latest.jar"),
        ("version", ">=6.0"),
        ("size", True),
        ("client_required", False),
        ("file_id", "latest"),
    ],
)
def test_invalid_artifact(field: str, value: Any) -> None:
    candidate = packages.load()[1]
    candidate["mods"][0][field] = value
    with pytest.raises(ValueError):
        packages.validate(candidate)


def test_duplicate_and_loader_mismatch() -> None:
    package = packages.load()[1]
    package["mods"].append(copy.deepcopy(package["mods"][0]))
    with pytest.raises(ValueError, match="DUPLICATE"):
        packages.validate(package)
    package = packages.load()[1]
    package["loader"]["version"] = "21.1.220"
    with pytest.raises(ValueError, match="INSTALLER_VERSION"):
        packages.validate(package)


def test_manifest_commits_every_package_field_and_legacy_is_unchanged() -> None:
    cfg = load_configuration(ROOT, "dev")
    games = tuple(json.loads((ROOT / "config/two-game-dev.json").read_text()))

    def render(value: Any = None) -> Any:
        return render_boot_time_artifacts(
            cfg.project,
            cfg.stage,
            observed_uid=993,
            observed_gid=993,
            targeted=True,
            games=games,
            packages=value,
        )

    legacy = render()
    assert render(None) == legacy
    current = render(packages.load())
    assert current == render(packages.load()) and current.digest != legacy.digest
    manifest = json.loads(current.manifest_json)
    assert manifest["packages"] == packages.load()
    assert current.digest == hashlib.sha256(current.manifest_json.encode()).hexdigest()
    changed = packages.load()
    changed[1]["mods"][0]["sha256"] = "a" * 64
    assert render(changed).digest != current.digest
    compose = yaml.safe_load(current.compose_yaml)["services"]["minecraft"]
    assert compose["mem_limit"] == "6144MiB"
    assert "MAX_MEMORY=4G" in current.runtime_env and "INIT_MEMORY=1G" in current.runtime_env
    assert "TYPE=" not in current.runtime_env and "VERSION=" not in current.runtime_env
    assert "WISHICRAFT_PACKAGE_TYPE?" in compose["environment"]["TYPE"]


def test_registration_is_exact_and_legacy_only_vanilla() -> None:
    catalog = packages.load()
    package = catalog[1]
    manifest = {"packages": catalog, "games": ["game-a", "game-b"]}
    game = {
        "game_id": "game-new",
        "runtime": {"class": "default"},
        "package": {
            "package_id": package["package_id"],
            "package_version": package["package_version"],
            "definition": package,
        },
        "creation": {"config_digest": "a" * 64, "package_digest": packages.digest(package)},
    }
    assert packages.registered(game, manifest, "a" * 64) == package
    with pytest.raises(ValueError, match="REGISTRATION"):
        packages.registered(game, manifest, "b" * 64)
    game.pop("creation")
    game["game_id"] = "game-a"
    with pytest.raises(ValueError, match="LEGACY"):
        packages.registered(game, manifest, "a" * 64)
    game["package"] = {k: catalog[0][k] for k in ("package_id", "package_version")}
    assert packages.registered(game, manifest, "a" * 64)["loader"]["type"] == "vanilla"


def test_private_materialization_retry_and_world_preservation(filesystem: Any) -> None:
    games, package = filesystem
    materialize(games, package)
    cache = packages.location("game-a")
    files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in cache.rglob("*.jar")}
    materialize(games, package)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == prior for p, prior in files.items())
    materialize(games, packages.load()[0], "game-b")
    assert list((games / "game-b/server/mods").iterdir()) == []
    for game in ("game-a", "game-b"):
        assert (games / game / "server/world/level.dat").read_bytes() == game.encode()
    assert not (games / "game-b/server/libraries").exists()


def test_download_failure_and_partial_retry(
    filesystem: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    games, package = filesystem
    real_fetch = packages.fetch
    calls = 0

    def interrupted(spec: Any) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("upstream unavailable")
        return real_fetch(spec)

    monkeypatch.setattr(packages, "fetch", interrupted)
    with pytest.raises(OSError):
        materialize(games, package)
    first = packages.location("game-a") / "mods" / package["mods"][0]["filename"]
    prior = first.stat().st_mtime_ns
    partial = first.with_name(first.name + ".partial")
    partial.write_bytes(b"interrupted temporary")
    monkeypatch.setattr(packages, "fetch", real_fetch)
    materialize(games, package)
    assert first.stat().st_mtime_ns == prior and not partial.exists()
    projected = games / "game-a/server/mods" / first.name
    projected.with_name(projected.name + ".partial").write_bytes(b"partial projection")
    materialize(games, package)
    assert not projected.with_name(projected.name + ".partial").exists()


@pytest.mark.parametrize("where", ["cache", "projection"])
def test_corruption_never_becomes_vanilla(filesystem: Any, where: str) -> None:
    games, package = filesystem
    materialize(games, package)
    base = packages.location("game-a") if where == "cache" else games / "game-a/server"
    jar = base / "mods" / package["mods"][0]["filename"]
    jar.chmod(0o600)
    jar.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="HASH"):
        materialize(games, package)
    assert (games / "game-a/server/world/level.dat").read_bytes() == b"game-a"


def test_unowned_and_symlink_refused(filesystem: Any) -> None:
    games, package = filesystem
    cache = packages.location("game-a")
    cache.symlink_to(games / "game-b", target_is_directory=True)
    with pytest.raises(ValueError, match="UNOWNED"):
        materialize(games, package)
    cache.unlink()
    materialize(games, package)
    (cache / "mods/unknown.jar").symlink_to(games / "game-b/server/world/level.dat")
    with pytest.raises(ValueError, match="UNKNOWN"):
        materialize(games, package)
