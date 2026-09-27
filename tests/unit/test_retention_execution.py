from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.unit.test_retention_daily import CONTEXT_SHARED, NOW, inventory
from wishicraft.operation import LeaseLost, LeaseProof
from wishicraft.retention import DeleteRequestOutcome, FakeSnapshotDeleteAdapter
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord, classify_absence
from wishicraft.retention_execution import (
    DeleteObservation,
    ExecutionMode,
    RetentionExecution,
)
from wishicraft.retention_execution_inventory import FreshInventory

VOLUME = "vol-0123456789abcdef0"
ACCOUNT = "123456789012"
PROOF = LeaseProof("wishicraft-main", "op-retention-test", "lease-test", int(NOW.timestamp()) + 900)
CANARY = "raw-secret-runtime-env-credentials-playerdata"


class Harness:
    def __init__(self, count: int = 12) -> None:
        self.now = NOW
        items, proofs = inventory([timedelta(days=20 + i) for i in range(count)])
        self.inventory_value = FreshInventory(
            replace(CONTEXT_SHARED, source_volume_id=VOLUME, owner_id=ACCOUNT),
            "ap-northeast-1",
            "wishicraft-main",
            NOW,
            tuple(
                replace(
                    s,
                    source_volume_id=VOLUME,
                    owner_id=ACCOUNT,
                    tags={**s.tags, "WishicraftSourceVolumeId": VOLUME},
                )
                for s in items
            ),
            {sid: replace(p, source_volume_id=VOLUME) for sid, p in proofs.items()},
            {},
            "references-1",
            "aws-checks-1",
            (),
        )
        self.record: DeletionRecord | None = None
        self.pending = False
        self.owned = True
        self.observation_active: bool | None = False
        self.observation_bin: bool | None = False
        self.adapter = FakeSnapshotDeleteAdapter(DeleteRequestOutcome.EXPLICIT_SUCCESS, [])
        self.engine = RetentionExecution(
            reads=self, leases=self, journal=self, clock=lambda: self.now, adapter=self.adapter
        )
        self.saved: list[dict[str, Any]] = []
        self.reads = 0
        self.fail_claim = False
        self.claim_response_loss = False
        self.fail_save = False
        self.mutate_after_claim = False

    def inventory(self) -> FreshInventory:
        self.reads += 1
        return replace(deepcopy(self.inventory_value), observed_at=self.now)

    def observe(self, snapshot_id: str) -> DeleteObservation:
        return DeleteObservation(
            snapshot_id,
            ACCOUNT,
            "ap-northeast-1",
            self.now,
            self.observation_active,
            self.observation_bin,
        )

    def verify_owned(self, proof: LeaseProof, *, now: datetime) -> None:
        if not self.owned or proof != PROOF or now.timestamp() > proof.lease_expires_at:
            raise LeaseLost("LOCK_LOST")

    def read_operation(self, operation_id: str) -> DeletionRecord | None:
        assert operation_id == PROOF.owner_operation_id
        return self.record

    def claim(self, record: DeletionRecord, proof: LeaseProof, now: datetime) -> bool:
        self.verify_owned(proof, now=now)
        if self.fail_claim:
            raise ValueError("transaction conflict")
        if self.record:
            return False
        self.record, self.pending = record, True
        self.saved.append(record.item())
        if self.mutate_after_claim:
            self.inventory_value = replace(self.inventory_value, reference_revision="new-journal")
        if self.claim_response_loss:
            raise ValueError("DELETION_CLAIM_UNKNOWN_OR_CONFLICT")
        return True

    def save(
        self, before: DeletionRecord, after: DeletionRecord, proof: LeaseProof, now: datetime
    ) -> None:
        self.verify_owned(proof, now=now)
        if self.fail_save or self.record != before:
            raise ValueError("CAS_CONFLICT")
        self.record = after
        self.saved.append(after.item())
        if after.phase in {DeletionPhase.FORMALLY_DELETED, DeletionPhase.NO_MUTATION}:
            self.pending = False

    def execute(self) -> DeletionRecord | None:
        return self.engine.execute(self.engine.prepare(PROOF), PROOF, mode=ExecutionMode.DELETE_ONE)

    def tick(self, seconds: int = 15) -> None:
        self.now += timedelta(seconds=seconds)


def test_default_disabled_and_formal_handler_cannot_enable_by_event(monkeypatch: Any) -> None:
    h = Harness()
    plan = h.engine.prepare(PROOF)
    assert h.engine.execute(plan, PROOF) is None and not h.saved and not h.adapter.calls
    h.engine.adapter = None
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) is None
    from wishicraft import retention_workflow_lambda as task

    def forbidden() -> None:
        raise AssertionError("must not create AWS clients")

    monkeypatch.setattr(task, "_get_runtime", forbidden)
    result = task.handler(
        dict(
            schema_version=1,
            operation_id="op-x",
            lease_id="lease-x",
            action="run",
            execution_mode="DELETE_ONE",
        ),
        None,
    )
    assert result == dict(
        status="NO_DELETE",
        reason="DELETE_ONE_NOT_RELEASED",
        deletion_authorized=False,
        planned_delete_ids=[],
        delete_action_count=0,
    )


