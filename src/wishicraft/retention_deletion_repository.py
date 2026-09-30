"""CAS deletion journal + pending bit on the existing non-TTL global Lock.

Claim includes a permanent per-RETENTION uniqueness record, so even after Operations
TTL or restart the same execution cannot move on to a second snapshot. No BACKUP
provenance is overwritten. Production wiring/IAM remains absent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from wishicraft.dynamodb_read import item
from wishicraft.maintenance_repository import encode
from wishicraft.operation import LeaseProof
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord


class DeletionRepository:
    def __init__(
        self,
        api: Any,
        *,
        backups_table: str,
        locks_table: str,
        state_table: str,
        operations_table: str,
        lock_name: str,
    ) -> None:
        self.api = api
        self.backups, self.locks, self.states = backups_table, locks_table, state_table
        self.operations, self.lock_name = operations_table, lock_name

    def _read(self, key: str) -> dict[str, Any]:
        try:
            return item(self.api, self.backups, "provenance_key", key)
        except Exception:
            raise ValueError("DELETION_READ_UNCONFIRMED") from None

    def read_operation(self, operation_id: str) -> DeletionRecord | None:
        reverse = self._read("RETENTION#" + operation_id)
        if not reverse:
            return None
        if set(reverse) != {
            "provenance_key",
            "record_type",
            "retention_operation_id",
            "snapshot_id",
        }:
            raise ValueError("INVALID_DELETION_REVERSE")
        if (
            reverse["retention_operation_id"] != operation_id
            or reverse["record_type"] != "RETENTION_DELETION_UNIQUENESS"
        ):
            raise ValueError("INVALID_DELETION_REVERSE")
        if not isinstance(reverse["snapshot_id"], str):
            raise ValueError("INVALID_DELETION_REVERSE")
        record = self.read_snapshot(reverse["snapshot_id"])
        if record is None or record.retention_operation_id != operation_id:
            raise ValueError("PARTIAL_DELETION_PAIR")
        return record

    def read_snapshot(self, snapshot_id: str) -> DeletionRecord | None:
        row = self._read("DELETION#" + snapshot_id)
        return DeletionRecord.parse(row) if row else None

    def _lock(self, proof: LeaseProof, now: datetime) -> dict[str, Any]:
        return {
            "TableName": self.locks,
            "Key": encode({"lock_name": self.lock_name}),
            "ConditionExpression": "resource_id = :system AND owner_operation_id = :operation "
            "AND lease_id = :lease AND lease_expires_at >= :now AND operation_type = :retention",
            "ExpressionAttributeValues": encode(
                {
                    ":system": proof.resource_id,
                    ":operation": proof.owner_operation_id,
                    ":lease": proof.lease_id,
                    ":now": int(now.timestamp()),
                    ":retention": "RETENTION",
                }
            ),
        }

    def claim(self, record: DeletionRecord, proof: LeaseProof, now: datetime) -> bool:
        if (
            record.retention_operation_id != proof.owner_operation_id
            or record.system_id != proof.resource_id
        ):
            raise ValueError("DELETION_OPERATION_MISMATCH")
        if record.phase != DeletionPhase.DISPATCHED or record.attempt != 1 or record.revision != 1:
            raise ValueError("INVALID_INITIAL_DELETION")
        old = self.read_operation(proof.owner_operation_id)
        if old is not None:
            if old.snapshot_id != record.snapshot_id or old.predicate_id != record.predicate_id:
                raise ValueError("DELETION_IDEMPOTENCY_CONFLICT")
            return False
        lock = self._lock(proof, now)
        lock["ConditionExpression"] += " AND attribute_not_exists(retention_delete_pending)"
        lock["UpdateExpression"] = "SET retention_delete_pending = :snapshot"
        lock["ExpressionAttributeValues"].update(encode({":snapshot": record.snapshot_id}))
        reverse = {
            "provenance_key": "RETENTION#" + record.retention_operation_id,
            "record_type": "RETENTION_DELETION_UNIQUENESS",
            "retention_operation_id": record.retention_operation_id,
            "snapshot_id": record.snapshot_id,
        }
        tx = [
            {"Update": lock},
            {
                "ConditionCheck": {
                    "TableName": self.states,
                    "Key": encode({"system_id": record.system_id}),
                    "ConditionExpression": "current_operation_id = :op AND "
                    "(attribute_not_exists(maintenance) OR maintenance.#s = :ended)",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": encode(
                        {":op": record.retention_operation_id, ":ended": "ENDED"}
                    ),
                }
            },
            {
                "ConditionCheck": {
                    "TableName": self.operations,
                    "Key": encode({"operation_id": record.retention_operation_id}),
                    "ConditionExpression": "operation_type = :retention "
                    "AND #s IN (:pending, :running) "
                    "AND requested_by = :actor",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": encode(
                        {
                            ":retention": "RETENTION",
                            ":pending": "PENDING",
                            ":running": "RUNNING",
                            ":actor": record.actor,
                        }
                    ),
                }
            },
            *[
                {
                    "Put": {
                        "TableName": self.backups,
                        "Item": encode(row),
                        "ConditionExpression": "attribute_not_exists(provenance_key)",
                    }
                }
                for row in (record.item(), reverse)
            ],
        ]
        try:
            self.api.transact_write_items(TransactItems=tx)
        except Exception:
            # Even when the write committed, a lost response must not dispatch. Another
            # worker might own the request. Preserve the claim and inspect, never replay.
            raise ValueError("DELETION_CLAIM_UNKNOWN_OR_CONFLICT") from None
        return True

    def save(
        self, before: DeletionRecord, after: DeletionRecord, proof: LeaseProof, now: datetime
    ) -> None:
        mutable = {
            "phase",
            "request_outcome",
            "reconciliation",
            "confirmed_at",
            "attempt",
            "revision",
            "first_absent_at",
            "last_observed_at",
        }
        if (
            after.revision != before.revision + 1
            or any(v != after.item()[k] for k, v in before.item().items() if k not in mutable)
            or before.phase in {DeletionPhase.FORMALLY_DELETED, DeletionPhase.NO_MUTATION}
            or proof.owner_operation_id != before.retention_operation_id
        ):
            raise ValueError("DELETION_CAS_CONFLICT")
        allowed = {
            DeletionPhase.DISPATCHED: {
                DeletionPhase.RESPONSE_RECORDED,
                DeletionPhase.NO_MUTATION,
                DeletionPhase.RECONCILIATION_REQUIRED,
            },
            DeletionPhase.RESPONSE_RECORDED: {
                DeletionPhase.RESPONSE_RECORDED,
                DeletionPhase.FORMALLY_DELETED,
                DeletionPhase.DISPATCHED,
            },
        }
        retry = after.phase == DeletionPhase.DISPATCHED
        if (
            after.phase not in allowed.get(before.phase, set())
            or (
                retry
                and (
                    before.attempt != 1
                    or after.attempt != 2
                    or before.request_outcome != "OUTCOME_UNKNOWN"
                    or before.reconciliation != "STILL_PRESENT"
                )
            )
            or (not retry and after.attempt != before.attempt)
        ):
            raise ValueError("DELETION_TRANSITION_CONFLICT")
        lock = self._lock(proof, now)
        lock["ConditionExpression"] += " AND retention_delete_pending = :snapshot"
        lock["ExpressionAttributeValues"].update(encode({":snapshot": before.snapshot_id}))
        terminal = after.phase in {DeletionPhase.FORMALLY_DELETED, DeletionPhase.NO_MUTATION}
        if terminal:
            lock["UpdateExpression"] = "REMOVE retention_delete_pending"
        try:
            self.api.transact_write_items(
                TransactItems=[
                    {"Update" if terminal else "ConditionCheck": lock},
                    {
                        "Put": {
                            "TableName": self.backups,
                            "Item": encode(after.item()),
                            "ConditionExpression": "#revision = :revision "
                            "AND predicate_id = :predicate "
                            "AND retention_operation_id = :op AND #phase = :phase",
                            "ExpressionAttributeNames": {
                                "#revision": "revision",
                                "#phase": "phase",
                            },
                            "ExpressionAttributeValues": encode(
                                {
                                    ":revision": before.revision,
                                    ":predicate": before.predicate_id,
                                    ":op": before.retention_operation_id,
                                    ":phase": before.phase.value,
                                }
                            ),
                        }
                    },
                ]
            )
        except Exception:
            # A committed response update can be acknowledged without dispatching again.
            if self.read_snapshot(before.snapshot_id) != after:
                raise ValueError("DELETION_WRITE_UNKNOWN_OR_CONFLICT") from None

    def resume_reconciliation(
        self,
        before: DeletionRecord,
        after: DeletionRecord,
        old: LeaseProof,
        new: LeaseProof,
        now: datetime,
    ) -> None:
        """Only called after quiescence/reference proof; atomically re-own SAME pending op.

        Never removes pending, changes the target, increments attempt or dispatches.
        Lost transaction response is unknown and requires read-back, not another request.
        """
        mutable = {
            "revision",
            "phase",
            "request_outcome",
            "reconciliation",
            "first_absent_at",
            "last_observed_at",
        }
        if (
            before.execution_arn is None
            or before.phase in {DeletionPhase.FORMALLY_DELETED, DeletionPhase.NO_MUTATION}
            or after.phase != DeletionPhase.RESPONSE_RECORDED
            or after.revision != before.revision + 1
            or any(v != after.item()[k] for k, v in before.item().items() if k not in mutable)
            or after.request_outcome
            != (
                "OUTCOME_UNKNOWN"
                if before.request_outcome == "NOT_RECORDED"
                else before.request_outcome
            )
            or (old.resource_id, old.owner_operation_id)
            != (new.resource_id, new.owner_operation_id)
            or new.owner_operation_id != before.retention_operation_id
            or new.resource_id != before.system_id
            or new.lease_id == old.lease_id
            or new.lease_expires_at != int(now.timestamp()) + 900
        ):
            raise ValueError("RECOVERY_CAS_CONFLICT")
        values = encode(
            {
                ":op": before.retention_operation_id,
                ":system": before.system_id,
                ":old": old.lease_id,
                ":new": new.lease_id,
                ":old_expiry": old.lease_expires_at,
                ":expiry": new.lease_expires_at,
                ":snapshot": before.snapshot_id,
                ":type": "RETENTION",
            }
        )
        try:
            self.api.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.locks,
                            "Key": encode({"lock_name": self.lock_name}),
                            "ConditionExpression": (
                                "resource_id = :system AND owner_operation_id = :op AND lease_id "
                                "= :old AND lease_expires_at = :old_expiry AND "
                                "retention_delete_pending = :snapshot AND operation_type = :type"
                            ),
                            "UpdateExpression": "SET lease_id = :new, lease_expires_at = :expiry",
                            "ExpressionAttributeValues": values,
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.backups,
                            "Item": encode(after.item()),
                            "ConditionExpression": (
                                "#revision = :revision AND #phase = :phase AND attempt = :attempt "
                                "AND retention_operation_id = :op AND predicate_id = :predicate"
                            ),
                            "ExpressionAttributeNames": {
                                "#revision": "revision",
                                "#phase": "phase",
                            },
                            "ExpressionAttributeValues": encode(
                                {
                                    ":revision": before.revision,
                                    ":phase": before.phase.value,
                                    ":attempt": before.attempt,
                                    ":op": before.retention_operation_id,
                                    ":predicate": before.predicate_id,
                                }
                            ),
                        }
                    },
                    {
                        "ConditionCheck": {
                            "TableName": self.backups,
                            "Key": encode(
                                {"provenance_key": "RETENTION#" + before.retention_operation_id}
                            ),
                            "ConditionExpression": (
                                "snapshot_id = :snapshot AND retention_operation_id = :op"
                            ),
                            "ExpressionAttributeValues": encode(
                                {
                                    ":snapshot": before.snapshot_id,
                                    ":op": before.retention_operation_id,
                                }
                            ),
                        }
                    },
                    {
                        "ConditionCheck": {
                            "TableName": self.states,
                            "Key": encode({"system_id": before.system_id}),
                            "ConditionExpression": (
                                "current_operation_id = :op AND "
                                "(attribute_not_exists(maintenance) OR maintenance.#status = "
                                ":ended)"
                            ),
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": encode(
                                {":op": before.retention_operation_id, ":ended": "ENDED"}
                            ),
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.operations,
                            "Key": encode({"operation_id": before.retention_operation_id}),
                            "ConditionExpression": (
                                "operation_type = :type AND workflow_execution_arn = :execution "
                                "AND lease_id = :old"
                            ),
                            "UpdateExpression": "SET lease_id = :new",
                            "ExpressionAttributeValues": encode(
                                {
                                    ":type": "RETENTION",
                                    ":execution": before.execution_arn,
                                    ":old": old.lease_id,
                                    ":new": new.lease_id,
                                }
                            ),
                        }
                    },
                ]
            )
        except Exception:
            raise ValueError("RECOVERY_WRITE_UNCONFIRMED") from None
