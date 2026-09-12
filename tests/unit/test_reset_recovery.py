from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.test_backup_provenance import Dynamo, record
from tests.unit.test_isolated_restore import source_evidence
from wishicraft.backup_provenance import BackupProvenanceRepository
from wishicraft.backup_recovery import recovery_digest, shared_tags
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.isolated_restore import verify_source
from wishicraft.reset_workflow import find_command
from wishicraft.runtime_contract import command
from wishicraft.world_reference import data_source

ROOT = Path(__file__).resolve().parents[2]
GAMES = ["game-vanilla-main", "game-vanilla-secondary"]


def recovery() -> str:
    cfg = load_configuration(ROOT, "dev")
    runtime = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=tuple(GAMES),
        reset_policies={},
    )
    return json.dumps(
        {
            "schema_version": 1,
            "source_volume_id": record().source_volume_id,
            "games": {
                g: {
                    "game_id": g,
                    "world": {"current_id": "op-world"},
                    "data_source": data_source(g, "op-world"),
                }
                for g in GAMES
            },
            "runtime": {
                "manifest_json": runtime.manifest_json,
                "compose_yaml": runtime.compose_yaml,
                "runtime_env": runtime.runtime_env,
            },
        },
        sort_keys=True,
    )


def test_v2_current_world_recovery_uses_existing_provenance_pair() -> None:
    value = recovery()
    old = record(verified_owner_id="385526546525")
    shared = replace(
        old, schema_version=2, recovery_json=value, metadata=shared_tags(old.metadata, value)
    )
    db = Dynamo()
    BackupProvenanceRepository(db, table_name="backups").register(shared)
    evidence = source_evidence()
    evidence["provenance"] = list(db.items.values())
    evidence["snapshots"][0]["Tags"] = [{"Key": k, "Value": v} for k, v in shared.metadata.items()]
    evidence["operations"][0]["backup_recovery_json"] = {"S": value}
    evidence["operations"][0]["result"]["M"].update(
        scope={"S": "shared-volume"}, recovery_digest={"S": recovery_digest(value)}
    )
    source = verify_source(evidence, old.snapshot_id, ROOT)
    assert source["recovery_description"]["games"][GAMES[1]]["world"]["current_id"] == "op-world"
    assert not source["restore_test_completed"]
    evidence["operations"][0]["backup_recovery_json"] = {"S": value.replace("op-world", "op-wrong")}
    with pytest.raises(ValueError):
        verify_source(evidence, old.snapshot_id, ROOT)


def test_recovery_reference_mismatch_rejected_without_rewriting_old_format() -> None:
    value = json.loads(recovery())
    value["games"][GAMES[1]]["world"]["current_id"] = None
    with pytest.raises(ValueError):
        recovery_digest(json.dumps(value))
    value["games"][GAMES[1]]["world"] = {}
    with pytest.raises(ValueError):
        recovery_digest(json.dumps(value))


def test_ssm_lost_reply_uses_exact_command_not_search_absence() -> None:
    proof = SimpleNamespace(owner_operation_id="op-reset", lease_id="lease-reset")
    plan = {"target": {"instance_id": "i-0123456789abcdef0"}}
    item = {
        "CommandId": "00000000-0000-4000-8000-000000000001",
        "Comment": "Wishicraft reset_prepare op-reset",
        "InstanceIds": [plan["target"]["instance_id"]],
        "DocumentName": "AWS-RunShellScript",
        "Targets": [],
        "Parameters": {
            "commands": [
                command(operation_id="op-reset", lease_id="lease-reset", action="RESET_PREPARE")
            ],
            "executionTimeout": ["360"],
        },
    }

    class Api:
        items: list[dict[str, Any]] = [item]

        def list_commands(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["InstanceId"] == plan["target"]["instance_id"]
            return {"Commands": self.items}

    api = Api()
    assert find_command(api, proof, plan, "reset_prepare") == item["CommandId"]
    for results in [[], [item, item]]:
        api.items = results
        with pytest.raises(RuntimeError, match="OUTCOME_UNKNOWN"):
            find_command(api, proof, plan, "reset_prepare")
    api.items = [{**item, "Parameters": {"commands": ["another payload"]}}]
    with pytest.raises(ValueError):
        find_command(api, proof, plan, "reset_prepare")
