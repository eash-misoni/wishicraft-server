from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from wishicraft.heartbeat_game_migration import (
    DESTINATION,
    PREDECESSOR,
    RUNTIME_DIGEST,
    prepare,
)

ROOT = Path(__file__).resolve().parents[2]


def stopped_receipt() -> dict[str, object]:
    return {
        "phase": "stopped",
        "target": {
            "instance_id": "i-04fc0629dc4ea466e",
            "game_id": "game-" + "a" * 64,
            "run_id": "op-finished",
            "data_source": "/srv/minecraft/games/game-" + "a" * 64 + "/server",
            "config_digest": RUNTIME_DIGEST,
        },
        "stop": {"save_confirmed": True, "removal_ready": True},
    }


def test_only_exact_producer_is_replaced_using_inactive_installer(tmp_path: Path) -> None:
    plan = prepare(ROOT, tmp_path / "bundle", stopped_receipt())
    assert plan["backup_namespace"] == "heartbeat-game-v1"
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
    assert 'namespace != "heartbeat-game-v1"' in installer
    assert "/var/tmp/wishicraft-heartbeat-game-v1" in installer
    assert "game_creation" not in json.dumps(plan)


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
        prepare(ROOT, tmp_path / "bundle", receipt)
    assert not (tmp_path / "bundle").exists()