@pytest.mark.parametrize("count", range(8))
def test_zero_through_seven_candidates_are_normal(count: int) -> None:
    h = Harness(count)
    assert h.execute() is None
    assert not h.saved and not h.adapter.calls


@pytest.mark.parametrize("in_bin", [False, True])
def test_one_oldest_only_success_needs_separate_absence_observations(in_bin: bool) -> None:
    h = Harness()
    plan = h.engine.prepare(PROOF)
    result = h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    assert result is not None and result.phase == DeletionPhase.RESPONSE_RECORDED
    assert h.adapter.calls == [h.inventory_value.snapshots[-1].snapshot_id] and h.pending
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) == result
    h.observation_bin = in_bin
    h.tick()
    first = h.engine.reconcile(PROOF)
    assert first is not None and first.phase != DeletionPhase.FORMALLY_DELETED and h.pending
    assert h.engine.reconcile(PROOF) == first  # same observed timestamp cannot be counted twice
    h.tick()
    final = h.engine.reconcile(PROOF)
    assert final is not None and final.phase == DeletionPhase.FORMALLY_DELETED and not h.pending
    assert final.reconciliation == ("RECYCLE_BIN_RETAINED" if in_bin else "ACTIVE_ABSENT")
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) == final
    assert len(h.adapter.calls) == 1


@pytest.mark.parametrize(
    "kind",
    [
        "hold",
        "journal",
        "last-success",
        "new-backup",
        "gone",
        "tags",
        "provenance",
        "aws",
        "lease",
        "stale",
    ],
)
def test_plan_is_not_permission_and_races_stop_before_request(kind: str) -> None:
    h = Harness()
    plan = h.engine.prepare(PROOF)
    old = h.inventory_value
    if kind == "hold":
        h.inventory_value = replace(old, holds={plan.snapshot_id or "": ("hold",)})
    elif kind in {"journal", "last-success"}:
        h.inventory_value = replace(old, reference_revision=kind)
    elif kind == "new-backup":
        h.inventory_value = replace(old, snapshots=old.snapshots[:-2])
    elif kind == "gone":
        h.inventory_value = replace(old, snapshots=old.snapshots[:-1])
    elif kind == "tags":
        s = old.snapshots[-1]
        h.inventory_value = replace(old, snapshots=(*old.snapshots[:-1], replace(s, tags={})))
    elif kind == "provenance":
        ps = deepcopy(old.proofs)
        ps.pop(old.snapshots[-1].snapshot_id)
        h.inventory_value = replace(old, proofs=ps)
    elif kind == "aws":
        h.inventory_value = replace(old, aws_revision="new-sharing")
    elif kind == "lease":
        h.owned = False
    elif kind == "stale":
        h.tick(121)
    with pytest.raises((ValueError, LeaseLost)):
        h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    assert not h.adapter.calls and not h.saved


def test_change_after_reservation_never_dispatches_and_keeps_barrier() -> None:
    h = Harness()
    h.mutate_after_claim = True
    r = h.execute()
    assert r and r.phase == DeletionPhase.RECONCILIATION_REQUIRED
    assert not h.adapter.calls and h.pending


@pytest.mark.parametrize(
    "issue",
    [
        "ami-unknown",
        "sharing-unknown",
        "snapshot-lock-unknown",
        "recycle-bin-unknown",
        "unresolved-backup-intent",
        "invalid-provenance",
        "unreviewed-holds",
    ],
)
def test_unknown_domain_blocks(issue: str) -> None:
    h = Harness()
    h.inventory_value = replace(h.inventory_value, issues=(issue,))
    with pytest.raises(ValueError):
        h.execute()
    assert not h.adapter.calls


@pytest.mark.parametrize(
    "outcome",
    [DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED, DeleteRequestOutcome.NOT_FOUND_BEFORE_REQUEST],
)
def test_definitive_initial_no_mutation_is_recorded(outcome: DeleteRequestOutcome) -> None:
    h = Harness()
    h.adapter.outcome = outcome
    r = h.execute()
    assert r and r.phase == DeletionPhase.NO_MUTATION and not h.pending
    assert h.engine.reconcile(PROOF) == r


@pytest.mark.parametrize("present", [False, True, None])
def test_unknown_response_is_never_deleted_from_absence_alone(present: bool | None) -> None:
    h = Harness()
    h.adapter.outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN
    h.execute()
    h.observation_active = present
    for _ in range(3):
        h.tick()
        h.engine.reconcile(PROOF)
    assert h.record and h.record.phase != DeletionPhase.FORMALLY_DELETED and h.pending


def test_retry_same_exact_target_once_after_backoff_and_fresh_membership() -> None:
    h = Harness()
    plan = h.engine.prepare(PROOF)
    h.adapter.outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN
    h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    h.observation_active = True
    h.tick()
    h.engine.reconcile(PROOF)
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        h.engine.retry(plan, PROOF)
    h.tick()
    h.engine.reconcile(PROOF)
    r = h.engine.retry(plan, PROOF)
    assert r.attempt == 2 and h.adapter.calls == [plan.snapshot_id] * 2
    h.tick(30)
    h.engine.reconcile(PROOF)
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        h.engine.retry(plan, PROOF)
    assert h.pending


