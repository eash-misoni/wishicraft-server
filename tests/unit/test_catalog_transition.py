"""Immutable Game provenance across one complete, reviewed catalog append."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import initial_game, reset_worlds
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]


def transition() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(Path(packages.__file__).with_name("catalog-transition.json").read_text()),
    )


def test_catalog_preserves_both_existing_package_identities() -> None:
    old = json.loads(
        subprocess.check_output(
            ["git", "show", "866f6ca:src/wishicraft/artifacts/game-packages.json"], cwd=ROOT
        )
    )["packages"]
    current = packages.load()
    assert current[:-1] == old
    assert [packages.digest(p) for p in current[:-1]] == [packages.digest(p) for p in old]
    assert packages.digest(current[1]) == (
        "720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b"
    )
    for p in current:
        assert packages.select(current, p) == p
    assert current[-1]["package_id"] == "create-terralith"
    assert [(m["mod_id"], m["client_required"]) for m in current[-1]["mods"]] == [
        ("create", True),
        ("farmersdelight", True),
        ("terralith", False),
        ("tectonic", False),
        ("lithostitched", False),
    ]


def test_reviewed_transition_matches_complete_current_renderer() -> None:
    cfg = load_configuration(ROOT, "dev")
    current = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(json.loads((ROOT / "config/two-game-dev.json").read_text())),
        reset_policies=json.loads((ROOT / "config/reset-dev.json").read_text()),
        packages=packages.load(),
    )
    edge = transition()
    assert json.loads(current.manifest_json) == edge["successor"]
    assert packages.digest(edge["predecessor"]) == (
        "64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c"
    )
    assert current.digest != packages.digest(edge["predecessor"])


def test_old_game_registration_stays_byte_identical() -> None:
    edge = transition()
    before, after = map(packages.digest, (edge["predecessor"], edge["successor"]))
    p = packages.load()[1]
    game = {
        "game_id": "game-preserved",
        "runtime": {"class": "default"},
        "package": {**{k: p[k] for k in ("package_id", "package_version")}, "definition": p},
        "creation": {"config_digest": before, "package_digest": packages.digest(p)},
    }
    snapshot = packages.canonical(game)
    assert packages.registered(game, edge["successor"], after) == p
    assert packages.canonical(game) == snapshot
    assert not packages.compatible_config(after, before, p)
    assert not packages.compatible_config("a" * 64, after, p)
    assert not packages.compatible_config(before, "b" * 64, p)
    assert not packages.compatible_config(before, after, packages.load()[-1])
    changed = copy.deepcopy(p)
    changed["mods"][0]["sha256"] = "c" * 64
    assert not packages.compatible_config(before, after, changed)


def test_initialized_owner_and_world_are_not_rewritten_by_new_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_game_creation import atomic

    edge = transition()
    before, after = map(packages.digest, (edge["predecessor"], edge["successor"]))
    game_id = "game-" + "d" * 64
    p = packages.load()[1]
    game = {
        "game_id": game_id,
        "creation": {
            "operation_id": "op-" + "d" * 64,
            "config_digest": before,
            "package_digest": packages.digest(p),
        },
        "package": {"definition": p},
        "world": {"seed": 42},
        "materialization_state": "UNMATERIALIZED",
    }
    games = tmp_path / "games"
    games.mkdir(mode=0o755)
    monkeypatch.setattr(reset_worlds, "GAMES", games)
    monkeypatch.setattr(reset_worlds, "OWNER_UID", os.getuid())
    monkeypatch.setattr(reset_worlds, "OWNER_GID", os.getgid())
    target = {
        "game_id": game_id,
        "data_source": str(games / game_id / "server"),
        "config_digest": before,
        "run_id": "op-original",
    }
    config = {"initial_whitelist": []}
    initial_game.prepare(game, config, target, atomic, uid=os.getuid(), gid=os.getgid())
    world = Path(target["data_source"]) / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"existing fixture world")
    assert initial_game.initialized(target, atomic)
    owner = games / (game_id + ".initial-owner.json")
    original = (owner.read_bytes(), owner.stat().st_mtime_ns, world.stat().st_ino)
    snapshot = copy.deepcopy(game)
    initial_game.prepare(
        game,
        config,
        {**target, "config_digest": after, "run_id": "op-new"},
        atomic,
        uid=os.getuid(),
        gid=os.getgid(),
    )
    assert (owner.read_bytes(), owner.stat().st_mtime_ns, world.stat().st_ino) == original
    assert (world / "level.dat").read_bytes() == b"existing fixture world"
    assert game == snapshot


@pytest.mark.parametrize("field", ["image", "compose_sha256", "runtime_env_sha256", "games"])
def test_changed_non_catalog_manifest_is_never_compatible(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    edge = transition()
    package = packages.load()[1]
    edge["successor"][field] = "tampered"
    monkeypatch.setattr(Path, "read_text", lambda self: json.dumps(edge))
    with pytest.raises(ValueError, match="NOT_APPEND_ONLY"):
        packages.compatible_config("a" * 64, "b" * 64, package)


def test_old_and_mixed_provenance_backups_remain_valid() -> None:
    from wishicraft.backup_recovery import recovery_digest

    cfg = load_configuration(ROOT, "dev")
    edge = transition()
    runtime = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(edge["successor"]["games"]),
        reset_policies=json.loads((ROOT / "config/reset-dev.json").read_text()),
        packages=packages.load(),
    )
    old_digest = packages.digest(edge["predecessor"])
    new_digest = packages.digest(edge["successor"])
    for name in ("predecessor", "successor"):
        games = {}
        ids = [*edge[name]["games"], "game-" + "a" * 64]
        if name == "successor":
            ids.append("game-" + "b" * 64)
        for index, identity in enumerate(ids):
            p = packages.load()[max(0, index - 1)]
            game: dict[str, Any] = {
                "game_id": identity,
                "data_source": f"/srv/minecraft/games/{identity}/server",
                "runtime": {"class": "default"},
                "world": {"generation": 1, "seed": 42},
                "materialization_state": "MATERIALIZED",
                "package": {k: p[k] for k in ("package_id", "package_version")},
            }
            if index >= 2:
                game["package"]["definition"] = p
                game["creation"] = {
                    "operation_id": "op-" + identity[5:],
                    "config_digest": old_digest if index == 2 else new_digest,
                    "package_digest": packages.digest(p),
                }
            games[identity] = game
        document = {
            "schema_version": 2,
            "source_volume_id": "vol-0123456789abcdef0",
            "games": games,
            "runtime": {
                "manifest_json": packages.canonical(edge[name]),
                "runtime_env": runtime.runtime_env,
                "compose_yaml": runtime.compose_yaml,
                "creation_config": {"initial_whitelist": []},
            },
        }
        serialized = json.dumps(document, sort_keys=True)
        assert recovery_digest(serialized)
        assert json.dumps(document, sort_keys=True) == serialized
        games[ids[2]]["creation"]["config_digest"] = "0" * 64
        with pytest.raises(ValueError, match="PACKAGE_REGISTRATION_MISMATCH"):
            recovery_digest(json.dumps(document))
