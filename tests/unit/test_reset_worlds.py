"""Real temporary filesystem, synthetic world contents; no production paths or AWS."""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from wishicraft.artifacts import reset_worlds as worlds
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.reset_policy import seed
from wishicraft.world_reference import data_source, validate_source


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    games = tmp_path / "games"
    games.mkdir(mode=0o755)
    monkeypatch.setattr(worlds, "GAMES", games)
    monkeypatch.setattr(worlds, "OWNER_UID", os.getuid())
    monkeypatch.setattr(worlds, "OWNER_GID", os.getgid())
    game = games / "game-test"
    game.mkdir(mode=0o755)
    server = game / "server"
    server.mkdir()
    (server / "world/players/data").mkdir(parents=True)
    (server / "world/level.dat").write_bytes(b"synthetic original world")
    (server / "world/players/data/player.dat").write_bytes(b"old inventory")
    (server / "server.properties").write_text("level-name=world\nlevel-seed=42\nonline-mode=true\n")
    (server / "whitelist.json").write_text('[{"name":"synthetic"}]')
    return server


def plan(source: Path, number: int) -> dict[str, Any]:
    target = worlds.parent("game-test", f"op-reset-{number}") / "server"
    return {
        "schema_version": 1,
        "source": {
            "game_id": "game-test",
            "data_source": str(source),
            "run_id": f"op-source-{number}",
        },
        "target": {
            "game_id": "game-test",
            "data_source": str(target),
            "run_id": f"op-reset-{number}",
        },
        "seed": number,
        "policy": {"retain_previous": 2, "minimum_free_bytes": 1},
    }


def prepare(document: dict[str, Any]) -> Path:
    receipt = {
        "phase": "stopped",
        "target": document["source"],
        "stop": {"save_confirmed": True, "removal_ready": True},
    }
    worlds.prepare(document, receipt=receipt, atomic=atomic, uid=os.getuid(), gid=os.getgid())
    return Path(document["target"]["data_source"])


def ready(document: dict[str, Any]) -> dict[str, Any]:
    data = Path(document["target"]["data_source"])
    (data / "world").mkdir(exist_ok=True)
    (data / "world/level.dat").write_bytes(b"synthetic new world")
    worlds.initialized(document["target"], atomic, require=True)
    return {"phase": "running", "target": document["target"]}


def test_new_world_preserves_configuration_not_players_and_reuses_preparation(layout: Path) -> None:
    document = plan(layout, 1)
    new = prepare(document)
    assert not (new / "world").exists()
    assert (layout / "world/players/data/player.dat").read_bytes() == b"old inventory"
    assert (new / "whitelist.json").read_bytes() == (layout / "whitelist.json").read_bytes()
    assert "level-seed=1\n" in (new / "server.properties").read_text()
    ready(document)
    (new / "world/value").write_text("saved")
    assert prepare(document) == new
    assert (new / "world/value").read_text() == "saved"
    changed = deepcopy(document)
    changed["seed"] = 2
    with pytest.raises(ValueError, match="ALREADY_OWNED"):
        prepare(changed)


def test_initialized_missing_world_is_not_permission_to_generate(layout: Path) -> None:
    document = plan(layout, 1)
    new = prepare(document)
    ready(document)
    (new / "world/level.dat").unlink()
    with pytest.raises(ValueError, match="EXISTING_WORLD_MISSING"):
        worlds.initialized(document["target"], atomic, require=False)


def test_chain_cleanup_retains_anchor_latest_two_and_current(layout: Path) -> None:
    source = layout
    documents = []
    for n in range(1, 6):
        document = plan(source, n)
        source = prepare(document)
        receipt = ready(document)
        worlds.cleanup(document, receipt=receipt, atomic=atomic)
        documents.append(document)
    assert (layout / "world/players/data/player.dat").is_file()
    assert [Path(d["target"]["data_source"]).exists() for d in documents] == [
        False,
        False,
        True,
        True,
        True,
    ]
    assert worlds.cleanup(document, receipt=receipt, atomic=atomic) == []


