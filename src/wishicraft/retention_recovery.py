"""Explicit same-operation reconcile-only recovery; no adapter and no automatic unlock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from wishicraft.operation import LeaseProof
from wishicraft.retention import DeleteRequestOutcome, parse_rfc3339
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord
from wishicraft.retention_execution import DeleteObservation


@dataclass(frozen=True)
class Quiescence:
    execution_arn: str
    status: str
    terminal_at: datetime
    last_task_end: datetime
    observed_at: datetime
    dispatcher_arn: str
    dispatcher_revision: str
    dispatcher_timeout: int
    history_complete: bool
    synchronous: bool
    redrive_count: int
    execution_revision: str

    def verify(self, record: DeletionRecord, now: datetime) -> None:
        if (
            record.execution_arn is None
            or self.execution_arn != record.execution_arn
            or self.dispatcher_arn != record.dispatcher_arn
            or self.dispatcher_revision != record.dispatcher_revision
            or self.dispatcher_timeout != record.dispatcher_timeout
            or self.status not in {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}
            or self.history_complete is not True
            or self.synchronous is not True
            or type(self.redrive_count) is not int
            or self.redrive_count != 0
            or not self.execution_revision
            or not timedelta(0) <= now - self.observed_at <= timedelta(seconds=30)
            or self.last_task_end > self.terminal_at
            or self.last_task_end < parse_rfc3339(record.requested_at)
            # Conservative AWS maximum, not a mutable $LATEST timeout observed later.
            or now - self.terminal_at < timedelta(seconds=900 + 60)
        ):
            raise ValueError("MANUAL_REVIEW_REQUIRED")


@dataclass(frozen=True)
class RecoveryRead:
    record: DeletionRecord
    old_lease: LeaseProof
    pending_snapshot: str
    observation: DeleteObservation
    reference_revision: str
    hold_revision: str
    provenance_matches: bool
    currently_referenced: bool
    references_complete: bool
    quiescence: Quiescence

    def verify(self, now: datetime) -> None:
        self.quiescence.verify(self.record, now)
        r, o = self.record, self.observation
        if (
            now.timestamp() - self.old_lease.lease_expires_at < 960
            or self.old_lease.owner_operation_id != r.retention_operation_id
            or self.old_lease.resource_id != r.system_id
            or self.pending_snapshot != r.snapshot_id
            or r.phase in {DeletionPhase.NO_MUTATION, DeletionPhase.FORMALLY_DELETED}
            or not self.reference_revision
            or not self.hold_revision
            or self.provenance_matches is not True
            or self.currently_referenced is not False
            or self.references_complete is not True
            or (o.snapshot_id, o.account, o.region) != (r.snapshot_id, r.account, r.region)
            or type(o.active) is not bool
            or type(o.in_recycle_bin) is not bool
            or (o.active and o.in_recycle_bin)
            or not timedelta(0) <= now - o.observed_at <= timedelta(seconds=30)
        ):
            raise ValueError("MANUAL_REVIEW_REQUIRED")


class RecoveryRepository(Protocol):
    def resume_reconciliation(
        self,
        before: DeletionRecord,
        after: DeletionRecord,
        old: LeaseProof,
        new: LeaseProof,
        now: datetime,
    ) -> None: ...


def resume(
    first: RecoveryRead,
    fresh: RecoveryRead,
    *,
    new_lease_id: str,
    now: datetime,
    repository: RecoveryRepository,
) -> LeaseProof:
    """Caller must obtain both reads from bound services; not an arbitrary JSON authority.

    Still held pending Lock fences formal reference writers throughout. The new lease is
    for the SAME operation. No request is resent; unknown + absent remains unknown.
    External redrive/deployment/reference writers must be excluded in the recovery window.
    """
    first.verify(now)
    fresh.verify(now)
    if (
        first.record != fresh.record
        or first.old_lease != fresh.old_lease
        or first.quiescence.execution_revision != fresh.quiescence.execution_revision
        or first.reference_revision != fresh.reference_revision
        or first.hold_revision != fresh.hold_revision
        or not new_lease_id
        or new_lease_id == fresh.old_lease.lease_id
    ):
        raise ValueError("RECOVERY_MEMBERSHIP_CHANGED")
    record = fresh.record
    outcome = record.request_outcome
    if outcome == "NOT_RECORDED":
        outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN.value
    after = record.advance(
        phase=DeletionPhase.RESPONSE_RECORDED,
        request_outcome=outcome,
        reconciliation="STILL_PRESENT" if fresh.observation.active else "OUTCOME_UNKNOWN",
        first_absent_at=None,
        last_observed_at=fresh.observation.observed_at.isoformat(),
    )
    proof = LeaseProof(
        record.system_id, record.retention_operation_id, new_lease_id, int(now.timestamp()) + 900
    )
    repository.resume_reconciliation(record, after, fresh.old_lease, proof, now)
    return proof
