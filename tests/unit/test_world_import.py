"""External archive rejection, exact runtime identity and first-generation ownership."""

from __future__ import annotations

import copy
import gzip
import io
import json
import os
import struct
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_game_creation import creation  # noqa: F401
from tests.unit.test_web_operations import boundary  # noqa: F401
from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import initial_game, reset_worlds
from wishicraft.artifacts import world_import as imp
from wishicraft.artifacts.targeted_runtime import atomic


def nbt(value: dict[str, Any]) -> bytes:
    def string(s: str) -> bytes:
        v = s.encode()
        return struct.pack(">H", len(v)) + v

    def compound(v: dict[str, Any]) -> bytes:
        result = b""
        for key, child in v.items():
            if isinstance(child, dict):
                tag, body = 10, compound(child)
            elif isinstance(child, str):
                tag, body = 8, string(child)
            else:
                tag, body = 4, struct.pack(">q", child)
            result += bytes([tag]) + string(key) + body
        return result + b"\0"

    return gzip.compress(b"\x0a\0\0" + compound(value))


@pytest.fixture
def source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    for module in (packages, reset_worlds):
        monkeypatch.setattr(module, "GAMES", tmp_path / "games")
    monkeypatch.setattr(packages, "OWNER_UID", os.getuid())
    monkeypatch.setattr(packages, "OWNER_GID", os.getgid())
    monkeypatch.setattr(reset_worlds, "OWNER_UID", os.getuid())
    monkeypatch.setattr(reset_worlds, "OWNER_GID", os.getgid())
    monkeypatch.setattr(imp, "STAGING", tmp_path / "imports")
    packages.GAMES.mkdir(mode=0o755)
    imp.STAGING.mkdir(mode=0o755)
    root = tmp_path / "source"
    root.mkdir()
    for name in imp.CONFIGS:
        p = root / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("_version: 31\n")
    world = root / imp.LEVEL
    world.mkdir()
    (world / "level.dat").write_bytes(
        nbt({"Data": {"DataVersion": 4790, "Version": {"Name": "26.1.2"}, "LevelName": imp.LEVEL}})
    )
    for dim in ("overworld", "the_nether", "the_end"):
        p = world / "dimensions/minecraft" / dim / "region"
        p.mkdir(parents=True)
        (p / "r.0.0.mca").write_bytes(b"preserved-test-chunks")
    p = world / "dimensions/minecraft/overworld/data/minecraft"
    p.mkdir(parents=True)
    (p / "world_gen_settings.dat").write_bytes(nbt({"data": {"seed": -123}}))
    (world / "players/data").mkdir(parents=True)
    package = packages.load()[-1]
    value = {
        "schema_version": 1,
        "source": {
            "server_type": "paper",
            "minecraft_version": "26.1.2",
            "paper_build": 53,
            "paper_commit": package["loader"]["commit"],
            "jar_sha256": package["loader"]["server"]["sha256"],
            "java_version": "25.0.3+9-LTS",
            "data_version": 4790,
            "level_name": imp.LEVEL,
            "online_mode": True,
            "seed": -123,
        },
        "captured_at": "2026-09-22T00:00:00Z",
        "source_stopped": True,
        "save_confirmed": True,
        "filesystem_synced": True,
        "target_package_digest": packages.digest(package),
        "properties": {
            "difficulty": "easy",
            "gamemode": "survival",
            "hardcore": "false",
            "generate-structures": "true",
            "level-seed": "",
            "level-type": "minecraft\\:normal",
            "generator-settings": "{}",
            "view-distance": "10",
            "simulation-distance": "10",
        },
        "configs": {name: imp.sha(root / name) for name in imp.CONFIGS},
        **imp.tree(root),
    }
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as tar:
        for path in sorted(root.iterdir()):
            tar.add(path, arcname=path.name)
    value.update(archive_size=archive.stat().st_size, archive_sha256=imp.sha(archive))
    staged = imp.STAGING / value["archive_sha256"]
    staged.mkdir(mode=0o755)
    archive.rename(staged / "source.tar")
    return staged / "source.tar", value, package


