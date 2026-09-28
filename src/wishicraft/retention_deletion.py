"""Non-TTL deletion journal, separate from immutable BACKUP provenance.

No EC2 mutation adapter. Records contain public identities/enums only. A DISPATCHED
record is deliberately not permission to replay a request after worker interruption.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from wishicraft.retention import BackupProvenance, DeleteRequestOutcome, parse_rfc3339
from wishicraft.retention_daily import POLICY


class DeletionPhase(StrEnum):
    DISPATCHED = "DISPATCHED"
    RESPONSE_RECORDED = "RESPONSE_RECORDED"
    FORMALLY_DELETED = "FORMALLY_DELETED"
    NO_MUTATION = "NO_MUTATION"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True)
class DeletionRecord:
    account: str
    region: str
    system_id: str
    stage: str
    source_volume_id: str
    snapshot_id: str
    backup_operation_id: str
    retention_operation_id: str
    acquired_at: str
    recovery_digest: str
    predicate_id: str
    requested_at: str
    actor: str
    phase: DeletionPhase = DeletionPhase.DISPATCHED
    request_outcome: str = "NOT_RECORDED"
    reconciliation: str = "OUTCOME_UNKNOWN"
    confirmed_at: str | None = None
    first_absent_at: str | None = None
    last_observed_at: str | None = None
    attempt: int = 1
    revision: int = 1
    schema_version: int = 1
    policy: str = POLICY

    def __post_init__(self) -> None:
        patterns = {
            "account": r"[0-9]{12}",
            "region": r"[a-z]{2}(?:-[a-z]+)+-[0-9]",
            "system_id": r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}",
            "stage": r"[a-z][a-z0-9-]{0,30}",
            "source_volume_id": r"vol-[0-9a-f]{8,17}",
            "snapshot_id": r"snap-[0-9a-f]{8,17}",
            "backup_operation_id": r"op-[A-Za-z0-9._:-]{1,124}",
            "retention_operation_id": r"op-[A-Za-z0-9._:-]{1,124}",
            "actor": r"(?:ADMIN|CLI)",
            "recovery_digest": r"[0-9a-f]{64}",
            "predicate_id": r"[0-9a-f]{64}",
        }
        if any(
            not isinstance(getattr(self, k), str) or not re.fullmatch(v, getattr(self, k))
            for k, v in patterns.items()
        ):
            raise ValueError("INVALID_DELETION_IDENTITY")
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.policy != POLICY
            or type(self.attempt) is not int
            or self.attempt not in {1, 2}
            or type(self.revision) is not int
            or self.revision < 1
            or not isinstance(self.phase, DeletionPhase)
            or self.request_outcome not in {"NOT_RECORDED", *DeleteRequestOutcome}
            or self.reconciliation
            not in {
                "OUTCOME_UNKNOWN",
                "ACTIVE_ABSENT",
                "RECYCLE_BIN_RETAINED",
                "STILL_PRESENT",
                "ACCESS_DENIED",
                "NOT_FOUND_BEFORE_REQUEST",
                "FRESH_VALIDATION_FAILED",
            }
        ):
            raise ValueError("INVALID_DELETION_STATE")
        acquired, requested = parse_rfc3339(self.acquired_at), parse_rfc3339(self.requested_at)
        if acquired > requested:
            raise ValueError("INVALID_DELETION_TIME")
        if self.confirmed_at is not None and parse_rfc3339(self.confirmed_at) < requested:
            raise ValueError("INVALID_DELETION_TIME")
        for value in (self.first_absent_at, self.last_observed_at):
            if value is not None and parse_rfc3339(value) < requested:
                raise ValueError("INVALID_OBSERVATION_TIME")
        if self.phase == DeletionPhase.FORMALLY_DELETED and (
            self.request_outcome != DeleteRequestOutcome.EXPLICIT_SUCCESS
            or self.reconciliation not in {"ACTIVE_ABSENT", "RECYCLE_BIN_RETAINED"}
            or self.confirmed_at is None
            or self.first_absent_at is None
            or self.last_observed_at != self.confirmed_at
            or (
                parse_rfc3339(self.confirmed_at) - parse_rfc3339(self.first_absent_at)
            ).total_seconds()
            < 10
        ):
            raise ValueError("UNCONFIRMED_DELETION")
        if self.phase == DeletionPhase.NO_MUTATION and (
            self.attempt != 1
            or self.request_outcome
            not in {
                DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED,
                DeleteRequestOutcome.NOT_FOUND_BEFORE_REQUEST,
            }
        ):
            raise ValueError("UNCONFIRMED_NO_MUTATION")

    def item(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "phase": self.phase.value,
            "provenance_key": "DELETION#" + self.snapshot_id,
            "record_type": "RETENTION_DELETION",
        }

    def advance(self, **changes: Any) -> DeletionRecord:
        allowed = {
            "phase",
            "request_outcome",
            "reconciliation",
            "confirmed_at",
            "attempt",
            "first_absent_at",
            "last_observed_at",
        }
        if set(changes) - allowed or self.phase in {
            DeletionPhase.FORMALLY_DELETED,
            DeletionPhase.NO_MUTATION,
        }:
            raise ValueError("DELETION_TRANSITION_CONFLICT")
        return replace(self, revision=self.revision + 1, **changes)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> DeletionRecord:
        try:
            fields = {k: v for k, v in value.items() if k not in {"record_type", "provenance_key"}}
            for key in ("schema_version", "attempt", "revision"):
                value_at_key = fields.get(key)
                if (
                    isinstance(value_at_key, Decimal)
                    and value_at_key.is_finite()
                    and value_at_key == value_at_key.to_integral_value()
                ):
                    fields[key] = int(value_at_key)
            fields["phase"] = DeletionPhase(fields["phase"])
            result = cls(**fields)
            if result.item() != value:
                raise ValueError("identity")
            return result
        except (KeyError, TypeError, ValueError):
            raise ValueError("INVALID_DELETION_RECORD") from None


def classify_absence(
    proof: BackupProvenance,
    record: DeletionRecord | None,
    *,
    account: str,
    region: str,
    system_id: str,
    now: datetime,
    referenced: bool,
    present: bool,
) -> str:
    """A valid BACKUP pair is prerequisite; never infer absence from a failed read."""
    if record is None:
        return "PRESENT" if present else "ANOMALY"
    if (
        record.account != account
        or record.region != region
        or record.system_id != system_id
        or record.stage != proof.stage
        or record.snapshot_id != proof.snapshot_id
        or record.source_volume_id != proof.source_volume_id
        or record.backup_operation_id != proof.operation_id
        or parse_rfc3339(record.acquired_at) != proof.snapshot_start_time
        or record.recovery_digest != proof.recovery_digest
        or proof.schema_version != 2
        or parse_rfc3339(record.requested_at) > now
        or (record.confirmed_at is not None and parse_rfc3339(record.confirmed_at) > now)
    ):
        return "ANOMALY"
    if record.phase == DeletionPhase.FORMALLY_DELETED:
        return "FORMALLY_DELETED" if not present and not referenced else "ANOMALY"
    if record.phase == DeletionPhase.NO_MUTATION:
        return "PRESENT" if present else "ANOMALY"
    return "DELETION_OUTCOME_UNKNOWN"


def split_deletion_records(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, DeletionRecord]]:
    """Validate both deletion/RETENTION uniqueness entries; unknown types remain visible."""
    normal = []
    records: dict[str, DeletionRecord] = {}
    reverse: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("record_type") == "RETENTION_DELETION":
            r = DeletionRecord.parse(row)
            if r.snapshot_id in records:
                raise ValueError("DUPLICATE_DELETION_RECORD")
            records[r.snapshot_id] = r
        elif row.get("record_type") == "RETENTION_DELETION_UNIQUENESS":
            op = row.get("retention_operation_id")
            if not isinstance(op, str) or op in reverse:
                raise ValueError("INVALID_DELETION_REVERSE")
            reverse[op] = row
        else:
            normal.append(row)
    for r in records.values():
        if reverse.get(r.retention_operation_id) != {
            "provenance_key": "RETENTION#" + r.retention_operation_id,
            "record_type": "RETENTION_DELETION_UNIQUENESS",
            "retention_operation_id": r.retention_operation_id,
            "snapshot_id": r.snapshot_id,
        }:
            raise ValueError("PARTIAL_DELETION_PAIR")
    if len(reverse) != len(records):
        raise ValueError("ORPHAN_DELETION_REVERSE")
    return normal, records
