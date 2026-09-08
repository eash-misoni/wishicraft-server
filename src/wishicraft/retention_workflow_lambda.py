"""Dry-run-only RETENTION task; this module has no snapshot mutation adapter."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.backup import REQUIRED_TAG_KEYS
from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    LeaseRepository,
    OperationRepository,
    OperationStatus,
)
from wishicraft.retention import (
    BackupProvenance,
    RetentionContext,
    RetentionRunStatus,
    SnapshotInventoryApi,
    SnapshotLockApi,
    load_complete_inventory,
    load_complete_snapshot_locks,
    parse_rfc3339,
    plan_retention,
    with_lock_states,
)


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class RetentionEc2Api(SnapshotInventoryApi, SnapshotLockApi, Protocol):
    def describe_volumes(self, **kwargs: object) -> object: ...


class RecycleBinApi(Protocol):
    def list_rules(self, **kwargs: object) -> object: ...
    def get_rule(self, **kwargs: object) -> object: ...


class RetentionDynamoApi(DynamoApi, Protocol):
    def scan(self, **kwargs: object) -> object: ...


class Runtime:
    def __init__(self) -> None:
        boto3 = cast(AwsSession, importlib.import_module("boto3"))
        region = _env("AWS_REGION")
        dynamodb = cast(RetentionDynamoApi, boto3.client("dynamodb", region_name=region))
        self.ec2 = cast(RetentionEc2Api, boto3.client("ec2", region_name=region))
        self.recycle_bin = cast(RecycleBinApi, boto3.client("rbin", region_name=region))
        self.system_id = _env("SYSTEM_ID")
        self.operations = OperationRepository(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            system_id=self.system_id,
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        self.leases = LeaseRepository(
            dynamodb, table_name=_env("LOCKS_TABLE"), lock_name=_env("GLOBAL_LOCK_NAME")
        )
        self.dynamodb = dynamodb
        self.backups_table = _env("BACKUPS_TABLE")
        self.context = RetentionContext(
            project=_env("PROJECT"),
            stage=_env("STAGE"),
            game_id=_env("GAME_ID"),
            source_volume_id=_env("DATA_VOLUME_ID"),
            owner_id=_env("AWS_ACCOUNT_ID"),
        )
        self.availability_zone = _env("AVAILABILITY_ZONE")
        self.device = _env("DATA_VOLUME_DEVICE")
        self.lease_seconds = int(_env("LOCK_LEASE_SECONDS"))


_runtime: Runtime | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    payload = _payload(event)
    runtime = _get_runtime()
    now = datetime.now(UTC)
    proof = LeaseProof(
        runtime.system_id, _string(payload, "operation_id"), _string(payload, "lease_id"), 0
    )
    action = _string(payload, "action")
    if action == "run":
        runtime.leases.verify_owned(proof, now=now)
        runtime.leases.renew(proof, now=now, lease_seconds=runtime.lease_seconds)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="RETENTION_INVENTORY",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        state = _mapping(payload, "state")
        instance_id = _validate_fresh_state(state, runtime.context.game_id)
        _validate_source_volume(runtime, instance_id)
        inventory = with_lock_states(
            load_complete_inventory(runtime.ec2, owner_id=runtime.context.owner_id),
            load_complete_snapshot_locks(runtime.ec2),
        )
        provenances = _load_complete_provenance(
            runtime.dynamodb, runtime.backups_table, runtime.context
        )
        rules = _load_complete_recycle_bin_rules(runtime.recycle_bin)
        plan = plan_retention(
            inventory,
            provenances,
            context=runtime.context,
            recycle_bin_preflight_complete=True,
        )
        retention_owned_ids = set(plan.keep_ids) | set(plan.candidate_ids)
        matching_rules = sum(
            1
            for rule in rules
            if any(
                _rule_matches(rule, item.tags)
                for item in inventory
                if item.snapshot_id in retention_owned_ids
            )
        )
        result: dict[str, object] = {
            "kind": "RETENTION_DRY_RUN",
            "reason": plan.reason,
            "inventory_count": plan.inventory_count,
            "keep_count": len(plan.keep_ids),
            "candidate_count": len(plan.candidate_ids),
            "excluded_count": len(plan.excluded_ids),
            "anomaly_count": len(plan.anomaly_ids),
            "deletion_plan_count": len(plan.planned_delete_ids),
            "delete_action_count": 0,
            "keep_snapshot_ids": list(plan.keep_ids),
            "candidate_snapshot_ids": list(plan.candidate_ids),
            "excluded_snapshot_ids": list(plan.excluded_ids),
            "anomaly_snapshot_ids": list(plan.anomaly_ids),
            "would_delete_snapshot_ids": list(plan.planned_delete_ids),
            "recycle_bin_rule_count": len(rules),
            "matching_recycle_bin_rule_count": matching_rules,
        }
        if plan.status is RetentionRunStatus.NO_DELETE:
            runtime.operations.complete_owned(
                proof=proof,
                status=OperationStatus.FAILED,
                completed_at=now,
                error_code="RETENTION_UNSAFE_INVENTORY",
                result=result,
            )
            return {"status": "FAILED", "reason": plan.reason}
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.SUCCEEDED,
            completed_at=now,
            result=result,
        )
        return {"status": "SUCCEEDED", "reason": plan.reason}
    if action == "fail":
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.FAILED,
            completed_at=now,
            error_code=_string(payload, "error_code"),
        )
        return {"status": "FAILED"}
    raise ValueError("unsupported RETENTION workflow action")


def _validate_fresh_state(state: dict[str, object], expected_game_id: str) -> str:
    observation = state.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("RETENTION observation is incomplete")
    if (
        state.get("health") != "HEALTHY"
        or state.get("game_id") != expected_game_id
        or state.get("discrepancies") != []
        or state.get("observation_errors") != []
        or state.get("observed_at") != observation.get("observed_at")
        or observation.get("expected_game_id") != expected_game_id
        or observation.get("ec2_state") not in {"running", "stopped"}
    ):
        raise ValueError("RETENTION precondition failed")
    instance_id = observation.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("RETENTION observation is incomplete")
    return instance_id


def _validate_source_volume(runtime: Runtime, expected_instance_id: str) -> None:
    response = runtime.ec2.describe_volumes(VolumeIds=[runtime.context.source_volume_id])
    volumes = response.get("Volumes") if isinstance(response, dict) else None
    if not isinstance(volumes, list) or len(volumes) != 1 or not isinstance(volumes[0], dict):
        raise ValueError("RETENTION source volume is unavailable")
    volume = volumes[0]
    attachments = volume.get("Attachments")
    if (
        volume.get("VolumeId") != runtime.context.source_volume_id
        or volume.get("AvailabilityZone") != runtime.availability_zone
        or volume.get("Encrypted") is not True
        or not isinstance(attachments, list)
        or len(attachments) != 1
        or not isinstance(attachments[0], dict)
        or attachments[0].get("InstanceId") != expected_instance_id
        or attachments[0].get("Device") != runtime.device
        or attachments[0].get("State") != "attached"
        or attachments[0].get("DeleteOnTermination") is not False
    ):
        raise ValueError("RETENTION source volume binding mismatch")


def _load_complete_provenance(
    api: RetentionDynamoApi, table_name: str, context: RetentionContext
) -> dict[str, BackupProvenance]:
    items = _scan_all(api, table_name)
    decoded = [_decode_map(item) for item in items]
    snapshots = {
        _required_string(item, "snapshot_id"): item
        for item in decoded
        if item.get("record_type") == "BACKUP_PROVENANCE"
    }
    operations = {
        _required_string(item, "operation_id"): item
        for item in decoded
        if item.get("record_type") == "BACKUP_OPERATION_UNIQUENESS"
    }
    if len(decoded) != len(snapshots) + len(operations):
        raise ValueError("unknown Backup provenance record")
    result: dict[str, BackupProvenance] = {}
    for snapshot_id, item in snapshots.items():
        operation_id = _required_string(item, "operation_id")
        reverse = operations.get(operation_id)
        metadata = item.get("metadata")
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in metadata.items()
        ):
            raise ValueError("malformed Backup provenance metadata")
        typed_metadata = cast(dict[str, str], metadata)
        fingerprint = hashlib.sha256(
            json.dumps(
                typed_metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if (
            reverse is None
            or reverse.get("snapshot_id") != snapshot_id
            or reverse.get("schema_version") != 1
            or item.get("project") != context.project
            or item.get("stage") != context.stage
            or item.get("game_id") != context.game_id
            or item.get("source_volume_id") != context.source_volume_id
            or item.get("verified_owner_id") != context.owner_id
            or item.get("category") != "backup"
            or item.get("protected") is not False
            or item.get("verification_status") != "VERIFIED_BACKUP_SUCCEEDED"
            or item.get("metadata_fingerprint") != fingerprint
            or set(typed_metadata) != REQUIRED_TAG_KEYS
            or typed_metadata.get("Project") != context.project
            or typed_metadata.get("Stage") != context.stage
            or typed_metadata.get("WishicraftCategory") != "backup"
            or typed_metadata.get("WishicraftGameId") != context.game_id
            or typed_metadata.get("WishicraftOperationId") != operation_id
            or typed_metadata.get("WishicraftSourceVolumeId") != context.source_volume_id
            or typed_metadata.get("WishicraftSchemaVersion") != "1"
            or typed_metadata.get("WishicraftProtected") != "false"
            or parse_rfc3339(typed_metadata.get("WishicraftCreatedAt", ""))
            != parse_rfc3339(_required_string(item, "wishicraft_created_at"))
        ):
            raise ValueError("partial Backup provenance pair")
        result[snapshot_id] = BackupProvenance(
            snapshot_id=snapshot_id,
            operation_id=operation_id,
            game_id=_required_string(item, "game_id"),
            stage=_required_string(item, "stage"),
            source_volume_id=_required_string(item, "source_volume_id"),
            operation_requested_at=parse_rfc3339(_required_string(item, "operation_requested_at")),
            wishicraft_created_at=parse_rfc3339(_required_string(item, "wishicraft_created_at")),
            snapshot_start_time=parse_rfc3339(_required_string(item, "snapshot_start_time")),
            provenance_recorded_at=parse_rfc3339(_required_string(item, "provenance_recorded_at")),
            schema_version=_required_int(item, "schema_version"),
        )
    if len(result) != len(operations):
        raise ValueError("orphan Backup provenance uniqueness record")
    return result


def _scan_all(api: RetentionDynamoApi, table_name: str) -> list[dict[str, object]]:
    token: dict[str, object] | None = None
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    while True:
        request: dict[str, object] = {"TableName": table_name, "ConsistentRead": True}
        if token is not None:
            request["ExclusiveStartKey"] = token
        response = api.scan(**request)
        if not isinstance(response, dict):
            raise ValueError("incomplete Backup provenance inventory")
        items = response.get("Items")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError("incomplete Backup provenance inventory")
        result.extend(cast(list[dict[str, object]], items))
        raw_token = response.get("LastEvaluatedKey")
        if raw_token is None:
            return result
        marker = repr(raw_token)
        if not isinstance(raw_token, dict) or not raw_token or marker in seen:
            raise ValueError("invalid Backup provenance pagination")
        seen.add(marker)
        token = raw_token


def _load_complete_recycle_bin_rules(api: RecycleBinApi) -> list[dict[str, object]]:
    token: str | None = None
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    while True:
        request: dict[str, object] = {"ResourceType": "EBS_SNAPSHOT", "MaxResults": 100}
        if token is not None:
            request["NextToken"] = token
        response = api.list_rules(**request)
        if not isinstance(response, dict):
            raise ValueError("incomplete Recycle Bin rule inventory")
        rules = response.get("Rules")
        if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
            raise ValueError("incomplete Recycle Bin rule inventory")
        for summary in cast(list[dict[str, object]], rules):
            identifier = summary.get("Identifier")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError("malformed Recycle Bin rule summary")
            detail = api.get_rule(Identifier=identifier)
            result.append(_validate_recycle_bin_rule(detail, identifier))
        raw_token = response.get("NextToken")
        if raw_token is None:
            return result
        if not isinstance(raw_token, str) or not raw_token or raw_token in seen:
            raise ValueError("invalid Recycle Bin pagination")
        seen.add(raw_token)
        token = raw_token


def _rule_matches(rule: dict[str, object], tags: dict[str, str]) -> bool:
    if rule.get("Status") != "available":
        return False
    included = _tag_map(rule.get("ResourceTags", []))
    excluded = _tag_map(rule.get("ExcludeResourceTags", []))
    return all(tags.get(key) == value for key, value in included.items()) and not any(
        tags.get(key) == value for key, value in excluded.items()
    )


def _validate_recycle_bin_rule(value: object, identifier: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("malformed Recycle Bin rule")
    retention = value.get("RetentionPeriod")
    lock_state = value.get("LockState")
    if (
        value.get("Identifier") != identifier
        or value.get("ResourceType") != "EBS_SNAPSHOT"
        or value.get("Status") not in {"pending", "available"}
        or not isinstance(value.get("RuleArn"), str)
        or not isinstance(retention, dict)
        or retention.get("RetentionPeriodUnit") != "DAYS"
        or not isinstance(retention.get("RetentionPeriodValue"), int)
        or not 1 <= cast(int, retention["RetentionPeriodValue"]) <= 365
        or (lock_state is not None and lock_state not in {"locked", "pending_unlock", "unlocked"})
    ):
        raise ValueError("malformed Recycle Bin rule")
    _tag_map(value.get("ResourceTags", []))
    _tag_map(value.get("ExcludeResourceTags", []))
    return value


def _tag_map(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        raise ValueError("malformed Recycle Bin rule tags")
    result: dict[str, str] = {}
    for tag in value:
        if not isinstance(tag, dict) or not isinstance(tag.get("ResourceTagKey"), str):
            raise ValueError("malformed Recycle Bin rule tag")
        key = cast(str, tag["ResourceTagKey"])
        raw = tag.get("ResourceTagValue", "")
        if not isinstance(raw, str) or key in result:
            raise ValueError("malformed Recycle Bin rule tag")
        result[key] = raw
    return result


def _payload(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("invalid RETENTION workflow invocation")
    for key in ("action", "operation_id", "lease_id"):
        _string(event, key)
    return event


def _mapping(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise ValueError(f"invalid {name}")
    return result


def _string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError(f"invalid {name}")
    return result


def _required_string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError("malformed Backup provenance")
    return result


def _required_int(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError("malformed Backup provenance")
    return result


def _decode(value: object) -> object:
    if not isinstance(value, dict):
        raise ValueError("malformed DynamoDB attribute")
    if isinstance(value.get("S"), str):
        return value["S"]
    if isinstance(value.get("N"), str):
        return int(cast(str, value["N"]))
    if isinstance(value.get("BOOL"), bool):
        return value["BOOL"]
    if isinstance(value.get("M"), dict):
        return _decode_map(cast(dict[str, object], value["M"]))
    raise ValueError("unsupported DynamoDB attribute")


def _decode_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _decode(item) for key, item in value.items()}


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
