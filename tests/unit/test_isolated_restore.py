from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_provenance import Dynamo, record
from wishicraft.backup_provenance import BackupProvenanceRepository
from wishicraft.isolated_restore import isolated_template, verify_source
from wishicraft.operation import _attribute_map

ROOT = Path(__file__).resolve().parents[2]


def source_evidence() -> dict[str, Any]:
    p = record(verified_owner_id="385526546525")
    db = Dynamo()
    BackupProvenanceRepository(db, table_name="backups").register(p)
    return {
        "snapshots": [
            {
                "SnapshotId": p.snapshot_id,
                "VolumeId": p.source_volume_id,
                "OwnerId": p.verified_owner_id,
                "State": "completed",
                "Encrypted": True,
                "VolumeSize": 30,
                "StartTime": p.snapshot_start_time.isoformat(),
                "StorageTier": "standard",
                "Description": "Wishicraft backup " + p.operation_id,
                "Tags": [{"Key": k, "Value": v} for k, v in p.metadata.items()],
            }
        ],
        "provenance": list(db.items.values()),
        "operations": [
            _attribute_map(
                {
                    "operation_id": p.operation_id,
                    "operation_type": "BACKUP",
                    "status": "SUCCEEDED",
                    "requested_at": p.operation_requested_at.isoformat(),
                    "result": {
                        "kind": "BACKUP",
                        "backup_id": p.operation_id.replace("op-", "backup-", 1),
                        "snapshot_id": p.snapshot_id,
                        "source_volume_id": p.source_volume_id,
                        "game_id": p.game_id,
                        "category": "backup",
                    },
                }
            )
        ],
    }


def test_source_uses_actual_provenance_operation_boundary() -> None:
    evidence = source_evidence()
    unchanged = copy.deepcopy(evidence)
    source = verify_source(evidence, record().snapshot_id, ROOT)
    assert source["provenance_verified"] is True
    assert source["restore_test_completed"] is False
    assert "not a Snapshot-time manifest" in source["runtime_reconstruction"]
    assert evidence == unchanged


@pytest.mark.parametrize(
    "field,value",
    [
        ("VolumeId", "vol-other"),
        ("OwnerId", "other"),
        ("State", "pending"),
        ("Encrypted", False),
        ("VolumeSize", 16),
    ],
)
def test_source_mismatch_is_rejected(field: str, value: object) -> None:
    evidence = source_evidence()
    evidence["snapshots"][0][field] = value
    with pytest.raises(ValueError):
        verify_source(evidence, record().snapshot_id, ROOT)


def test_provenance_missing_conflicting_or_duplicate_is_rejected() -> None:
    for mutation in ("missing", "duplicate", "failed"):
        evidence = source_evidence()
        if mutation == "missing":
            evidence["provenance"].pop()
        elif mutation == "duplicate":
            evidence["operations"] *= 2
        else:
            evidence["operations"][0]["status"] = {"S": "FAILED"}
        with pytest.raises(ValueError):
            verify_source(evidence, record().snapshot_id, ROOT)


def test_template_isolates_identity_permissions_storage_and_preserves_copy() -> None:
    source = verify_source(source_evidence(), record().snapshot_id, ROOT)
    template = isolated_template(source, ROOT)
    r = template["Resources"]
    assert r["Attachment"]["Properties"]["VolumeId"] == {"Ref": "Copy"}
    assert r["Copy"]["Properties"]["SnapshotId"] == source["snapshot_id"]
    assert r["Copy"]["DeletionPolicy"] == r["Copy"]["UpdateReplacePolicy"] == "Retain"
    assert r["Host"]["Properties"]["BlockDeviceMappings"][0]["Ebs"]["DeleteOnTermination"] is False
    assert r["SecurityGroup"]["Properties"]["SecurityGroupIngress"] == []
    assert "UserData" not in r["Host"]["Properties"]
    assert {v["Value"] for v in r["Host"]["Properties"]["Tags"]} == {
        "wishicraft-restore-test",
        "restore-test",
        "isolated-restore",
    }
    policy = r["Role"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert "ssmmessages:OpenDataChannel" in policy[0]["Action"]
    assert "dynamodb:*" in policy[1]["Action"] and policy[1]["Effect"] == "Deny"
    assert "ssm:GetParameter*" in policy[1]["Action"]
    assert all(
        v["Type"] not in {"AWS::Route53::RecordSet", "AWS::DynamoDB::Table", "AWS::Events::Rule"}
        for v in r.values()
    )