def game(value: dict[str, Any], package: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    identity = "game-" + "a" * 64
    creation_metadata = {
        "operation_id": "op-" + "a" * 64,
        "actor_id": "123",
        "config_digest": "b" * 64,
        "package_digest": packages.digest(package),
        "reset_policy": None,
        "import": value,
    }
    record = {
        "game_id": identity,
        "world": {"generation": 1, "seed": -123},
        "creation": creation_metadata,
        "package": {"definition": package},
        "materialization_state": "UNMATERIALIZED",
    }
    return record, {
        "game_id": identity,
        "data_source": str(packages.GAMES / identity / "server"),
        "config_digest": "b" * 64,
    }


def test_exact_identity_and_prepare_without_regeneration(source: Any) -> None:
    archive, manifest, package = source
    assert imp.validate(manifest, package) == manifest
    record, target = game(manifest, package)
    other = packages.GAMES / "game-existing"
    other.mkdir()
    (other / "unchanged").write_bytes(b"existing")
    before = imp.tree(other)
    initial_game.prepare(
        record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
    )
    server = Path(target["data_source"])
    initial = imp.tree(server)
    owner = packages.GAMES / (record["game_id"] + ".initial-owner.json")
    mtime = owner.stat().st_mtime_ns
    assert json.loads(owner.read_text())["phase"] == "prepared"
    assert initial_game.initialized(target, atomic)
    assert json.loads(owner.read_text())["phase"] == "initialized"
    initial_game.prepare(
        record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
    )
    assert imp.tree(server) == initial and imp.tree(other) == before
    assert record["world"]["generation"] == 1
    assert (server / "whitelist.json").read_text() == "[]\n"
    assert "level-name=wishinkaiwai\n" in (server / "server.properties").read_text()
    assert not (server / "world").exists()
    assert imp.sha(archive) == manifest["archive_sha256"]
    assert owner.stat().st_mtime_ns >= mtime
    (server / imp.LEVEL / "level.dat").unlink()
    with pytest.raises(ValueError, match="WORLD_MISSING"):
        initial_game.prepare(
            record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("minecraft_version", "26.1"),
        ("minecraft_version", "26.2"),
        ("server_type", "vanilla"),
        ("paper_build", 54),
        ("paper_build", True),
        ("jar_sha256", "a" * 64),
        ("online_mode", False),
        ("data_version", 4791),
    ],
)
def test_runtime_mismatch_rejected(source: Any, key: str, value: Any) -> None:
    _, manifest, package = source
    manifest["source"][key] = value
    with pytest.raises(ValueError, match="RUNTIME_IDENTITY"):
        imp.validate(manifest, package)


