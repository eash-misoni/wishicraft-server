"""Fail-closed repository contracts for independent snapshot retention."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from wishicraft.backup import REQUIRED_TAG_KEYS


class SnapshotDisposition(StrEnum):
    KEEP = "KEEP"
    CANDIDATE = "CANDIDATE"
    EXCLUDED = "EXCLUDED"
    ANOMALY = "ANOMALY"


class RetentionRunStatus(StrEnum):
    DRY_RUN = "DRY_RUN"
    NO_DELETE = "NO_DELETE"


class RecycleBinState(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACTIVE_DELETED = "ACTIVE_DELETED"
    RECYCLE_BIN_RETAINED = "RECYCLE_BIN_RETAINED"
    FULLY_PURGED_OR_NOT_RETAINED = "FULLY_PURGED_OR_NOT_RETAINED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class DeleteRequestOutcome(StrEnum):
    EXPLICIT_SUCCESS = "EXPLICIT_SUCCESS"
    EXPLICIT_ACCESS_DENIED = "EXPLICIT_ACCESS_DENIED"
    NOT_FOUND_BEFORE_REQUEST = "NOT_FOUND_BEFORE_REQUEST"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class DeleteReconciliation(StrEnum):
    ACTIVE_ABSENT = "ACTIVE_ABSENT"
    STILL_PRESENT_RETRY_ELIGIBLE = "STILL_PRESENT_RETRY_ELIGIBLE"
    STILL_PRESENT_STOPPED = "STILL_PRESENT_STOPPED"
    FAILED = "FAILED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass(frozen=True)
class RetentionContext:
    project: str
    stage: str
    game_id: str
    source_volume_id: str
    owner_id: str
    keep_count: int = 7

    def __post_init__(self) -> None:
        if self.keep_count != 7:
            raise ValueError("D-090 retention count must remain seven")
        if not all((self.project, self.stage, self.game_id, self.source_volume_id, self.owner_id)):
            raise ValueError("retention context identity must be complete")


@dataclass(frozen=True)
class InventorySnapshot:
    snapshot_id: str
    source_volume_id: str
    state: str
    owner_id: str
    start_time: datetime
    description: str
    tags: dict[str, str]
    storage_tier: str = "standard"
    lock_state: str | None = None


@dataclass(frozen=True)
class BackupProvenance:
    """Non-TTL retention ownership proof, independent of expiring Operations."""

    snapshot_id: str
    operation_id: str
    game_id: str
    stage: str
    source_volume_id: str
    operation_requested_at: datetime
    wishicraft_created_at: datetime
    snapshot_start_time: datetime
    provenance_recorded_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported backup provenance schema")
        _aware_utc(self.operation_requested_at)
        _aware_utc(self.wishicraft_created_at)
        _aware_utc(self.snapshot_start_time)
        _aware_utc(self.provenance_recorded_at)


@dataclass(frozen=True)
class ClassifiedSnapshot:
    snapshot: InventorySnapshot
    disposition: SnapshotDisposition
    reason: str


@dataclass(frozen=True)
class RetentionPlan:
    status: RetentionRunStatus
    inventory_count: int
    keep_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    anomaly_ids: tuple[str, ...]
    planned_delete_ids: tuple[str, ...]
    reason: str


class SnapshotInventoryApi(Protocol):
    def describe_snapshots(self, **kwargs: object) -> object: ...


class SnapshotLockApi(Protocol):
    def describe_locked_snapshots(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class RecycleBinRule:
    identifier: str
    retention_days: int
    lock_state: str
    resource_tags: dict[str, str]
    exclusion_tags: dict[str, str]

    def matches(self, tags: dict[str, str]) -> bool:
        if self.resource_tags and not all(tags.get(k) == v for k, v in self.resource_tags.items()):
            return False
        return not any(tags.get(k) == v for k, v in self.exclusion_tags.items())


class SnapshotDeleteAdapter(Protocol):
    """Future adapter: configured with one SDK attempt; no AWS implementation in this slice."""

    def delete_once(self, *, snapshot_id: str) -> DeleteRequestOutcome: ...


@dataclass
class FakeSnapshotDeleteAdapter:
    outcome: DeleteRequestOutcome
    calls: list[str]

    def delete_once(self, *, snapshot_id: str) -> DeleteRequestOutcome:
        self.calls.append(snapshot_id)
        return self.outcome


def load_complete_inventory(api: SnapshotInventoryApi, *, owner_id: str) -> list[InventorySnapshot]:
    """Load every page or fail; a partial inventory must never drive deletion."""
    token: str | None = None
    seen_tokens: set[str] = set()
    records: list[InventorySnapshot] = []
    while True:
        request: dict[str, object] = {"OwnerIds": [owner_id], "MaxResults": 1000}
        if token is not None:
            request["NextToken"] = token
        response = api.describe_snapshots(**request)
        if not isinstance(response, dict) or not isinstance(response.get("Snapshots"), list):
            raise ValueError("incomplete snapshot inventory")
        records.extend(_parse_inventory_snapshot(item) for item in response["Snapshots"])
        raw_token = response.get("NextToken")
        if raw_token is None:
            return records
        if not isinstance(raw_token, str) or not raw_token or raw_token in seen_tokens:
            raise ValueError("invalid snapshot pagination")
        seen_tokens.add(raw_token)
        token = raw_token


def load_complete_snapshot_locks(api: SnapshotLockApi) -> dict[str, str]:
    token: str | None = None
    seen: set[str] = set()
    result: dict[str, str] = {}
    while True:
        request: dict[str, object] = {"MaxResults": 1000}
        if token is not None:
            request["NextToken"] = token
        raw_response = api.describe_locked_snapshots(**request)
        response = raw_response if isinstance(raw_response, dict) else {}
        entries = response.get("Snapshots")
        if not isinstance(entries, list):
            raise ValueError("incomplete snapshot lock inventory")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("malformed snapshot lock")
            snapshot_id = entry.get("SnapshotId")
            lock_state = entry.get("LockState")
            if not isinstance(snapshot_id, str) or not isinstance(lock_state, str):
                raise ValueError("malformed snapshot lock")
            if snapshot_id in result:
                raise ValueError("duplicate snapshot lock")
            result[snapshot_id] = lock_state
        raw_token = response.get("NextToken")
        if raw_token is None:
            return result
        if not isinstance(raw_token, str) or not raw_token or raw_token in seen:
            raise ValueError("invalid snapshot lock pagination")
        seen.add(raw_token)
        token = raw_token


def with_lock_states(
    snapshots: list[InventorySnapshot], lock_states: dict[str, str]
) -> list[InventorySnapshot]:
    return [
        InventorySnapshot(
            **{
                **item.__dict__,
                "lock_state": lock_states.get(item.snapshot_id),
            }
        )
        for item in snapshots
    ]


def classify_inventory(
    snapshots: list[InventorySnapshot],
    provenances: dict[str, BackupProvenance],
    *,
    context: RetentionContext,
) -> list[ClassifiedSnapshot]:
    return [_classify(item, provenances.get(item.snapshot_id), context) for item in snapshots]


def plan_retention(
    snapshots: list[InventorySnapshot],
    provenances: dict[str, BackupProvenance],
    *,
    context: RetentionContext,
    recycle_bin_preflight_complete: bool,
) -> RetentionPlan:
    classified = classify_inventory(snapshots, provenances, context=context)
    excluded = tuple(x.snapshot.snapshot_id for x in classified if x.disposition == "EXCLUDED")
    anomalies = tuple(x.snapshot.snapshot_id for x in classified if x.disposition == "ANOMALY")
    eligible = [x.snapshot for x in classified if x.disposition == "KEEP"]
    if not recycle_bin_preflight_complete or anomalies:
        return RetentionPlan(
            RetentionRunStatus.NO_DELETE,
            len(snapshots),
            tuple(x.snapshot_id for x in eligible),
            (),
            excluded,
            anomalies,
            (),
            "recycle-bin-unknown" if not recycle_bin_preflight_complete else "inventory-anomaly",
        )
    operation_ids = [x.tags["WishicraftOperationId"] for x in eligible]
    if len(operation_ids) != len(set(operation_ids)):
        anomaly_ids = tuple(x.snapshot_id for x in eligible)
        return RetentionPlan(
            RetentionRunStatus.NO_DELETE,
            len(snapshots),
            (),
            (),
            excluded,
            anomaly_ids,
            (),
            "duplicate-operation-provenance",
        )
    eligible.sort(key=lambda x: _aware_utc(x.start_time), reverse=True)
    if len(eligible) > context.keep_count and (
        _aware_utc(eligible[context.keep_count - 1].start_time)
        == _aware_utc(eligible[context.keep_count].start_time)
    ):
        return RetentionPlan(
            RetentionRunStatus.NO_DELETE,
            len(snapshots),
            tuple(x.snapshot_id for x in eligible),
            (),
            excluded,
            (),
            (),
            "keep-delete-boundary-tie",
        )
    keep = tuple(x.snapshot_id for x in eligible[: context.keep_count])
    candidates = tuple(x.snapshot_id for x in eligible[context.keep_count :])
    # Initial release caps the blast radius at one, oldest unambiguous candidate.
    planned = candidates[-1:] if candidates else ()
    return RetentionPlan(
        RetentionRunStatus.DRY_RUN,
        len(snapshots),
        keep,
        candidates,
        excluded,
        (),
        planned,
        "planned" if planned else "within-retention-limit",
    )


def reconcile_delete_outcome(
    request_outcome: DeleteRequestOutcome,
    *,
    exists_after_request: bool | None,
    lock_owned: bool,
    predicate_still_valid: bool,
    membership_still_valid: bool,
    retry_count: int,
) -> DeleteReconciliation:
    if request_outcome in {
        DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED,
        DeleteRequestOutcome.NOT_FOUND_BEFORE_REQUEST,
    }:
        return DeleteReconciliation.FAILED
    if exists_after_request is False:
        return DeleteReconciliation.ACTIVE_ABSENT
    if exists_after_request is None:
        return DeleteReconciliation.OUTCOME_UNKNOWN
    if (
        request_outcome == DeleteRequestOutcome.OUTCOME_UNKNOWN
        and retry_count == 0
        and lock_owned
        and predicate_still_valid
        and membership_still_valid
    ):
        return DeleteReconciliation.STILL_PRESENT_RETRY_ELIGIBLE
    return DeleteReconciliation.STILL_PRESENT_STOPPED


def _classify(
    item: InventorySnapshot,
    provenance: BackupProvenance | None,
    context: RetentionContext,
) -> ClassifiedSnapshot:
    tags = item.tags
    wishicraft_claim = any(key in tags for key in REQUIRED_TAG_KEYS)
    if not wishicraft_claim:
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "unclaimed-manual")
    category = tags.get("WishicraftCategory")
    protected = tags.get("WishicraftProtected")
    if category == "migration":
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "migration")
    if protected == "true":
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "protected")
    if category != "backup":
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "other-category")
    if tags.get("Project") != context.project or tags.get("Stage") != context.stage:
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "other-project-or-stage")
    if tags.get("WishicraftGameId") != context.game_id:
        return ClassifiedSnapshot(item, SnapshotDisposition.EXCLUDED, "other-game")
    expected = {
        "Project": context.project,
        "Stage": context.stage,
        "WishicraftCategory": "backup",
        "WishicraftGameId": context.game_id,
        "WishicraftSourceVolumeId": context.source_volume_id,
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
    }
    if set(tags) != REQUIRED_TAG_KEYS or any(tags.get(k) != v for k, v in expected.items()):
        return ClassifiedSnapshot(item, SnapshotDisposition.ANOMALY, "invalid-d090-metadata")
    operation_id = tags.get("WishicraftOperationId", "")
    try:
        created_at = parse_rfc3339(tags.get("WishicraftCreatedAt", ""))
    except ValueError:
        return ClassifiedSnapshot(item, SnapshotDisposition.ANOMALY, "invalid-created-at")
    if (
        item.owner_id != context.owner_id
        or item.source_volume_id != context.source_volume_id
        or item.state != "completed"
        or item.description != f"Wishicraft backup {operation_id}"
        or item.storage_tier != "standard"
        or item.lock_state in {"governance", "compliance-cooloff", "compliance"}
    ):
        return ClassifiedSnapshot(item, SnapshotDisposition.ANOMALY, "aws-attribute-mismatch")
    if provenance is None:
        return ClassifiedSnapshot(item, SnapshotDisposition.ANOMALY, "missing-durable-provenance")
    if (
        provenance.snapshot_id != item.snapshot_id
        or provenance.operation_id != operation_id
        or provenance.game_id != context.game_id
        or provenance.stage != context.stage
        or provenance.source_volume_id != context.source_volume_id
        or provenance.schema_version != 1
        or _aware_utc(provenance.wishicraft_created_at) != created_at
        or _aware_utc(provenance.snapshot_start_time) != _aware_utc(item.start_time)
    ):
        return ClassifiedSnapshot(item, SnapshotDisposition.ANOMALY, "provenance-mismatch")
    return ClassifiedSnapshot(item, SnapshotDisposition.KEEP, "retention-owned")


def parse_rfc3339(value: str) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        )
        is None
    ):
        raise ValueError("invalid RFC3339 timestamp")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return _aware_utc(parsed)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _parse_inventory_snapshot(value: object) -> InventorySnapshot:
    if not isinstance(value, dict):
        raise ValueError("invalid snapshot inventory record")
    tags: dict[str, str] = {}
    raw_tags = value.get("Tags", [])
    if not isinstance(raw_tags, list):
        raise ValueError("invalid snapshot tags")
    for tag in raw_tags:
        if (
            not isinstance(tag, dict)
            or not isinstance(tag.get("Key"), str)
            or not isinstance(tag.get("Value"), str)
        ):
            raise ValueError("invalid snapshot tag")
        key = cast(str, tag["Key"])
        if key in tags:
            raise ValueError("duplicate snapshot tag")
        tags[key] = cast(str, tag["Value"])
    fields = (
        value.get("SnapshotId"),
        value.get("VolumeId"),
        value.get("State"),
        value.get("OwnerId"),
        value.get("Description"),
    )
    if (
        not all(isinstance(field, str) for field in fields)
        or not isinstance(value.get("StartTime"), datetime)
        or not isinstance(value.get("StorageTier", "standard"), str)
    ):
        raise ValueError("incomplete snapshot inventory record")
    return InventorySnapshot(
        cast(str, fields[0]),
        cast(str, fields[1]),
        cast(str, fields[2]),
        cast(str, fields[3]),
        _aware_utc(cast(datetime, value["StartTime"])),
        cast(str, fields[4]),
        tags,
        cast(str, value.get("StorageTier", "standard")),
    )
