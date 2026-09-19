from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from wishicraft.artifacts import game_package
from wishicraft.heartbeat_game_migration import (
    DESTINATION,
    PREDECESSOR,
    RUNTIME_DIGEST,
    prepare,
)

ROOT = Path(__file__).resolve().parents[2]


def stopped_receipt(game_id: str = "game-" + "a" * 64) -> dict[str, object]:
    return {
        "phase": "stopped",
        "target": {
            "instance_id": "i-04fc0629dc4ea466e",
            "game_id": game_id,
            "run_id": "op-finished",
            "data_source": "/srv/minecraft/games/" + game_id + "/server",
            "config_digest": RUNTIME_DIGEST,
        },
        "stop": {"save_confirmed": True, "removal_ready": True},
    }


def attribute(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if type(value) is int:
        return {"N": str(value)}
    if isinstance(value, list):
        return {"L": [attribute(item) for item in value]}
    if isinstance(value, dict):
        return {"M": {key: attribute(item) for key, item in value.items()}}
    raise TypeError(type(value))


def game_document(*, legacy: bool = False) -> dict[str, object]:
    package = game_package.load()[0 if legacy else 1]
    game_id = "game-vanilla-main" if legacy else "game-" + "a" * 64
    game: dict[str, object] = {
        "game_id": game_id,
        "schema_version": 1,
        "lifecycle_state": "ACTIVE",
        "materialization_state": "MATERIALIZED",
        "runtime": {"class": "default"},
        "package": {
            "package_id": package["package_id"],
            "package_version": package["package_version"],
        },
        "world": {"generation": 1, "current_id": None},
    }
    if not legacy:
        game["package"] = {**game["package"], "definition": package}  # type: ignore[dict-item]
        game["creation"] = {
            "config_digest": RUNTIME_DIGEST,
            "package_digest": game_package.digest(package),
        }
    return {"Item": {key: attribute(value) for key, value in game.items()}}


def test_only_exact_producer_is_replaced_using_inactive_installer(tmp_path: Path) -> None:
    plan = prepare(ROOT, tmp_path / "bundle", stopped_receipt(), game_document())
    assert plan["backup_namespace"] == "heartbeat-game-v2"
    assert plan["receipt_predecessor"] == stopped_receipt()
    assert len(plan["files"]) == 1
    entry = plan["files"][0]
    assert entry["destination"] == DESTINATION
    assert entry["predecessor"] == PREDECESSOR
    assert (
        entry["sha256"]
        == hashlib.sha256(
            (ROOT / "src/wishicraft/runtime_heartbeat_producer.py").read_bytes()
        ).hexdigest()
    )
    assert entry["sha256"] != PREDECESSOR
    assert json.loads((tmp_path / "bundle/install.json").read_text()) == plan
    installer = (tmp_path / "bundle/install.py").read_text()
    assert "verify_stopped_predecessor(manifest)" in installer
    assert "require_no_container()" in installer
    assert 'namespace != "heartbeat-game-v2"' in installer
    assert "/var/tmp/wishicraft-heartbeat-game-v2" in installer
    assert "game_creation" not in json.dumps(plan)
    package = game_package.load()[1]
    target = stopped_receipt()["target"]
    assert isinstance(target, dict)
    assert plan["package_environment"] == game_package.projection(
        target["game_id"],
        package,
    )
    assert plan["package_context"]["package"] == package
    assert plan["package_context"]["package_digest"] == game_package.digest(package)
    assert {a["sha256"] for a in plan["package_context"]["artifacts"]} == {
        a["sha256"] for a in [*package["mods"], package["loader"]["installer"]]
    }


@pytest.mark.parametrize("field", ["phase", "save_confirmed", "removal_ready", "digest"])
def test_migration_rejects_incomplete_stop_or_wrong_runtime(tmp_path: Path, field: str) -> None:
    receipt = stopped_receipt()
    if field == "phase":
        receipt["phase"] = "running"
    elif field == "digest":
        receipt["target"]["config_digest"] = "0" * 64  # type: ignore[index]
    else:
        receipt["stop"][field] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="exact completed stopped receipt"):
        prepare(ROOT, tmp_path / "bundle", receipt, game_document())
    assert not (tmp_path / "bundle").exists()


def test_vanilla_game_uses_same_authority_and_projection(tmp_path: Path) -> None:
    receipt = stopped_receipt("game-vanilla-main")
    plan = prepare(ROOT, tmp_path / "bundle", receipt, game_document(legacy=True))
    assert plan["package_environment"]["WISHICRAFT_PACKAGE_TYPE"] == "VANILLA"
    assert plan["package_environment"]["WISHICRAFT_PACKAGE_VERSION"] == "26.2"
    assert plan["package_context"]["artifacts"] == []


@pytest.mark.parametrize("damage", ["digest", "directory", "game", "state"])
def test_game_authority_or_path_mismatch_is_rejected(tmp_path: Path, damage: str) -> None:
    receipt = stopped_receipt()
    document = game_document()
    item = cast(dict[str, Any], document["Item"])
    if damage == "digest":
        item["creation"]["M"]["package_digest"] = {"S": "0" * 64}
    elif damage == "directory":
        target = cast(dict[str, Any], receipt["target"])
        target["data_source"] = str(target["data_source"]) + "-other"
    elif damage == "game":
        item["game_id"] = {"S": "game-" + "b" * 64}
    else:
        item["materialization_state"] = {"S": "UNMATERIALIZED"}
    with pytest.raises(ValueError):
        prepare(ROOT, tmp_path / "bundle", receipt, document)
    assert not (tmp_path / "bundle").exists()
