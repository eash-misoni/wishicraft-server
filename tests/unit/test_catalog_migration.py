"""Exact offline cutover guards; inventory and immutable provenance are never rewritten."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_heartbeat_game_migration import attribute, game_document, stopped_receipt
from tests.unit.test_runtime_memory import inventory, receipt
from wishicraft import catalog_migration, game_package_migration
from wishicraft.game_creation import REGISTRY_KEY

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def inputs(tmp_path: Path, historical_catalog_root: Path) -> dict[str, Any]:
    previous = tmp_path / "previous"
    game_package_migration.prepare(historical_catalog_root, previous, receipt(), inventory())
    edge = json.loads((ROOT / "src/wishicraft/artifacts/catalog-transition.json").read_text())
    legacy = game_document(legacy=True)["Item"]
    assert isinstance(legacy, dict)
    items = []
    for identity in edge["predecessor"]["games"]:
        item = copy.deepcopy(legacy)
        item["game_id"] = {"S": identity}
        items.append(item)
    dynamic = game_document()["Item"]
    assert isinstance(dynamic, dict)
    items.append(dynamic)
    items.append({"game_id": {"S": REGISTRY_KEY}, "registered_ids": {"SS": ["game-" + "a" * 64]}})
    items.append(
        {
            "game_id": {"S": "policy-whitelist-common-v1"},
            "policy_json": {"S": json.dumps({"revision": 0, "members": {}})},
        }
    )
    return {
        "receipt": stopped_receipt(),
        "inventory": {"Items": items},
        "host_config_bytes": (previous / "3.artifact").read_bytes(),
    }


def test_exact_append_preserves_records_and_configuration(
    tmp_path: Path, inputs: dict[str, Any]
) -> None:
    snapshot = copy.deepcopy(inputs)
    output = tmp_path / "cutover"
    review = catalog_migration.prepare(ROOT, output, **inputs)
    assert inputs == snapshot
    assert review["durable_record_updates"] == []
    assert len(review["plan"]["files"]) == 6
    old = json.loads(inputs["host_config_bytes"])
    new = json.loads((output / "5.artifact").read_bytes())
    assert new.pop("config_digest") == review["new_digest"]
    assert old.pop("config_digest") == review["old_digest"]
    assert new == old
    for item in review["plan"]["files"]:
        assert hashlib.sha256((output / item["source"]).read_bytes()).hexdigest() == item["sha256"]
    assert review["plan"]["receipt_predecessor"] == inputs["receipt"]


@pytest.mark.parametrize(
    "damage",
    [
        "config",
        "running",
        "save",
        "removal",
        "digest",
        "path",
        "pagination",
        "unknown",
        "unmaterialized",
        "package",
    ],
)
def test_cutover_fails_closed_before_output(
    tmp_path: Path, inputs: dict[str, Any], damage: str
) -> None:
    if damage == "config":
        inputs["host_config_bytes"] += b"\n"
    elif damage == "running":
        inputs["receipt"]["phase"] = "running"
    elif damage in {"save", "removal"}:
        inputs["receipt"]["stop"]["save_confirmed" if damage == "save" else "removal_ready"] = False
    elif damage in {"digest", "path"}:
        inputs["receipt"]["target"]["config_digest" if damage == "digest" else "data_source"] = (
            "wrong"
        )
    elif damage == "pagination":
        inputs["inventory"]["LastEvaluatedKey"] = {"game_id": {"S": "more"}}
    elif damage == "unknown":
        inputs["inventory"]["Items"].append({"game_id": {"S": "unknown"}})
    elif damage == "unmaterialized":
        inputs["inventory"]["Items"][2]["materialization_state"] = {"S": "UNMATERIALIZED"}
    else:
        inputs["inventory"]["Items"][2]["creation"]["M"]["package_digest"] = attribute("0" * 64)
    output = tmp_path / "rejected"
    with pytest.raises(ValueError):
        catalog_migration.prepare(ROOT, output, **inputs)
    assert not output.exists()
