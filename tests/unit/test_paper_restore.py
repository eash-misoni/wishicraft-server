"""IMPORT-origin Paper restoration, retaining the original initial directory."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

from tests.unit.test_restore_repository import NOW, setup
from tests.unit.test_world_import import game
from tests.unit.test_world_import import source as paper_source  # noqa: F401
from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import initial_game, reset_worlds, restore_tree, world_import
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.restore_source import make_plan


def test_import_origin_prepare_selection_and_initial_path_rollback(paper_source: Any) -> None:  # noqa: F811
    archive, manifest, package = paper_source
    record, initial_target = game(manifest, package)
    record.update(lifecycle_state="ACTIVE", runtime={"class": "default"})
    record["package"].update({k: package[k] for k in ("package_id", "package_version")})
    runtime = {"packages": packages.load(), "games": []}
    config_digest = packages.digest(runtime)
    record["creation"]["config_digest"] = config_digest
    initial_target["config_digest"] = config_digest
    initial_game.prepare(
        record,
        {},
        initial_target,
        atomic,
        uid=os.getuid(),
        gid=os.getgid(),
        verify=lambda: None,
    )
    initial_game.initialized(initial_target, atomic)
    record["materialization_state"] = "MATERIALIZED"
    current = Path(initial_target["data_source"])
    for group in ("stats", "advancements"):
        root = current / "wishinkaiwai/players" / group
        root.mkdir(parents=True)
        (root / "fixture.json").write_text('{"retained":true}')
    for dimension in ("overworld", "the_nether", "the_end"):
        (current / "wishinkaiwai/dimensions/minecraft" / dimension / "paper-world.yml").write_text(
            "_version: 31\n"
        )
    snapshot = packages.GAMES.parent / "snapshot"
    shutil.copytree(packages.GAMES, snapshot / "games")
    for name in ("whitelist.json", "ops.json", "banned-ips.json", "banned-players.json"):
        (current / name).write_text('[{"current-policy":"fixture"}]')
    archive.unlink()  # RESTORE and later ordinary initial-path replay must not extract it.
    canonical = "/srv/minecraft/games/" + record["game_id"] + "/server"
    recovered = {**copy.deepcopy(record), "data_source": canonical}
    plan = make_plan(
        game=record,
        current_manifest=runtime,
        recovery={
            "games": {record["game_id"]: recovered},
            "runtime": {"manifest_json": json.dumps(runtime)},
        },
        provenance={
            "project": "wishicraft",
            "stage": "dev",
            "snapshot_id": "snap-fixture",
            "operation_id": "op-backup",
            "source_volume_id": "vol-fixture",
            "snapshot_start_time": NOW.isoformat(),
        },
        request_id="paper-restore-fixture",
        system_id="system",
        now=NOW,
    )
    assert plan["previous_world"] == record["world"]
    assert "current_id" not in plan["previous_world"]
    assert plan["target_generation"] == 2
    # The actual source selection is canonical; only the filesystem fixture root is relocated.
    for key in ("source_data_source", "previous_data_source", "target_data_source"):
        plan[key] = plan[key].replace("/srv/minecraft/games", str(packages.GAMES), 1)
    previous = world_import.tree(current)
    mismatched = {**plan, "source_creation": {**plan["source_creation"], "actor_id": "other"}}
    with pytest.raises(ValueError, match="RESTORE_SOURCE_OWNER"):
        restore_tree.prepare(
            mismatched,
            snapshot,
            atomic=atomic,
            verify=lambda: None,
            uid=os.getuid(),
            gid=os.getgid(),
        )
    assert not Path(plan["target_data_source"]).exists()
    prepared = restore_tree.prepare(
        plan,
        snapshot,
        atomic=atomic,
        verify=lambda: None,
        uid=os.getuid(),
        gid=os.getgid(),
    )
    target = {**initial_target, "data_source": plan["target_data_source"]}
    restored = Path(target["data_source"])
    assert prepared["source_world_tree"] == world_import.tree(restored / "wishinkaiwai")
    assert world_import.tree(current) == previous
    assert world_import.expected_level(target) == "wishinkaiwai"
    assert not (restored / "world").exists()
    for name in ("whitelist.json", "ops.json", "banned-ips.json", "banned-players.json"):
        assert (restored / name).read_bytes() == (current / name).read_bytes()
    for name in world_import.CONFIGS:
        assert (restored / name).read_bytes() == (current / name).read_bytes()
    reset_worlds.initialized(target, atomic, require=True)
    db, repo, lease, _ = setup()
    journal = repo.create(
        plan,
        lease=lease,
        now=NOW,
        protection={"snapshot_id": "snap-protection", "desired_revision": 7},
        current_package=record["package"],
    )
    journal = repo.advance(journal, lease=lease, now=NOW, phase="PREPARED")
    committed = repo.select(journal, lease=lease, now=NOW)
    restored_world = TypeDeserializer().deserialize(
        db.calls[-1][-1]["Update"]["ExpressionAttributeValues"][":new"]
    )
    assert restored_world["current_id"] == plan["operation_id"]
    assert restored_world["generation_counter"] == 2
    repo.select(committed, lease=lease, now=NOW, rollback=True)
    rolled_world = TypeDeserializer().deserialize(
        db.calls[-1][-1]["Update"]["ExpressionAttributeValues"][":new"]
    )
    assert rolled_world == {**record["world"], "generation_counter": 2}
    assert "current_id" not in rolled_world
    record["world"] = json.loads(json.dumps(rolled_world, default=int))
    initial_game.prepare(
        record,
        {},
        initial_target,
        atomic,
        uid=os.getuid(),
        gid=os.getgid(),
        verify=lambda: None,
    )
    assert world_import.tree(current) == previous
    assert restored.is_dir()