@pytest.mark.parametrize("field", ["source_stopped", "save_confirmed", "filesystem_synced"])
def test_unfrozen_source_rejected(source: Any, field: str) -> None:
    _, manifest, package = source
    manifest[field] = False
    with pytest.raises(ValueError, match="SOURCE_NOT_FROZEN"):
        imp.validate(manifest, package)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("/absolute", tarfile.REGTYPE),
        ("../escape", tarfile.REGTYPE),
        ("wishinkaiwai/../escape", tarfile.REGTYPE),
        ("wishinkaiwai/link", tarfile.SYMTYPE),
        ("wishinkaiwai/hard", tarfile.LNKTYPE),
        ("wishinkaiwai/dev", tarfile.CHRTYPE),
        ("wishinkaiwai/fifo", tarfile.FIFOTYPE),
        ("ops.json", tarfile.REGTYPE),
        ("whitelist.json", tarfile.REGTYPE),
        ("banned-players.json", tarfile.REGTYPE),
        ("banned-ips.json", tarfile.REGTYPE),
        ("server.properties", tarfile.REGTYPE),
    ],
)
def test_unsafe_and_access_control_archive_rejected(
    source: Any, tmp_path: Path, name: str, kind: bytes
) -> None:
    _, value, _ = source
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as tar:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        entry.linkname = "../escape"
        tar.addfile(entry)
    value.update(archive_size=archive.stat().st_size, archive_sha256=imp.sha(archive))
    with pytest.raises(ValueError, match="ARCHIVE"):
        imp.extract(archive, tmp_path, value)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "names",
    [
        ("wishinkaiwai/a", "wishinkaiwai/a"),
        ("wishinkaiwai/A", "wishinkaiwai/a"),
        ("wishinkaiwai/X/a", "wishinkaiwai/x/b"),
        ("wishinkaiwai/a", "wishinkaiwai/a/b"),
    ],
)
def test_duplicate_case_and_parent_collisions(
    source: Any, tmp_path: Path, names: tuple[str, str]
) -> None:
    _, value, _ = source
    path = tmp_path / "collision.tar"
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name in names:
            entry = tarfile.TarInfo(name)
            entry.size = 1
            tar.addfile(entry, io.BytesIO(b"x"))
    value.update(archive_size=path.stat().st_size, archive_sha256=imp.sha(path))
    with pytest.raises(ValueError, match="DUPLICATE|COLLISION"):
        imp.extract(path, tmp_path, value)


@pytest.mark.parametrize("point", ["validation", "renamed"])
def test_retry_after_prepared_commit_interruption(source: Any, point: str) -> None:
    _, value, package = source
    record, target = game(value, package)

    def fail(path: Path, text: str) -> None:
        if (point == "validation" and path.name.endswith(".validated.json")) or (
            point == "renamed"
            and path.name.endswith(".initial-owner.json")
            and json.loads(text)["phase"] == "prepared"
        ):
            raise OSError("synthetic interrupted write")
        atomic(path, text)

    with pytest.raises(OSError, match="synthetic"):
        initial_game.prepare(
            record, {}, target, fail, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
        )
    initial_game.prepare(
        record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
    )
    assert (Path(target["data_source"]) / imp.LEVEL / "level.dat").is_file()
    assert record["world"]["generation"] == 1


