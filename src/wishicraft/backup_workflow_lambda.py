"""Versioned Lambda task boundary for the Phase 8A BACKUP state machine."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from typing import Protocol, cast

from botocore.config import Config  # type: ignore[import-untyped]

from wishicraft.backup import (
    BackupCoordinator,
    BackupErrorCode,
    BackupWorkflowError,
    Ec2SnapshotApi,
    SnapshotAdapter,
)
from wishicraft.backup_create import (
    BackupCreateGuard,
    BackupCreateOutcomeUnknown,
    BackupCreateRejected,
    BackupProvenanceOutcomeUnknown,
)
from wishicraft.backup_provenance import (
    BackupOperationEvidence,
    BackupProvenanceRepository,
    build_verified_provenance,
)
from wishicraft.backup_recovery import RecoveryRepository, recovery_digest, shared_tags
from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    LeaseRepository,
    OperationRepository,
    OperationStatus,
    OperationType,
)
from wishicraft.runtime_catalog import configured_catalog


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class Runtime:
    def __init__(self) -> None:
        boto3 = cast(AwsSession, importlib.import_module("boto3"))
        region = _env("AWS_REGION")
        dynamodb = cast(DynamoApi, boto3.client("dynamodb", region_name=region))
        ec2 = cast(Ec2SnapshotApi, boto3.client("ec2", region_name=region))
        create_ec2 = cast(
            Ec2SnapshotApi,
            boto3.client(
                "ec2",
                region_name=region,
                config=Config(retries={"total_max_attempts": 1, "mode": "standard"}),
            ),
        )
        self.create_guard = BackupCreateGuard(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        self.system_id = _env("SYSTEM_ID")
        self.recovery = RecoveryRepository(
            dynamodb, _env("OPERATIONS_TABLE"), os.environ.get("GAMES_TABLE", "")
        )
        self.operations = OperationRepository(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            system_id=self.system_id,
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        self.provenance = BackupProvenanceRepository(dynamodb, table_name=_env("BACKUPS_TABLE"))
        leases = LeaseRepository(
            dynamodb, table_name=_env("LOCKS_TABLE"), lock_name=_env("GLOBAL_LOCK_NAME")
        )
        self.coordinator = BackupCoordinator(
            leases=leases,
            snapshots=SnapshotAdapter(
                ec2, account_id=_env("AWS_ACCOUNT_ID"), create_api=create_ec2
            ),
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
    catalog = configured_catalog()
    if catalog is not None:
        raw = runtime.recovery.operation(proof.owner_operation_id)
        game_id = raw["target_game_id"]["S"]
        catalog.data_source(game_id)
        runtime.coordinator.game_id = game_id
    if action == "preflight":
        runtime.coordinator.preflight(proof=proof, state=_mapping(payload, "state"), now=now)
        if catalog is not None:
            runtime.recovery.freeze(
                operation_id=proof.owner_operation_id,
                lease_id=proof.lease_id,
                catalog=catalog,
                volume=runtime.coordinator.expected_volume_id,
                runtime_json=_env("RECOVERY_RUNTIME_JSON"),
            )
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
        if catalog is not None:
            tags = shared_tags(tags, runtime.recovery.read(proof.owner_operation_id))
        runtime.create_guard.reserve(proof=proof, tags=tags, now=now)
        runtime.coordinator.leases.verify_owned(proof, now=datetime.now(UTC))
        try:
            record = runtime.coordinator.snapshots.create_once(
                volume_id=runtime.coordinator.expected_volume_id, tags=tags
            )
        except Exception as error:
            response = getattr(error, "response", None)
            detail = response.get("Error") if isinstance(response, dict) else None
            metadata = response.get("ResponseMetadata") if isinstance(response, dict) else None
            if (
                isinstance(detail, dict)
                and isinstance(metadata, dict)
                and metadata.get("HTTPStatusCode") in {400, 403}
                and detail.get("Code")
                in {
                    "UnauthorizedOperation",
                    "AuthFailure",
                    "InvalidVolume.NotFound",
                    "InvalidParameterValue",
                }
            ):
                raise BackupCreateRejected("EC2 explicitly rejected creation") from None
            raise BackupCreateOutcomeUnknown("snapshot creation outcome unknown") from None
        if record.source_volume_id != runtime.coordinator.expected_volume_id or record.tags != tags:
            raise BackupCreateOutcomeUnknown("snapshot response verification failed")
        runtime.create_guard.record_snapshot(proof=proof, snapshot_id=record.snapshot_id, tags=tags)
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
        if record.start_time is None or record.storage_tier != "standard":
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        raw_operation = runtime.operations.load_backup_evidence(proof.owner_operation_id)
        operation_result = raw_operation["result"]
        if operation_result is not None and not isinstance(operation_result, dict):
            raise ValueError("malformed BACKUP Operation result")
        requested_at = datetime.fromisoformat(
            str(raw_operation["requested_at"]).replace("Z", "+00:00")
        )
        provenance = build_verified_provenance(
            snapshot=record,
            operation=BackupOperationEvidence(
                operation_id=proof.owner_operation_id,
                operation_type=str(raw_operation["operation_type"]),
                status=str(raw_operation["status"]),
                requested_at=requested_at,
                result=operation_result or {},
            ),
            project=runtime.coordinator.project,
            stage=runtime.coordinator.stage,
            game_id=runtime.coordinator.game_id,
            source_volume_id=runtime.coordinator.expected_volume_id,
            owner_id=record.owner_id,
            provenance_recorded_at=now,
            require_succeeded_operation=raw_operation["status"] == "SUCCEEDED",
            recovery_json=runtime.recovery.read(proof.owner_operation_id)
            if catalog is not None
            else None,
        )
        should_create = runtime.provenance.assert_createable_or_exact(provenance)
        result: dict[str, object] = {
            "kind": "BACKUP",
            "backup_id": proof.owner_operation_id.replace("op-", "backup-", 1),
            "snapshot_id": snapshot_id,
            "source_volume_id": runtime.coordinator.expected_volume_id,
            "game_id": runtime.coordinator.game_id,
            "category": "backup",
        }
        if catalog is not None:
            result.update(
                {
                    "scope": "shared-volume",
                    "recovery_digest": recovery_digest(
                        runtime.recovery.read(proof.owner_operation_id)
                    ),
                }
            )
        if not should_create:
            if not runtime.operations.terminal_result_matches(
                operation_id=proof.owner_operation_id,
                operation_type=OperationType.BACKUP,
                result=result,
            ):
                raise ValueError("Backup provenance exists without matching terminal Operation")
            return {"status": "SUCCEEDED"}
        try:
            runtime.operations.complete_owned(
                proof=proof,
                status=OperationStatus.SUCCEEDED,
                completed_at=now,
                result=result,
                additional_writes=runtime.provenance.transactional_puts(provenance),
            )
        except Exception:
            if not (
                runtime.provenance.exact_match(provenance)
                and runtime.operations.terminal_result_matches(
                    operation_id=proof.owner_operation_id,
                    operation_type=OperationType.BACKUP,
                    result=result,
                )
            ):
                raise BackupProvenanceOutcomeUnknown("provenance commit not established") from None
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
