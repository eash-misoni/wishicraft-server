"""Operator entrypoint for evidence-verified, conditional BACKUP provenance backfill."""

from __future__ import annotations

import argparse
import importlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from wishicraft.backup import Ec2SnapshotApi, SnapshotAdapter
from wishicraft.backup_provenance import (
    BackupOperationEvidence,
    BackupProvenanceRecord,
    BackupProvenanceRepository,
    DynamoProvenanceApi,
    build_verified_provenance,
)
from wishicraft.config import load_configuration
from wishicraft.naming import resource_name
from wishicraft.operation import DynamoApi, OperationRepository
from wishicraft.retention import SnapshotLockApi, load_complete_snapshot_locks, parse_rfc3339


class StsApi(Protocol):
    def get_caller_identity(self) -> object: ...


class Session(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class DynamoBackfillApi(DynamoApi, DynamoProvenanceApi, Protocol):
    def scan(self, **kwargs: object) -> object: ...


def execute_backfill(
    *,
    dynamodb: DynamoBackfillApi,
    ec2: Ec2SnapshotApi,
    sts: StsApi,
    repository_root: Path,
    stage_name: str,
    snapshot_ids: tuple[str, ...],
) -> tuple[BackupProvenanceRecord, ...]:
    """Revalidate production evidence and conditionally register immutable pairs."""
    if not snapshot_ids or len(set(snapshot_ids)) != len(snapshot_ids):
        raise ValueError("snapshot IDs must be a non-empty unique set")
    config = load_configuration(repository_root, stage_name)
    stage = config.stage
    project = config.project
    caller = sts.get_caller_identity()
    if not isinstance(caller, dict) or caller.get("Account") != stage.aws_account_id:
        raise ValueError("caller account does not match stage configuration")
    source_volume_id = stage.host_runtime_value("target_host.existing_data_volume_id")
    if not isinstance(source_volume_id, str) or not source_volume_id:
        raise ValueError("stage Data EBS binding is unavailable")
    operations_table = resource_name(project.resource_prefix, stage.stage, "operations")
    backups_table = resource_name(project.resource_prefix, stage.stage, "backups")
    operations = OperationRepository(
        dynamodb,
        operations_table=operations_table,
        locks_table=resource_name(project.resource_prefix, stage.stage, "locks"),
        system_state_table=resource_name(project.resource_prefix, stage.stage, "system-state"),
        system_id=project.system_id,
        lock_name=stage.global_lock_name,
    )
    snapshots = SnapshotAdapter(ec2, account_id=stage.aws_account_id)
    lock_states = load_complete_snapshot_locks(cast(SnapshotLockApi, ec2))
    mapping = _load_complete_operation_snapshot_mapping(dynamodb, operations_table)
    records: list[BackupProvenanceRecord] = []
    for snapshot_id in snapshot_ids:
        snapshot = snapshots.describe(snapshot_id)
        operation_id = snapshot.tags.get("WishicraftOperationId", "")
        if lock_states.get(snapshot_id) in {"governance", "compliance-cooloff", "compliance"}:
            raise ValueError("backfill snapshot has an active Snapshot Lock")
        if mapping.get(snapshot_id) != (operation_id,):
            raise ValueError("snapshot/Operation result mapping is not unique")
        raw = operations.load_backup_evidence(operation_id)
        result = raw["result"]
        if not isinstance(result, dict):
            raise ValueError("BACKUP Operation result is unavailable")
        requested_at = _strict_timestamp(str(raw["requested_at"]))
        recorded_at = datetime.now(UTC)
        records.append(
            build_verified_provenance(
                snapshot=snapshot,
                operation=BackupOperationEvidence(
                    operation_id=operation_id,
                    operation_type=str(raw["operation_type"]),
                    status=str(raw["status"]),
                    requested_at=requested_at,
                    result=result,
                ),
                project=project.project_slug,
                stage=stage.stage,
                game_id=project.initial_game_id,
                source_volume_id=source_volume_id,
                owner_id=stage.aws_account_id,
                provenance_recorded_at=recorded_at,
            )
        )
    allowed_keys = {
        key
        for record in records
        for key in (f"SNAPSHOT#{record.snapshot_id}", f"OPERATION#{record.operation_id}")
    }
    existing_keys = _load_complete_provenance_keys(dynamodb, backups_table)
    if existing_keys - allowed_keys:
        raise ValueError("Backups table contains an unrelated record")
    repository = BackupProvenanceRepository(
        cast(DynamoProvenanceApi, dynamodb), table_name=backups_table
    )
    for record in records:
        repository.register(record)
        if not repository.exact_match(record):
            raise ValueError("provenance registration did not converge exactly")
    return tuple(records)


def _load_complete_operation_snapshot_mapping(
    dynamodb: DynamoBackfillApi, table_name: str
) -> dict[str, tuple[str, ...]]:
    token: dict[str, object] | None = None
    values: dict[str, list[str]] = {}
    while True:
        request: dict[str, object] = {
            "TableName": table_name,
            "ProjectionExpression": "operation_id, #result",
            "ExpressionAttributeNames": {"#result": "result"},
            "ConsistentRead": True,
        }
        if token is not None:
            request["ExclusiveStartKey"] = token
        response = dynamodb.scan(**request)
        if not isinstance(response, dict) or not isinstance(response.get("Items"), list):
            raise ValueError("Operation inventory is incomplete")
        for item in response["Items"]:
            if not isinstance(item, dict):
                raise ValueError("malformed Operation inventory")
            operation_id = cast(str, _string_attribute(item.get("operation_id")))
            result = item.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("M"), dict):
                continue
            snapshot_id = _string_attribute(result["M"].get("snapshot_id"), required=False)
            if snapshot_id is not None:
                values.setdefault(snapshot_id, []).append(operation_id)
        raw_token = response.get("LastEvaluatedKey")
        if raw_token is None:
            return {key: tuple(value) for key, value in values.items()}
        if not isinstance(raw_token, dict) or not raw_token or raw_token == token:
            raise ValueError("Operation pagination is invalid")
        token = raw_token


