from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from wishicraft import retention_workflow_lambda
from wishicraft.backup_provenance import BackupProvenanceRecord, BackupProvenanceRepository
from wishicraft.operation import OperationStatus
from wishicraft.retention import RetentionContext

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def tags() -> dict[str, str]:
    return {
        "Project": "wishicraft",
        "Stage": "dev",
        "WishicraftCategory": "backup",
        "WishicraftGameId": "game-vanilla-main",
        "WishicraftOperationId": "op-backup",
        "WishicraftSourceVolumeId": "vol-data",
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
        "WishicraftCreatedAt": "2026-09-08T11:59:50Z",
    }


class Dynamo:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []

    def scan(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {"Items": self.items}


class Ec2:
    def __init__(self) -> None:
        self.snapshot_calls = 0

    def describe_snapshots(self, **kwargs: object) -> object:
        self.snapshot_calls += 1
        return {
            "Snapshots": [
                {
                    "SnapshotId": "snap-00000000000000001",
                    "VolumeId": "vol-data",
                    "State": "completed",
                    "OwnerId": "123456789012",
                    "StartTime": NOW,
                    "Description": "Wishicraft backup op-backup",
                    "StorageTier": "standard",
                    "Tags": [{"Key": key, "Value": value} for key, value in tags().items()],
                },
                {
                    "SnapshotId": "snap-00000000000000002",
                    "VolumeId": "vol-data",
                    "State": "completed",
                    "OwnerId": "123456789012",
                    "StartTime": NOW - timedelta(days=1),
                    "Description": "migration anchor",
                    "StorageTier": "standard",
                    "Tags": [],
                },
            ]
        }

    def describe_locked_snapshots(self, **kwargs: object) -> object:
        return {"Snapshots": []}

    def describe_volumes(self, **kwargs: object) -> object:
        return {
            "Volumes": [
                {
                    "VolumeId": "vol-data",
                    "AvailabilityZone": "ap-northeast-1a",
                    "Encrypted": True,
                    "Attachments": [
                        {
                            "InstanceId": "i-target",
                            "Device": "/dev/sdf",
                            "State": "attached",
                            "DeleteOnTermination": False,
                        }
                    ],
                }
            ]
        }


class RecycleBin:
    def __init__(self, pages: list[dict[str, object]] | None = None) -> None:
        self.pages = pages or [{"Rules": []}]
        self.calls = 0

    def list_rules(self, **kwargs: object) -> object:
        assert kwargs["ResourceType"] == "EBS_SNAPSHOT"
        result = self.pages[self.calls]
        self.calls += 1
        return result

    def get_rule(self, **kwargs: object) -> object:
        identifier = kwargs["Identifier"]
        return {
            "Identifier": identifier,
            "RuleArn": f"arn:aws:rbin:ap-northeast-1:123456789012:rule/{identifier}",
            "ResourceType": "EBS_SNAPSHOT",
            "Status": "available",
            "RetentionPeriod": {
                "RetentionPeriodValue": 7,
                "RetentionPeriodUnit": "DAYS",
            },
            "ResourceTags": [],
            "ExcludeResourceTags": [],
        }


class Leases:
    def __init__(self) -> None:
        self.verified = 0
        self.renewed = 0

    def verify_owned(self, proof: object, *, now: datetime) -> None:
        self.verified += 1

    def renew(self, proof: object, *, now: datetime, lease_seconds: int) -> object:
        self.renewed += 1
        return proof


class Operations:
    def __init__(self) -> None:
        self.steps: list[dict[str, object]] = []
        self.completions: list[dict[str, object]] = []

    def update_step(self, **kwargs: object) -> None:
        self.steps.append(kwargs)

    def complete_owned(self, **kwargs: object) -> None:
        self.completions.append(kwargs)


class Runtime:
    def __init__(self, *, with_provenance: bool = True) -> None:
        record = BackupProvenanceRecord(
            snapshot_id="snap-00000000000000001",
            operation_id="op-backup",
            game_id="game-vanilla-main",
            source_volume_id="vol-data",
            stage="dev",
            project="wishicraft",
            category="backup",
            protected=False,
            snapshot_start_time=NOW,
            operation_requested_at=NOW - timedelta(seconds=20),
            wishicraft_created_at=NOW - timedelta(seconds=10),
            provenance_recorded_at=NOW + timedelta(seconds=5),
            verified_owner_id="123456789012",
            metadata=tags(),
        )
        writes = BackupProvenanceRepository(
            cast(Any, None), table_name="backups"
        ).transactional_puts(record)
        items = [
            cast(dict[str, object], cast(dict[str, object], value["Put"])["Item"])
            for value in writes
        ]
        self.dynamodb = Dynamo(items if with_provenance else [])
        self.ec2 = Ec2()
        self.recycle_bin = RecycleBin()
        self.operations = Operations()
        self.leases = Leases()
        self.system_id = "wishicraft-main"
        self.backups_table = "backups"
        self.context = RetentionContext(
            "wishicraft", "dev", "game-vanilla-main", "vol-data", "123456789012"
        )
        self.availability_zone = "ap-northeast-1a"
        self.device = "/dev/sdf"
        self.lease_seconds = 900


def event(*, ec2_state: str = "stopped", health: str = "HEALTHY") -> dict[str, object]:
    observed = "2026-09-08T12:00:00Z"
    return {
        "schema_version": 1,
        "action": "run",
        "operation_id": "op-retention",
        "lease_id": "lease-retention",
        "state": {
            "game_id": "game-vanilla-main",
            "health": health,
            "discrepancies": [],
            "observation_errors": [],
            "observed_at": observed,
            "observation": {
                "observed_at": observed,
                "expected_game_id": "game-vanilla-main",
                "instance_id": "i-target",
                "ec2_state": ec2_state,
            },
        },
    }


@pytest.mark.parametrize("ec2_state", ["stopped", "running"])
def test_dry_run_succeeds_for_fresh_healthy_state_without_delete(
    monkeypatch: pytest.MonkeyPatch, ec2_state: str
) -> None:
    runtime = Runtime()
    monkeypatch.setattr(retention_workflow_lambda, "_runtime", runtime)
    result = retention_workflow_lambda.handler(event(ec2_state=ec2_state), None)
    assert result == {"status": "SUCCEEDED", "reason": "within-retention-limit"}
    assert runtime.leases.verified == runtime.leases.renewed == 1
    completion = runtime.operations.completions[0]
    assert completion["status"] is OperationStatus.SUCCEEDED
    evidence = cast(dict[str, object], completion["result"])
    assert evidence["keep_count"] == 1
    assert evidence["excluded_count"] == 1
    assert evidence["candidate_count"] == evidence["anomaly_count"] == 0
    assert evidence["deletion_plan_count"] == evidence["delete_action_count"] == 0
    assert not hasattr(runtime.ec2, "delete_snapshot")


def test_missing_provenance_is_visible_failed_no_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(with_provenance=False)
    monkeypatch.setattr(retention_workflow_lambda, "_runtime", runtime)
    result = retention_workflow_lambda.handler(event(), None)
    assert result == {"status": "FAILED", "reason": "inventory-anomaly"}
    completion = runtime.operations.completions[0]
    assert completion["status"] is OperationStatus.FAILED
    assert completion["error_code"] == "RETENTION_UNSAFE_INVENTORY"
    evidence = cast(dict[str, object], completion["result"])
    assert evidence["anomaly_count"] == 1
    assert evidence["delete_action_count"] == 0


@pytest.mark.parametrize("health", ["UNHEALTHY", "UNKNOWN"])
def test_unhealthy_state_fails_before_inventory(
    monkeypatch: pytest.MonkeyPatch, health: str
) -> None:
    runtime = Runtime()
    monkeypatch.setattr(retention_workflow_lambda, "_runtime", runtime)
    with pytest.raises(ValueError, match="precondition"):
        retention_workflow_lambda.handler(event(health=health), None)
    assert runtime.ec2.snapshot_calls == 0
    assert runtime.operations.completions == []


def test_discrepancy_and_stale_reconcile_shape_fail_closed() -> None:
    state = cast(dict[str, object], event()["state"])
    state["discrepancies"] = ["dns-mismatch"]
    with pytest.raises(ValueError, match="precondition"):
        retention_workflow_lambda._validate_fresh_state(state, "game-vanilla-main")
    state["discrepancies"] = []
    state["observed_at"] = "older"
    with pytest.raises(ValueError, match="precondition"):
        retention_workflow_lambda._validate_fresh_state(state, "game-vanilla-main")


def test_recycle_bin_inventory_requires_complete_nonrepeating_pagination() -> None:
    api = RecycleBin(
        [
            {"Rules": [{"Identifier": "rule-1"}], "NextToken": "page-2"},
            {"Rules": [{"Identifier": "rule-2"}]},
        ]
    )
    rules = retention_workflow_lambda._load_complete_recycle_bin_rules(api)
    assert [rule["Identifier"] for rule in rules] == ["rule-1", "rule-2"]
    assert api.calls == 2

    repeating = RecycleBin(
        [
            {"Rules": [], "NextToken": "again"},
            {"Rules": [], "NextToken": "again"},
        ]
    )
    with pytest.raises(ValueError, match="pagination"):
        retention_workflow_lambda._load_complete_recycle_bin_rules(repeating)


def test_provenance_inventory_requires_complete_nonrepeating_pagination() -> None:
    class RepeatingDynamo:
        def scan(self, **kwargs: object) -> object:
            return {"Items": [], "LastEvaluatedKey": {"pk": {"S": "same"}}}

    with pytest.raises(ValueError, match="pagination"):
        retention_workflow_lambda._scan_all(cast(Any, RepeatingDynamo()), "backups")


def test_provenance_loader_rejects_self_consistent_non_d090_metadata() -> None:
    runtime = Runtime()
    provenance = next(
        item
        for item in runtime.dynamodb.items
        if cast(dict[str, object], item["record_type"])["S"] == "BACKUP_PROVENANCE"
    )
    metadata_attributes = cast(dict[str, object], provenance["metadata"])["M"]
    metadata = cast(dict[str, dict[str, str]], metadata_attributes)
    metadata["WishicraftCategory"] = {"S": "migration"}
    decoded_metadata = {key: value["S"] for key, value in metadata.items()}
    fingerprint = hashlib.sha256(
        json.dumps(
            decoded_metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    provenance["metadata_fingerprint"] = {"S": fingerprint}
    with pytest.raises(ValueError, match="partial Backup provenance pair"):
        retention_workflow_lambda._load_complete_provenance(
            cast(Any, runtime.dynamodb), "backups", runtime.context
        )