def test_cleanup_response_loss_resumes_exact_directory(
    layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = layout
    for n in range(1, 5):
        document = plan(source, n)
        source = prepare(document)
        receipt = ready(document)
    real = shutil.rmtree

    def lost(path: Path) -> None:
        real(path)
        raise OSError("synthetic response lost after deletion")

    lost.avoids_symlink_attacks = True  # type: ignore[attr-defined]
    monkeypatch.setattr(shutil, "rmtree", lost)
    with pytest.raises(OSError):
        worlds.cleanup(document, receipt=receipt, atomic=atomic)
    monkeypatch.setattr(shutil, "rmtree", real)
    assert worlds.cleanup(document, receipt=receipt, atomic=atomic) == ["op-reset-1"]
    assert source.exists() and layout.exists()


def test_preparing_file_failure_resumes_without_new_world(layout: Path) -> None:
    document = plan(layout, 1)
    count = 0

    def interruption(path: Path, value: str) -> None:
        nonlocal count
        atomic(path, value)
        count += 1
        if count == 2:
            raise OSError("synthetic write reply loss")

    receipt = {
        "phase": "stopped",
        "target": document["source"],
        "stop": {"save_confirmed": True, "removal_ready": True},
    }
    with pytest.raises(OSError):
        worlds.prepare(
            document, receipt=receipt, atomic=interruption, uid=os.getuid(), gid=os.getgid()
        )
    new = prepare(document)
    assert len(list(new.parent.parent.glob("*/server"))) == 1
    assert not (new / "world").exists()


def test_unowned_or_redirected_data_is_rejected(layout: Path) -> None:
    document = plan(layout, 1)
    (layout / "redirect").symlink_to(layout.parent)
    with pytest.raises(ValueError, match="UNKNOWN_DATA"):
        prepare(document)
    (layout / "redirect").unlink()
    destination = worlds.parent("game-test", "op-reset-1")
    destination.mkdir(parents=True)
    with pytest.raises(ValueError, match="UNOWNED_DIRECTORY"):
        prepare(document)


def test_seed_and_world_are_fixed_by_identity() -> None:
    policy = {"fixed_seed": 0}
    assert seed("op-one", "fixed", policy) == seed("op-two", "fixed", policy) == 0
    assert seed("op-one", "new", policy) == seed("op-one", "new", policy)
    assert seed("op-one", "new", policy) != seed("op-two", "new", policy)
    path = data_source("game-a", "op-one")
    assert validate_source("game-a", path) == path
    for invalid in [
        path.replace("game-a", "game-b"),
        path.replace("op-one", ".."),
        "/srv/minecraft",
    ]:
        with pytest.raises(ValueError):
            validate_source("game-a", invalid)


def test_capacity_rejection_preserves_source_and_creates_no_world(
    layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="INSUFFICIENT_CAPACITY"):
        prepare(plan(layout, 1))
    assert (layout / "world/level.dat").is_file()
    assert not worlds.parent("game-test", "op-reset-1").exists()


@pytest.mark.parametrize("mutation", ["current", "other-game", "symlink", "mode", "protected"])
def test_cleanup_protects_current_other_unknown_and_explicit_protection(
    layout: Path, mutation: str
) -> None:
    source = layout
    documents = []
    for n in range(1, 5):
        document = plan(source, n)
        source = prepare(document)
        receipt = ready(document)
        documents.append(document)
    oldest = Path(documents[0]["target"]["data_source"])
    owner = worlds.owner_path(oldest.parent)
    value = json.loads(owner.read_text())
    if mutation == "current":
        value["plan"]["source"] = document["target"]
        atomic(owner, json.dumps(value))
    elif mutation == "other-game":
        value["plan"]["target"]["game_id"] = "game-other"
        atomic(owner, json.dumps(value))
    elif mutation == "symlink":
        (oldest / "outside").symlink_to(layout)
    elif mutation == "mode":
        owner.chmod(0o644)
    else:
        value["protected"] = True
        atomic(owner, json.dumps(value))
    if mutation == "protected":
        assert worlds.cleanup(document, receipt=receipt, atomic=atomic) == []
    else:
        with pytest.raises(ValueError):
            worlds.cleanup(document, receipt=receipt, atomic=atomic)
    assert oldest.exists() and source.exists() and layout.exists()


@pytest.mark.parametrize(
    "extra",
    [
        "level-name:other",
        "level-name=other",
        "level-name=world\\\ncontinued=other",
        " level-name=other",
    ],
)
def test_ambiguous_java_properties_rejected(layout: Path, extra: str) -> None:
    path = layout / "server.properties"
    path.write_text(path.read_text() + extra + "\n")
    with pytest.raises(ValueError, match="CUSTOM_PROPERTIES"):
        prepare(plan(layout, 1))
    assert (layout / "world/level.dat").exists()


def test_start_return_before_world_generation_is_not_ready(layout: Path) -> None:
    document = plan(layout, 1)
    new = prepare(document)
    worlds.initialized(document["target"], atomic, require=False)
    assert worlds.record(worlds.owner_path(new.parent))["phase"] == "prepared"
    ready(document)
    (new / "world/level.dat").unlink()
    with pytest.raises(ValueError, match="EXISTING_WORLD_MISSING"):
        worlds.initialized(document["target"], atomic, require=False)