def _load_complete_provenance_keys(dynamodb: DynamoBackfillApi, table_name: str) -> set[str]:
    token: dict[str, object] | None = None
    result: set[str] = set()
    while True:
        request: dict[str, object] = {
            "TableName": table_name,
            "ProjectionExpression": "provenance_key",
            "ConsistentRead": True,
        }
        if token is not None:
            request["ExclusiveStartKey"] = token
        response = dynamodb.scan(**request)
        if not isinstance(response, dict) or not isinstance(response.get("Items"), list):
            raise ValueError("provenance inventory is incomplete")
        for item in response["Items"]:
            if not isinstance(item, dict):
                raise ValueError("malformed provenance inventory")
            key = cast(str, _string_attribute(item.get("provenance_key")))
            if key in result:
                raise ValueError("duplicate provenance key")
            result.add(key)
        raw_token = response.get("LastEvaluatedKey")
        if raw_token is None:
            return result
        if not isinstance(raw_token, dict) or not raw_token or raw_token == token:
            raise ValueError("provenance pagination is invalid")
        token = raw_token


def _string_attribute(value: object, *, required: bool = True) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("S"), str) and value["S"]:
        return cast(str, value["S"])
    if required:
        raise ValueError("malformed DynamoDB string attribute")
    return None


def _strict_timestamp(value: str) -> datetime:
    return parse_rfc3339(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--snapshot-id", action="append", required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    config = load_configuration(repository_root, args.stage)
    boto3 = cast(Session, importlib.import_module("boto3").Session(profile_name=args.profile))
    records = execute_backfill(
        dynamodb=cast(
            DynamoBackfillApi, boto3.client("dynamodb", region_name=config.stage.aws_region)
        ),
        ec2=cast(Ec2SnapshotApi, boto3.client("ec2", region_name=config.stage.aws_region)),
        sts=cast(StsApi, boto3.client("sts", region_name=config.stage.aws_region)),
        repository_root=repository_root,
        stage_name=args.stage,
        snapshot_ids=tuple(args.snapshot_id),
    )
    for record in records:
        print(f"registered {record.snapshot_id} -> {record.operation_id}")


if __name__ == "__main__":
    main()