def test_retry_stops_on_new_reference_or_lease_loss() -> None:
    for change in ["reference", "lease"]:
        h = Harness()
        plan = h.engine.prepare(PROOF)
        h.adapter.outcome = DeleteRequestOutcome.OUTCOME_UNKNOWN
        h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
        h.observation_active = True
        h.tick(30)
        h.engine.reconcile(PROOF)
        if change == "reference":
            h.inventory_value = replace(h.inventory_value, reference_revision="later")
        else:
            h.owned = False
        with pytest.raises((ValueError, LeaseLost)):
            h.engine.retry(plan, PROOF)
        assert len(h.adapter.calls) == 1 and h.pending


def test_claim_response_loss_and_worker_restart_never_replays() -> None:
    h = Harness()
    plan = h.engine.prepare(PROOF)
    h.claim_response_loss = True
    with pytest.raises(ValueError):
        h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    h.claim_response_loss = False
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) == h.record
    assert not h.adapter.calls and h.pending
    h.tick()
    assert h.engine.reconcile(PROOF) == h.record and h.pending


def test_final_record_write_interruption_never_repeats_request() -> None:
    h = Harness()
    h.fail_save = True
    plan = h.engine.prepare(PROOF)
    with pytest.raises(ValueError):
        h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    assert len(h.adapter.calls) == 1 and h.pending
    h.fail_save = False
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) == h.record
    assert len(h.adapter.calls) == 1


def test_after_final_commit_restart_keeps_same_provenance_and_result() -> None:
    h = Harness()
    before = deepcopy(h.inventory_value.proofs)
    plan = h.engine.prepare(PROOF)
    h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE)
    for _ in range(2):
        h.tick()
        h.engine.reconcile(PROOF)
    result = h.record
    assert result and result.phase == DeletionPhase.FORMALLY_DELETED
    h.engine = RetentionExecution(
        reads=h, leases=h, journal=h, clock=lambda: h.now, adapter=h.adapter
    )
    assert h.engine.execute(plan, PROOF, mode=ExecutionMode.DELETE_ONE) == result
    assert h.inventory_value.proofs == before and len(h.adapter.calls) == 1
    with pytest.raises(ValueError):
        h.engine.execute(
            replace(plan, snapshot_id=h.inventory_value.snapshots[-2].snapshot_id),
            PROOF,
            mode=ExecutionMode.DELETE_ONE,
        )


def test_snapshot_absence_requires_exact_confirmed_deletion_record() -> None:
    h = Harness()
    h.execute()
    for _ in range(2):
        h.tick()
        h.engine.reconcile(PROOF)
    r = h.record
    assert r
    p = h.inventory_value.proofs[r.snapshot_id]

    def classify(rec: DeletionRecord | None, **kw: Any) -> str:
        return classify_absence(
            p,
            rec,
            account=ACCOUNT,
            region="ap-northeast-1",
            system_id="wishicraft-main",
            now=h.now,
            referenced=kw.get("referenced", False),
            present=kw.get("present", False),
        )

    assert classify(None) == "ANOMALY"
    assert classify(r) == "FORMALLY_DELETED"
    assert classify(r, referenced=True) == "ANOMALY"
    assert classify(r, present=True) == "ANOMALY"
    assert classify(replace(r, backup_operation_id="op-other")) == "ANOMALY"
    assert classify(replace(r, source_volume_id="vol-00000000000000000")) == "ANOMALY"


def test_exception_privacy_and_unknown_observation() -> None:
    class ErrorAdapter:
        def delete_once(self, *, snapshot_id: str) -> DeleteRequestOutcome:
            raise RuntimeError(CANARY)

    h = Harness()
    h.engine.adapter = ErrorAdapter()
    stream = io.StringIO()
    with redirect_stdout(stream), redirect_stderr(stream):
        r = h.execute()
        h.tick()
        h.observation_active = None
        h.engine.reconcile(PROOF)
    assert r and r.request_outcome == DeleteRequestOutcome.OUTCOME_UNKNOWN
    assert CANARY not in stream.getvalue() + json.dumps(h.saved)
    assert h.pending


def test_oldest_tie_and_seventh_eighth_tie_never_dispatch() -> None:
    for a, b in [(10, 11), (6, 7)]:
        h = Harness()
        inv = h.inventory_value
        items, proofs = list(inv.snapshots), dict(inv.proofs)
        time = items[a].start_time
        s = items[b]
        items[b] = replace(
            s, start_time=time, tags={**s.tags, "WishicraftCreatedAt": time.isoformat()}
        )
        proofs[s.snapshot_id] = replace(
            proofs[s.snapshot_id],
            snapshot_start_time=time,
            wishicraft_created_at=time,
            operation_requested_at=time,
        )
        h.inventory_value = replace(inv, snapshots=tuple(items), proofs=proofs)
        with pytest.raises(ValueError):
            h.execute()
        assert not h.adapter.calls and not h.saved
