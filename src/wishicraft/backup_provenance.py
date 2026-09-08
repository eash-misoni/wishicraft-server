"""Immutable, non-TTL Backup provenance persistence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from wishicraft.backup import REQUIRED_TAG_KEYS, SnapshotRecord
from wishicraft.system_state import utc_timestamp


class DynamoProvenanceApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def transact_write_items(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class BackupProvenanceRecord:
    snapshot_id: str
    operation_id: str
    game_id: str
    source_volume_id: str
    stage: str
    project: str
    category: str
    protected: bool
    snapshot_start_time: datetime
    operation_requested_at: datetime
    wishicraft_created_at: datetime
    provenance_recorded_at: datetime
    verified_owner_id: str
    metadata: dict[str, str]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.category != "backup" or self.protected:
            raise ValueError("invalid Backup provenance classification")
        for value in (
            self.operation_requested_at,
            self.wishicraft_created_at,
            self.snapshot_start_time,
            self.provenance_recorded_at,
        ):
            utc_timestamp(value)
        expected_metadata = {
            "Project": self.project,
            "Stage": self.stage,
            "WishicraftCategory": self.category,
            "WishicraftGameId": self.game_id,
            "WishicraftOperationId": self.operation_id,
            "WishicraftSourceVolumeId": self.source_volume_id,
            "WishicraftSchemaVersion": str(self.schema_version),
            "WishicraftProtected": "false",
        }
        try:
            created_at = _parse_rfc3339(self.metadata.get("WishicraftCreatedAt", ""))
        except ValueError as error:
            raise ValueError("invalid Backup provenance metadata") from error
        if (
            not all(
                (
                    self.snapshot_id,
                    self.operation_id,
                    self.game_id,
                    self.source_volume_id,
                    self.stage,
                    self.project,
                    self.verified_owner_id,
                )
            )
            or set(self.metadata) != REQUIRED_TAG_KEYS
            or any(self.metadata.get(key) != value for key, value in expected_metadata.items())
            or created_at.astimezone(UTC) != self.wishicraft_created_at.astimezone(UTC)
        ):
            raise ValueError("invalid Backup provenance metadata")
        if self.metadata_fingerprint != _metadata_fingerprint(self.metadata):
            raise AssertionError("unreachable metadata fingerprint mismatch")

    @property
    def metadata_fingerprint(self) -> str:
        return _metadata_fingerprint(self.metadata)

    def snapshot_item(self) -> dict[str, object]:
        return {
            "provenance_key": f"SNAPSHOT#{self.snapshot_id}",
            "record_type": "BACKUP_PROVENANCE",
            **self._evidence(),
        }

    def operation_item(self) -> dict[str, object]:
        return {
            "provenance_key": f"OPERATION#{self.operation_id}",
            "record_type": "BACKUP_OPERATION_UNIQUENESS",
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "operation_id": self.operation_id,
        }

    def _evidence(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "operation_id": self.operation_id,
            "game_id": self.game_id,
            "source_volume_id": self.source_volume_id,
            "stage": self.stage,
            "project": self.project,
            "category": self.category,
            "protected": self.protected,
            "operation_requested_at": utc_timestamp(self.operation_requested_at),
            "wishicraft_created_at": utc_timestamp(self.wishicraft_created_at),
            "snapshot_start_time": utc_timestamp(self.snapshot_start_time),
            "provenance_recorded_at": utc_timestamp(self.provenance_recorded_at),
            "verified_owner_id": self.verified_owner_id,
            "metadata": self.metadata,
            "metadata_fingerprint": self.metadata_fingerprint,
            "verification_status": "VERIFIED_BACKUP_SUCCEEDED",
        }


@dataclass(frozen=True)
class BackupOperationEvidence:
    operation_id: str
    operation_type: str
    status: str
    requested_at: datetime
    result: dict[str, object]


def build_verified_provenance(
    *,
    snapshot: SnapshotRecord,
    operation: BackupOperationEvidence,
    project: str,
    stage: str,
    game_id: str,
    source_volume_id: str,
    owner_id: str,
    provenance_recorded_at: datetime,
    require_succeeded_operation: bool = True,
) -> BackupProvenanceRecord:
    tags = snapshot.tags
    operation_id = operation.operation_id
    expected_result = {
        "kind": "BACKUP",
        "backup_id": operation_id.replace("op-", "backup-", 1),
        "snapshot_id": snapshot.snapshot_id,
        "source_volume_id": source_volume_id,
        "game_id": game_id,
        "category": "backup",
    }
    expected_tags = {
        "Project": project,
        "Stage": stage,
        "WishicraftCategory": "backup",
        "WishicraftGameId": game_id,
        "WishicraftOperationId": operation_id,
        "WishicraftSourceVolumeId": source_volume_id,
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
    }
    operation_valid = (
        operation.status == "SUCCEEDED" and operation.result == expected_result
        if require_succeeded_operation
        else operation.status in {"PENDING", "RUNNING"}
    )
    try:
        wishicraft_created_at = _parse_rfc3339(tags.get("WishicraftCreatedAt", ""))
    except ValueError as error:
        raise ValueError("Backup provenance evidence is incomplete or inconsistent") from error
    result_snapshot_mismatch = require_succeeded_operation and (
        snapshot.snapshot_id != str(operation.result.get("snapshot_id"))
    )
    if (
        operation.operation_type != "BACKUP"
        or not operation_valid
        or snapshot.state != "completed"
        or snapshot.owner_id != owner_id
        or snapshot.source_volume_id != source_volume_id
        or snapshot.start_time is None
        or snapshot.storage_tier != "standard"
        or snapshot.description != f"Wishicraft backup {operation_id}"
        or set(tags) != REQUIRED_TAG_KEYS
        or any(tags.get(key) != value for key, value in expected_tags.items())
        or result_snapshot_mismatch
    ):
        raise ValueError("Backup provenance evidence is incomplete or inconsistent")
    return BackupProvenanceRecord(
        snapshot_id=snapshot.snapshot_id,
        operation_id=operation_id,
        game_id=game_id,
        source_volume_id=source_volume_id,
        stage=stage,
        project=project,
        category="backup",
        protected=False,
        snapshot_start_time=snapshot.start_time,
        operation_requested_at=operation.requested_at,
        wishicraft_created_at=wishicraft_created_at,
        provenance_recorded_at=provenance_recorded_at,
        verified_owner_id=owner_id,
        metadata=tags,
    )


class BackupProvenanceRepository:
    def __init__(self, api: DynamoProvenanceApi, *, table_name: str) -> None:
        self._api = api
        self._table = table_name

    def transactional_puts(self, record: BackupProvenanceRecord) -> tuple[dict[str, object], ...]:
        return (
            self._put(record.snapshot_item()),
            self._put(record.operation_item()),
        )

    def register(self, record: BackupProvenanceRecord) -> bool:
        """Conditionally create both uniqueness records; exact replay is a no-op."""
        if not self.assert_createable_or_exact(record):
            return False
        try:
            self._api.transact_write_items(TransactItems=list(self.transactional_puts(record)))
        except Exception:
            if self.exact_match(record):
                return False
            raise
        return True

    def exact_match(self, record: BackupProvenanceRecord) -> bool:
        snapshot = self._load(f"SNAPSHOT#{record.snapshot_id}")
        return (
            _same_evidence(snapshot, record.snapshot_item())
            and self._load(f"OPERATION#{record.operation_id}") == record.operation_item()
        )

    def existing_recorded_at(self, snapshot_id: str, operation_id: str) -> datetime | None:
        """Recover a fixed audit timestamp only from a complete matching pair."""
        snapshot = self._load(f"SNAPSHOT#{snapshot_id}")
        operation = self._load(f"OPERATION#{operation_id}")
        if snapshot is None and operation is None:
            return None
        if snapshot is None or operation is None:
            raise ValueError("conflicting or partial Backup provenance")
        if (
            snapshot.get("snapshot_id") != snapshot_id
            or snapshot.get("operation_id") != operation_id
            or operation.get("snapshot_id") != snapshot_id
            or operation.get("operation_id") != operation_id
        ):
            raise ValueError("conflicting or partial Backup provenance")
        value = snapshot.get("provenance_recorded_at")
        if not isinstance(value, str):
            raise ValueError("malformed Backup provenance timestamp")
        return _parse_rfc3339(value)

    def assert_createable_or_exact(self, record: BackupProvenanceRecord) -> bool:
        snapshot = self._load(f"SNAPSHOT#{record.snapshot_id}")
        operation = self._load(f"OPERATION#{record.operation_id}")
        if snapshot is None and operation is None:
            return True
        if (
            _same_evidence(snapshot, record.snapshot_item())
            and operation == record.operation_item()
        ):
            return False
        raise ValueError("conflicting or partial Backup provenance")

    def _put(self, item: dict[str, object]) -> dict[str, object]:
        return {
            "Put": {
                "TableName": self._table,
                "Item": _attribute_map(item),
                "ConditionExpression": "attribute_not_exists(provenance_key)",
            }
        }

    def _load(self, key: str) -> dict[str, object] | None:
        response = self._api.get_item(
            TableName=self._table,
            Key={"provenance_key": {"S": key}},
            ConsistentRead=True,
        )
        if not isinstance(response, dict):
            raise ValueError("malformed Backup provenance response")
        raw = response.get("Item")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("malformed Backup provenance item")
        return _decode_map(raw)


def _metadata_fingerprint(metadata: dict[str, str]) -> str:
    canonical = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _parse_rfc3339(value: str) -> datetime:
    if (
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
            value,
        )
        is None
    ):
        raise ValueError("invalid provenance timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ValueError("invalid provenance timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid provenance timestamp")
    return parsed


def _same_evidence(actual: dict[str, object] | None, expected: dict[str, object]) -> bool:
    if actual is None:
        return False
    return {key: value for key, value in actual.items() if key != "provenance_recorded_at"} == {
        key: value for key, value in expected.items() if key != "provenance_recorded_at"
    }


def _attribute(value: object) -> dict[str, object]:
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": _attribute_map(value)}
    raise TypeError("unsupported Backup provenance value")


def _attribute_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _attribute(item) for key, item in value.items()}


def _decode(value: object) -> object:
    if not isinstance(value, dict):
        raise ValueError("malformed DynamoDB attribute")
    if isinstance(value.get("S"), str):
        return value["S"]
    if isinstance(value.get("N"), str):
        return int(value["N"])
    if isinstance(value.get("BOOL"), bool):
        return value["BOOL"]
    if isinstance(value.get("M"), dict):
        return _decode_map(value["M"])
    raise ValueError("unsupported DynamoDB attribute")


def _decode_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _decode(item) for key, item in value.items()}
