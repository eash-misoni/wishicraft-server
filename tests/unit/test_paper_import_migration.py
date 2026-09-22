"""Exact complete manifest transition and stopped-host import support bundle."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_catalog_migration import inputs  # noqa: F401
from tests.unit.test_heartbeat_game_migration import attribute
from wishicraft import paper_import_migration
from wishicraft.artifacts import game_package as packages
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def paper_inputs(inputs: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    value = copy.deepcopy(inputs)
    edge = json.loads((ROOT / "src/wishicraft/artifacts/paper-transition.json").read_text())
    previous = packages.digest(edge["predecessor"])
    cfg = json.loads(value["host_config_bytes"])
    cfg["config_digest"] = previous
    value["host_config_bytes"] = json.dumps(cfg, sort_keys=True).encode()
    value["receipt"]["target"]["config_digest"] = previous
    return value


def test_exact_paper_bundle_keeps_durable_records(
    tmp_path: Path, paper_inputs: dict[str, Any]
) -> None:
    before = copy.deepcopy(paper_inputs)
    result = paper_import_migration.prepare(ROOT, tmp_path / "bundle", **paper_inputs)
    assert before == paper_inputs
    assert result["durable_record_updates"] == []
    entries = result["plan"]["files"]
    assert len(entries) == 9
    destinations = {v["destination"] for v in entries}
    assert "/usr/local/libexec/wishicraft/world_import.py" in destinations
    assert "/usr/local/libexec/wishicraft/world_nbt.py" in destinations
    assert not any(path.startswith("/srv/") for path in destinations)
    for entry in entries:
        assert (
            hashlib.sha256((tmp_path / "bundle" / entry["source"]).read_bytes()).hexdigest()
            == entry["sha256"]
        )


def test_renderer_exact_successor_and_legacy_environment() -> None:
    edge = json.loads((ROOT / "src/wishicraft/artifacts/paper-transition.json").read_text())
    cfg = load_configuration(ROOT, "dev")
    runtime = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(edge["predecessor"]["games"]),
        reset_policies=json.loads((ROOT / "config/reset-dev.json").read_text()),
        packages=packages.load(),
    )
    assert json.loads(runtime.manifest_json) == edge["successor"]
    assert edge["predecessor"]["runtime_env_sha256"] == edge["successor"]["runtime_env_sha256"]
    for key in edge["predecessor"]:
        if key not in {"compose_sha256", "packages"}:
            assert edge["predecessor"][key] == edge["successor"][key]


@pytest.mark.parametrize("damage", ["running", "config", "package", "unknown_record"])
def test_paper_release_refuses_unsafe_inventory(
    tmp_path: Path, paper_inputs: dict[str, Any], damage: str
) -> None:
    if damage == "running":
        paper_inputs["receipt"]["phase"] = "running"
    elif damage == "config":
        paper_inputs["host_config_bytes"] += b" "
    elif damage == "package":
        paper_inputs["inventory"]["Items"][2]["package"]["M"]["definition"]["M"][
            "minecraft_version"
        ] = {"S": "26.2"}
    else:
        paper_inputs["inventory"]["Items"].append({"game_id": attribute("unknown")})
    with pytest.raises(ValueError):
        paper_import_migration.prepare(ROOT, tmp_path / "rejected", **paper_inputs)
