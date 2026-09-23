from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_provenance import record
from tests.unit.test_isolated_restore import source_evidence
from tests.unit.test_reset_recovery import recovery
from tests.unit.test_world_import import nbt
from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import reset_worlds, restore_tree, world_import
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.backup_recovery import shared_tags
from wishicraft.restore_source import make_plan, verified_snapshot

NOW = datetime(2026, 9, 23, tzinfo=UTC)


def evidence() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    description = json.loads(recovery())
    for game in description["games"].values():
        game.update(
            lifecycle_state="ACTIVE",
            materialization_state="MATERIALIZED",
            package={"package_id": "vanilla", "package_version": "initial-fixed-version"},
        )
        game["world"]["generation"] = 1
    text = json.dumps(description)
    old = record()
    p = replace(old, schema_version=2, recovery_json=text, metadata=shared_tags(old.metadata, text))
    raw = source_evidence(p)["snapshots"][0]
    return raw, p.snapshot_item(), p.operation_item(), description


def verify(raw: dict[str, Any], p: dict[str, Any], reverse: dict[str, Any]) -> dict[str, Any]:
    return verified_snapshot(
        raw,
        p,
        reverse,
        project="wishicraft",
        stage="dev",
        account=record().verified_owner_id,
        volume=record().source_volume_id,
    )


def test_provenance_pair_without_expiring_operation() -> None:
    raw, p, reverse, description = evidence()
    assert verify(raw, p, reverse) == description
    for field in ("snapshot_id", "operation_id"):
        broken = {**reverse, field: "unknown"}
        with pytest.raises(ValueError):
            verify(raw, p, broken)


@pytest.mark.parametrize(
    "field,value",
    [
        ("OwnerId", "wrong"),
        ("State", "pending"),
        ("Encrypted", False),
        ("VolumeId", "vol-other"),
        ("SnapshotId", "snap-unknown"),
    ],
)
def test_snapshot_mismatch(field: str, value: Any) -> None:
    raw, p, reverse, _ = evidence()
    with pytest.raises(ValueError):
        verify({**raw, field: value}, p, reverse)


def test_same_game_package_and_new_generation() -> None:
    _, p, _, recovery_doc = evidence()
    game = copy.deepcopy(recovery_doc["games"]["game-vanilla-secondary"])
    game["world"]["generation"] = 3
    manifest = json.loads(recovery_doc["runtime"]["manifest_json"])
    kwargs = dict(
        game=game,
        current_manifest=manifest,
        recovery=recovery_doc,
        provenance=p,
        request_id="restore-test-001",
        system_id="wishicraft-main",
        now=NOW,
    )
    plan = make_plan(**kwargs)
    assert plan["target_generation"] == 4 and plan["source_generation"] == 1
    assert plan["target_data_source"] != game["data_source"]
    assert make_plan(**kwargs) == plan
    game["game_id"] = "game-other"
    with pytest.raises(ValueError, match="GAME_IDENTITY"):
        make_plan(**kwargs)
    game["game_id"] = "game-vanilla-secondary"
    manifest["minecraft_version"] = "1.21.1"
    with pytest.raises(ValueError, match="PACKAGE_MISMATCH"):
        make_plan(**kwargs)


@pytest.fixture(params=[0, 1, -1], ids=["vanilla", "neoforge", "paper"])
def trees(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], Path, Path]:
    games = tmp_path / "current/games"
    games.mkdir(parents=True)
    for module in (reset_worlds, packages):
        monkeypatch.setattr(module, "GAMES", games)
        monkeypatch.setattr(module, "OWNER_UID", os.getuid())
        monkeypatch.setattr(module, "OWNER_GID", os.getgid())
    package = packages.load()[request.param]
    mount = tmp_path / "snapshot"
    current = games / "game-test/server"
    source = mount / "games/game-test/server"
    level = package["loader"].get("level_name", "world")
    for directory, content in [(current, b"current"), (source, b"past")]:
        (directory / level / "region").mkdir(parents=True)
        (directory / level / "level.dat").write_bytes(
            nbt({"Data": {"Version": {"Name": package["minecraft_version"]}}})
        )
        (directory / level / "region/r.0.0.mca").write_bytes(content)
        (directory / "server.properties").write_text(
            "level-name=" + level + "\nlevel-seed=12\nonline-mode=true\n"
        )
        if package["loader"]["type"] == "paper":
            for name in world_import.CONFIGS:
                config = directory / name
                config.parent.mkdir(exist_ok=True)
                config.write_text("_version: 31\n")
        for name in ("whitelist.json", "ops.json", "banned-ips.json", "banned-players.json"):
            (directory / name).write_bytes(content)
    plan = {
        "game_id": "game-test",
        "operation_id": "op-test",
        "package": package,
        "package_digest": packages.digest(package),
        "source_world": {"generation": 1},
        "source_data_source": str(current),
        "previous_data_source": str(current),
        "target_data_source": str(games / "game-test/worlds/op-test/server"),
    }
    return plan, mount, current


def prepare(plan: dict[str, Any], mount: Path, **kw: Any) -> dict[str, Any]:
    return restore_tree.prepare(
        plan, mount, atomic=atomic, verify=lambda: None, uid=os.getuid(), gid=os.getgid(), **kw
    )


