"""Immutable Game provenance across one complete, reviewed catalog append."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from wishicraft.artifacts import game_package as packages
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