def test_paper_pin_cannot_float_or_change_artifact(source: Any) -> None:
    _, _, package = source
    for field, value in [("build", "latest"), ("build", 54), ("commit", "latest")]:
        p = copy.deepcopy(package)
        p["loader"][field] = value
        with pytest.raises(ValueError):
            packages.validate(p)
    p = copy.deepcopy(package)
    p["loader"]["server"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        packages.validate(p)
    assert packages.environment(package)["PAPER_CUSTOM_JAR"].endswith("paper-26.1.2-53.jar")


@pytest.mark.parametrize("damage", ["count", "size", "hash", "tree", "disk"])
def test_archive_limits_and_integrity(
    source: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    archive, value, _ = source
    if damage == "count":
        value["file_count"] = 1
    elif damage == "size":
        value["expanded_size"] = 1
    elif damage == "hash":
        value["archive_sha256"] = "0" * 64
    elif damage == "tree":
        value["tree_sha256"] = "0" * 64
    else:
        import shutil

        monkeypatch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(ValueError):
        imp.extract(archive, tmp_path, value)


def test_lease_loss_before_commit_keeps_game_world_absent(source: Any) -> None:
    _, value, package = source
    record, target = game(value, package)
    calls = 0

    def verify() -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError("lease lost")

    with pytest.raises(ValueError, match="lease lost"):
        initial_game.prepare(
            record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=verify
        )
    assert not Path(target["data_source"]).exists()
    initial_game.prepare(
        record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
    )
    assert (Path(target["data_source"]) / imp.LEVEL / "level.dat").exists()


def test_existing_game_never_adopted(source: Any) -> None:
    _, value, package = source
    record, target = game(value, package)
    server = Path(target["data_source"])
    server.mkdir(parents=True)
    (server / "precious").write_text("existing world")
    before = imp.tree(server)
    with pytest.raises(ValueError, match="EXISTING_GAME"):
        initial_game.prepare(
            record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
        )
    assert imp.tree(server) == before


def test_pax_extension_is_rejected_before_expansion(source: Any, tmp_path: Path) -> None:
    _, value, _ = source
    path = tmp_path / "pax.tar"
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as tar:
        entry = tarfile.TarInfo("wishinkaiwai/a")
        entry.pax_headers = {"comment": "untrusted"}
        tar.addfile(entry)
    value.update(archive_size=path.stat().st_size, archive_sha256=imp.sha(path))
    with pytest.raises(ValueError, match="ARCHIVE_TYPE"):
        imp.extract(path, tmp_path, value)


def test_complete_paper_transition_retains_all_existing_packages() -> None:
    edge = json.loads(Path(packages.__file__).with_name("paper-transition.json").read_text())
    before, after = edge["predecessor"], edge["successor"]
    assert after["packages"][:-1] == before["packages"]
    assert packages.load() == after["packages"]
    for name in ["historical", "predecessor"]:
        for p in edge[name]["packages"]:
            assert packages.compatible_config(
                packages.digest(edge[name]), packages.digest(after), p
            )
        assert not packages.compatible_config(
            packages.digest(edge[name]), packages.digest(after), after["packages"][-1]
        )
    assert not packages.compatible_config(
        packages.digest(after), packages.digest(before), before["packages"][1]
    )
    assert not packages.compatible_config("0" * 64, packages.digest(after), before["packages"][1])


def test_import_create_provenance_is_immutable_and_actor_bound(
    source: Any,
    creation: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_game_creation import payload
    from tests.unit.test_web_operations import login, post
    from wishicraft.game_creation import REGISTRY_KEY
    from wishicraft.web_status import decode

    monkeypatch.setenv("GAME_PACKAGES", "1")
    _, manifest, package = source
    before = copy.deepcopy(creation[2].db.records)
    request = payload(package_id="vps-survival", seed="-123", **{"import": manifest})
    session = login(creation[1])
    assert post(creation, session, request)["statusCode"] == 202
    assert post(creation, session, request)["statusCode"] == 200
    assert creation[2].db.transactions == 1 and creation[3] == []
    identity = creation[2].db.records["games", REGISTRY_KEY]["registered_ids"]["SS"][0]
    document = {k: decode(v) for k, v in creation[2].db.records["games", identity].items()}
    assert document["creation"]["import"] == manifest
    assert document["package"]["definition"] == package
    assert document["world"]["generation"] == 1
    assert document["materialization_state"] == "UNMATERIALIZED"
    for key, value in before.items():
        assert creation[2].db.records[key] == value
    changed = copy.deepcopy(request)
    changed["creation"]["import"]["archive_sha256"] = "0" * 64
    assert post(creation, session, changed)["statusCode"] == 409
    assert creation[2].db.transactions == 1


def test_interrupted_extraction_retains_attempt_and_retries_new_root(
    source: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive, value, package = source
    record, target = game(value, package)
    original = tarfile.TarFile.extractfile
    calls = 0

    def interrupted(self: Any, entry: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic extraction failure")
        return original(self, entry)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", interrupted)
    with pytest.raises(OSError, match="extraction failure"):
        initial_game.prepare(
            record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
        )
    attempts = list(archive.parent.glob("extract-*"))
    assert len(attempts) == 1 and not Path(target["data_source"]).exists()
    failed = imp.tree(attempts[0])
    monkeypatch.setattr(tarfile.TarFile, "extractfile", original)
    initial_game.prepare(
        record, {}, target, atomic, uid=os.getuid(), gid=os.getgid(), verify=lambda: None
    )
    assert imp.tree(attempts[0]) == failed
    assert (Path(target["data_source"]) / imp.LEVEL / "level.dat").exists()