def test_copy_retry_and_start_failure_preserve_previous(
    trees: tuple[dict[str, Any], Path, Path],
) -> None:
    plan, mount, current = trees
    before = world_import.tree(current)
    source_before = world_import.tree(mount)
    result = prepare(plan, mount)
    assert prepare(plan, mount) == result
    assert world_import.tree(current) == before
    assert world_import.tree(mount) == source_before
    server = Path(plan["target_data_source"])
    assert (server / "ops.json").read_bytes() == b"current"
    assert (server / restore_tree.level_name(plan) / "region/r.0.0.mca").read_bytes() == b"past"
    reset_worlds.initialized(
        {"game_id": plan["game_id"], "data_source": str(server)}, atomic, require=True
    )
    assert world_import.tree(current) == before  # START failure never deletes the previous tree.
    assert world_import.expected_level(
        {"game_id": plan["game_id"], "data_source": str(server)}
    ) == restore_tree.level_name(plan)


def test_partial_copy_retry_uses_new_root(
    trees: tuple[dict[str, Any], Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, mount, _ = trees
    original = shutil.copytree
    with monkeypatch.context() as scoped:

        def broken(source: Path, target: Path, **kwargs: Any) -> None:
            target.mkdir()
            (target / "partial").write_text("interrupted")
            raise OSError("interrupted")

        scoped.setattr(shutil, "copytree", broken)
        with pytest.raises(OSError):
            prepare(plan, mount)
    assert shutil.copytree is original
    assert prepare(plan, mount)["phase"] == "prepared"
    assert not list(Path(plan["target_data_source"]).rglob("partial"))


def test_unsafe_source_refused(trees: tuple[dict[str, Any], Path, Path]) -> None:
    plan, mount, current = trees
    (mount / "games/game-test/server/redirect").symlink_to(current)
    with pytest.raises(ValueError, match="UNKNOWN_DATA"):
        prepare(plan, mount)
    assert not Path(plan["target_data_source"]).exists()


def test_rename_committed_before_owner_response_loss(
    trees: tuple[dict[str, Any], Path, Path],
) -> None:
    plan, mount, current = trees
    before = world_import.tree(current)

    def fail_prepared(path: Path, value: str) -> None:
        if path.name.endswith(".owner.json") and json.loads(value).get("phase") == "prepared":
            raise OSError("owner receipt interrupted")
        atomic(path, value)

    with pytest.raises(OSError):
        restore_tree.prepare(
            plan, mount, atomic=fail_prepared, verify=lambda: None, uid=os.getuid(), gid=os.getgid()
        )
    server = Path(plan["target_data_source"])
    saved = world_import.tree(server)
    assert prepare(plan, mount)["phase"] == "prepared"
    assert world_import.tree(server) == saved
    assert world_import.tree(current) == before
    assert not list(server.parent.glob("staging-*"))


def test_revocation_during_copy_preserves_both_sources_and_resumes(
    trees: tuple[dict[str, Any], Path, Path],
) -> None:
    plan, mount, current = trees
    original = world_import.tree(current)
    snapshot = world_import.tree(mount)
    target = Path(plan["target_data_source"])

    def revoked() -> None:
        if list(target.parent.glob("staging-*/**/r.0.0.mca")):
            raise ValueError("RESTORE_HOST_MAINTENANCE")

    with pytest.raises(ValueError, match="MAINTENANCE"):
        restore_tree.prepare(
            plan, mount, atomic=atomic, verify=revoked, uid=os.getuid(), gid=os.getgid()
        )
    assert not target.exists()
    assert world_import.tree(current) == original
    assert world_import.tree(mount) == snapshot
    assert prepare(plan, mount)["phase"] == "prepared"
    assert not list(target.parent.glob("staging-*"))


def test_managed_previous_and_restored_world_are_retention_protected(
    trees: tuple[dict[str, Any], Path, Path],
) -> None:
    plan, mount, legacy = trees
    previous = reset_worlds.parent("game-test", "op-previous") / "server"
    previous.parent.mkdir(parents=True)
    shutil.copytree(legacy, previous)
    atomic(
        reset_worlds.owner_path(previous.parent),
        json.dumps(
            {
                "phase": "initialized",
                "plan": {
                    "source": {"game_id": "game-test", "data_source": str(legacy)},
                    "target": {"game_id": "game-test", "data_source": str(previous)},
                },
            }
        ),
    )
    plan["previous_data_source"] = str(previous)
    saved = world_import.tree(previous)
    owner = prepare(plan, mount)
    assert owner["protected"] is True
    assert reset_worlds.record(reset_worlds.owner_path(previous.parent))["protected"] is True
    restored = Path(plan["target_data_source"])
    reset_worlds.initialized(
        {"game_id": "game-test", "data_source": str(restored)}, atomic, require=True
    )
    if restore_tree.level_name(plan) == "world":
        from tests.unit.test_reset_worlds import plan as reset_plan
        from tests.unit.test_reset_worlds import prepare as reset_prepare
        from tests.unit.test_reset_worlds import ready

        current = restored
        for number in range(1, 5):
            document = reset_plan(current, number)
            current = reset_prepare(document)
            reset_worlds.cleanup(document, receipt=ready(document), atomic=atomic)
    # Paper RESET remains disabled; its RESTORE owners use the same protection records.
    assert world_import.tree(previous) == saved
    assert restored.exists() and legacy.exists()
