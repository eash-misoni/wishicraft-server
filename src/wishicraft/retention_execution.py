"""Future DELETE_ONE core: formal lease + fresh predicate + durable request + reconciliation.

Not wired to an AWS adapter, event flag, CLI or deployed runtime. DRY_RUN stays the
only deployed mode. Injection is a Python integration seam, not caller authorization.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from wishicraft.operation import LeaseProof
from wishicraft.retention import (
    DeleteReconciliation,
    DeleteRequestOutcome,
    SnapshotDeleteAdapter,
    parse_rfc3339,
    reconcile_delete_outcome,
)
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord
from wishicraft.retention_execution_inventory import FreshInventory


class ExecutionMode(StrEnum):
    DRY_RUN = "DRY_RUN"
    DELETE_ONE = "DELETE_ONE"


@dataclass(frozen=True)
class ExecutionPlan:
    snapshot_id: str | None
    predicate_id: str
    evaluated_at: datetime
    inventory: FreshInventory


@dataclass(frozen=True)
class DeleteObservation:
    snapshot_id: str
    account: str
    region: str
    observed_at: datetime
    active: bool | None
    in_recycle_bin: bool | None


class Reads(Protocol):
    def inventory(self) -> FreshInventory: ...
    def observe(self, snapshot_id: str) -> DeleteObservation: ...


class Leases(Protocol):
    def verify_owned(self, proof: LeaseProof, *, now: datetime) -> None: ...


class Journal(Protocol):
    def read_operation(self, operation_id: str) -> DeletionRecord | None: ...
    def claim(self, record: DeletionRecord, proof: LeaseProof, now: datetime) -> bool: ...
    def save(
        self, before: DeletionRecord, after: DeletionRecord, proof: LeaseProof, now: datetime
    ) -> None: ...


class RetentionExecution:
    def __init__(
        self,
        *,
        reads: Reads,
        leases: Leases,
        journal: Journal,
        clock: Callable[[], datetime],
        adapter: SnapshotDeleteAdapter | None = None,
        dispatcher: tuple[str, str, str, int] | None = None,
    ) -> None:
        self.reads, self.leases, self.journal = reads, leases, journal
        self.clock, self.adapter = clock, adapter
        self.dispatcher = dispatcher

    def prepare(self, proof: LeaseProof) -> ExecutionPlan:
        self.leases.verify_owned(proof, now=self.clock())
        inventory = self.reads.inventory()
        now = self.clock()
        predicate = inventory.identity(now)
        if inventory.system_id != proof.resource_id:
            raise ValueError("RETENTION_SCOPE_MISMATCH")
        policy = inventory.policy(now)
        if policy.status == "NO_DELETE":
            raise ValueError("RETENTION_POLICY_UNKNOWN")
        candidates = sorted(
            (s for s in inventory.snapshots if s.snapshot_id in policy.candidate_ids),
            key=lambda s: s.start_time,
        )
        if len(candidates) > 1 and candidates[0].start_time == candidates[1].start_time:
            raise ValueError("OLDEST_CANDIDATE_AMBIGUOUS")
        return ExecutionPlan(
            candidates[0].snapshot_id if candidates else None, predicate, now, inventory
        )

    def _fresh(self, plan: ExecutionPlan, proof: LeaseProof) -> None:
        # Do not begin an SDK attempt at the edge of lease expiry. The durable pending
        # bit also blocks automatic release/recovery if this worker pauses after checking.
        self.leases.verify_owned(proof, now=self.clock() + timedelta(seconds=60))
        if not timedelta(0) <= self.clock() - plan.evaluated_at <= timedelta(seconds=120):
            raise ValueError("STALE_RETENTION_PLAN")
        current = self.prepare(proof)
        if current.snapshot_id != plan.snapshot_id or current.predicate_id != plan.predicate_id:
            raise ValueError("RETENTION_MEMBERSHIP_CHANGED")
        self.leases.verify_owned(proof, now=self.clock() + timedelta(seconds=60))

    def execute(
        self,
        plan: ExecutionPlan,
        proof: LeaseProof,
        *,
        actor: str = "ADMIN",
        mode: ExecutionMode = ExecutionMode.DRY_RUN,
    ) -> DeletionRecord | None:
        if mode != ExecutionMode.DELETE_ONE or self.adapter is None:
            return None
        existing = self.journal.read_operation(proof.owner_operation_id)
        if existing is not None:
            if (
                existing.snapshot_id != plan.snapshot_id
                or existing.predicate_id != plan.predicate_id
            ):
                raise ValueError("DELETION_IDEMPOTENCY_CONFLICT")
            return existing  # DISPATCHED means reconcile, never another DeleteSnapshot.
        self._fresh(plan, proof)
        if plan.snapshot_id is None:
            return None  # zero candidates is normal, no claim and no request
        p = plan.inventory.proofs[plan.snapshot_id]
        if p.recovery_digest is None:
            raise ValueError("SHARED_PROVENANCE_REQUIRED")
        c = plan.inventory.context
        record = DeletionRecord(
            c.owner_id,
            plan.inventory.region,
            proof.resource_id,
            c.stage,
            c.source_volume_id,
            plan.snapshot_id,
            p.operation_id,
            proof.owner_operation_id,
            p.snapshot_start_time.isoformat(),
            p.recovery_digest,
            plan.predicate_id,
            self.clock().isoformat(),
            actor,
            execution_arn=self.dispatcher[0] if self.dispatcher else None,
            dispatcher_arn=self.dispatcher[1] if self.dispatcher else None,
            dispatcher_revision=self.dispatcher[2] if self.dispatcher else None,
            dispatcher_timeout=self.dispatcher[3] if self.dispatcher else None,
            dispatcher_lease_id=proof.lease_id if self.dispatcher else None,
        )
        if not self.journal.claim(record, proof, self.clock()):
            return self.journal.read_operation(proof.owner_operation_id)
        return self._dispatch(record, plan, proof)

    def _dispatch(
        self, record: DeletionRecord, plan: ExecutionPlan, proof: LeaseProof
    ) -> DeletionRecord:
        assert self.adapter is not None
        # Fresh read after reservation closes stale-plan input. The non-expiring lock
        # excludes formal reference writers; it is NOT the pair of reads that fences them.
        try:
            self._fresh(plan, proof)
        except Exception:
            after = record.advance(
                phase=DeletionPhase.RECONCILIATION_REQUIRED,
                reconciliation="FRESH_VALIDATION_FAILED",
            )
            self.journal.save(record, after, proof, self.clock())
            return after
        try:
            outcome = self.adapter.delete_once(snapshot_id=record.snapshot_id)
            if not isinstance(outcome, DeleteRequestOutcome):
                outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN
        except Exception:
            outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN
        # Persist the response before any retry or reconciliation. CAS failure cannot
        # dispatch again and the reservation remains. No exception detail is persisted.
        terminal = record.attempt == 1 and outcome in {
            DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED,
            DeleteRequestOutcome.NOT_FOUND_BEFORE_REQUEST,
        }
        after = record.advance(
            phase=DeletionPhase.NO_MUTATION if terminal else DeletionPhase.RESPONSE_RECORDED,
            request_outcome=outcome.value,
            reconciliation=(
                "ACCESS_DENIED"
                if outcome == DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED
                else "NOT_FOUND_BEFORE_REQUEST"
                if outcome == DeleteRequestOutcome.NOT_FOUND_BEFORE_REQUEST
                else "OUTCOME_UNKNOWN"
            ),
        )
        self.journal.save(record, after, proof, self.clock())
        return after

    def reconcile(self, proof: LeaseProof) -> DeletionRecord | None:
        before = self.journal.read_operation(proof.owner_operation_id)
        if before is None or before.phase in {
            DeletionPhase.FORMALLY_DELETED,
            DeletionPhase.NO_MUTATION,
            DeletionPhase.DISPATCHED,
            DeletionPhase.RECONCILIATION_REQUIRED,
        }:
            # A crashed dispatcher with no recorded response is NOT known to have
            # stopped sending. Requires future operator reconciliation, not auto-unlock.
            return before
        self.leases.verify_owned(proof, now=self.clock())
        try:
            obs = self.reads.observe(before.snapshot_id)
            now = self.clock()
            if (
                obs.snapshot_id != before.snapshot_id
                or obs.account != before.account
                or obs.region != before.region
                or obs.observed_at <= parse_rfc3339(before.requested_at)
                or not timedelta(0) <= now - obs.observed_at <= timedelta(seconds=30)
                or (
                    before.last_observed_at is not None
                    and obs.observed_at <= parse_rfc3339(before.last_observed_at)
                )
                or type(obs.active) is not bool
                or type(obs.in_recycle_bin) is not bool
                or (obs.active and obs.in_recycle_bin)
            ):
                raise ValueError("INVALID_DELETE_OBSERVATION")
        except Exception:
            return before  # no heartbeat/success fabrication and no reservation removal
        outcome = DeleteRequestOutcome(before.request_outcome)
        result = reconcile_delete_outcome(
            outcome,
            exists_after_request=obs.active,
            lock_owned=True,
            predicate_still_valid=False,
            membership_still_valid=False,
            retry_count=before.attempt - 1,
        )
        confirmed = (
            result == DeleteReconciliation.ACTIVE_ABSENT
            and outcome == DeleteRequestOutcome.EXPLICIT_SUCCESS
            and before.first_absent_at is not None
            and obs.observed_at - parse_rfc3339(before.first_absent_at) >= timedelta(seconds=10)
        )
        after = before.advance(
            phase=DeletionPhase.FORMALLY_DELETED if confirmed else DeletionPhase.RESPONSE_RECORDED,
            reconciliation=(
                "STILL_PRESENT"
                if obs.active
                else "RECYCLE_BIN_RETAINED"
                if obs.in_recycle_bin
                else "ACTIVE_ABSENT"
            ),
            first_absent_at=(
                None if obs.active else before.first_absent_at or obs.observed_at.isoformat()
            ),
            last_observed_at=obs.observed_at.isoformat(),
            confirmed_at=obs.observed_at.isoformat() if confirmed else None,
        )
        self.journal.save(before, after, proof, now)
        return after

    def retry(self, plan: ExecutionPlan, proof: LeaseProof) -> DeletionRecord:
        """One same-target retry after >=30s, only after a recorded unknown response.

        No Step Functions Retry binding is added. The future orchestrator must opt in
        after reconciliation; an interrupted DISPATCHED state cannot use this method.
        """
        before = self.journal.read_operation(proof.owner_operation_id)
        if (
            self.adapter is None
            or before is None
            or before.attempt != 1
            or before.phase != DeletionPhase.RESPONSE_RECORDED
            or before.request_outcome != DeleteRequestOutcome.OUTCOME_UNKNOWN
            or before.reconciliation != "STILL_PRESENT"
            or before.last_observed_at is None
            or self.clock() - parse_rfc3339(before.last_observed_at) > timedelta(seconds=30)
            or self.clock() - parse_rfc3339(before.requested_at) < timedelta(seconds=30)
            or before.snapshot_id != plan.snapshot_id
            or before.predicate_id != plan.predicate_id
        ):
            raise ValueError("DELETE_RETRY_NOT_ELIGIBLE")
        self._fresh(plan, proof)
        after = before.advance(
            phase=DeletionPhase.DISPATCHED,
            attempt=2,
            request_outcome="NOT_RECORDED",
            reconciliation="OUTCOME_UNKNOWN",
            first_absent_at=None,
            last_observed_at=None,
        )
        self.journal.save(before, after, proof, self.clock())
        return self._dispatch(after, plan, proof)
