"""Versioned Lambda task boundary for the Phase 8A BACKUP state machine."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.backup import (
    BackupCoordinator,
    BackupErrorCode,
    BackupWorkflowError,
    Ec2SnapshotApi,
    SnapshotAdapter,
)
from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    LeaseRepository,
    OperationRepository,
    OperationStatus,
)


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class Runtime:
    def __init__(self) -> None:
        boto3 = cast(AwsSession, importlib.import_module("boto3"))
        region = _env("AWS_REGION")
        dynamodb = cast(DynamoApi, boto3.client("dynamodb", region_name=region))
        ec2 = cast(Ec2SnapshotApi, boto3.client("ec2", region_name=region))
        self.system_id = _env("SYSTEM_ID")
        self.operations = OperationRepository(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            system_id=self.system_id,
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        leases = LeaseRepository(
            dynamodb, table_name=_env("LOCKS_TABLE"), lock_name=_env("GLOBAL_LOCK_NAME")
        )
        self.coordinator = BackupCoordinator(
            leases=leases,
            snapshots=SnapshotAdapter(ec2, account_id=_env("AWS_ACCOUNT_ID")),
            expected_volume_id=_env("DATA_VOLUME_ID"),
            availability_zone=_env("AVAILABILITY_ZONE"),
            project=_env("PROJECT"),
            stage=_env("STAGE"),
            game_id=_env("GAME_ID"),
            lease_seconds=int(_env("LOCK_LEASE_SECONDS")),
        )


_runtime: Runtime | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    payload = _payload(event)
    runtime = _get_runtime()
    now = datetime.now(UTC)
    proof = LeaseProof(
        runtime.system_id,
        _string(payload, "operation_id"),
        _string(payload, "lease_id"),
        0,
    )
    action = _string(payload, "action")
    if action == "preflight":
        runtime.coordinator.preflight(proof=proof, state=_mapping(payload, "state"), now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="SNAPSHOT_CREATING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        return {"allowed": True}
    if action == "create":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        tags = runtime.coordinator.tags(
            operation_id=proof.owner_operation_id,
            requested_at=now.isoformat().replace("+00:00", "Z"),
        )
        record = runtime.coordinator.snapshots.create_once(
            volume_id=runtime.coordinator.expected_volume_id, tags=tags
        )
        if record.source_volume_id != runtime.coordinator.expected_volume_id or record.tags != tags:
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        return {"snapshot_id": record.snapshot_id, "tags": tags}
    if action == "poll":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        record = runtime.coordinator.snapshots.describe(_string(payload, "snapshot_id"))
        if record.state == "error":
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_FAILED)
        if record.state not in {"pending", "completed"}:
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        return {"state": record.state, "complete": record.state == "completed"}
    if action == "renew":
        renewed = runtime.coordinator.renew(proof, now=now)
        return {"lease_expires_at": renewed.lease_expires_at}
    if action == "complete":
        snapshot_id = _string(payload, "snapshot_id")
        tags = _string_mapping(payload, "tags")
        record = runtime.coordinator.snapshots.describe(snapshot_id)
        runtime.coordinator.verify_completed(record, expected_tags=tags)
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.SUCCEEDED,
            completed_at=now,
            result={
                "kind": "BACKUP",
                "backup_id": proof.owner_operation_id.replace("op-", "backup-", 1),
                "snapshot_id": snapshot_id,
                "source_volume_id": runtime.coordinator.expected_volume_id,
                "game_id": runtime.coordinator.game_id,
                "category": "backup",
            },
        )
        return {"status": "SUCCEEDED"}
    if action == "fail":
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.FAILED,
            completed_at=now,
            error_code=_string(payload, "error_code"),
        )
        return {"status": "FAILED"}
    raise ValueError("unsupported BACKUP workflow action")


def _payload(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("invalid BACKUP workflow invocation")
    for key in ("action", "operation_id", "lease_id"):
        _string(event, key)
    return event


def _mapping(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise ValueError(f"invalid {name}")
    return result


def _string_mapping(value: dict[str, object], name: str) -> dict[str, str]:
    result = _mapping(value, name)
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in result.items()):
        raise ValueError(f"invalid {name}")
    return cast(dict[str, str], result)


def _string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError(f"invalid {name}")
    return result


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime
