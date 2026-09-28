"""Bounded positive read adapter for explicit reconciliation; no invocation or mutation."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from wishicraft.maintenance_operator import item
from wishicraft.operation import LeaseProof
from wishicraft.retention_deletion import DeletionRecord, classify_absence
from wishicraft.retention_deletion_repository import DeletionRepository
from wishicraft.retention_execution_reads import ExecutionReads
from wishicraft.retention_recovery import Quiescence, RecoveryRead


def read_quiescence(
    states: Any, functions: Any, record: DeletionRecord, now: datetime
) -> Quiescence:
    """Never persist inputs/outputs/history/errors. Unexpected history leaves pending.

    Exact terminal execution read twice, complete history, exactly one synchronous run
    task; failure-record task does not dispatch. Redriven/retried dispatch is manual review.
    """
    try:
        before = states.describe_execution(executionArn=record.execution_arn)
        events: dict[int, dict[str, Any]] = {}
        token: str | None = None
        seen: set[str] = set()
        for _ in range(100):
            args: dict[str, Any] = dict(
                executionArn=record.execution_arn, maxResults=1000, includeExecutionData=True
            )
            if token is not None:
                args["nextToken"] = token
            page = states.get_execution_history(**args)
            for event in page["events"]:
                if type(event["id"]) is not int or event["id"] in events:
                    raise ValueError("history")
                events[event["id"]] = event
            token = page.get("nextToken")
            if token is None:
                break
            if not isinstance(token, str) or not token or token in seen:
                raise ValueError("pagination")
            seen.add(token)
        else:
            raise ValueError("history limit")
        dispatches = []
        for event in events.values():
            detail = event.get("taskScheduledEventDetails", {})
            if detail.get("resourceType") != "lambda" or detail.get("resource") != "invoke":
                continue
            payload = json.loads(detail["parameters"])
            if (
                payload.get("FunctionName") == record.dispatcher_arn
                and payload.get("Payload", {}).get("action") == "run"
            ):
                if (
                    payload.get("InvocationType", "RequestResponse") != "RequestResponse"
                    or "Qualifier" in payload
                    or payload["Payload"].get("operation_id") != record.retention_operation_id
                    or payload["Payload"].get("lease_id") != record.dispatcher_lease_id
                ):
                    raise ValueError("task identity")
                dispatches.append(event["id"])
        if len(dispatches) != 1:
            raise ValueError("ambiguous dispatcher")
        ends = []
        for event in events.values():
            if event.get("type") not in {"TaskSucceeded", "TaskFailed", "TaskTimedOut"}:
                continue
            ancestor = event.get("previousEventId")
            visited: set[int] = set()
            while ancestor and ancestor not in visited:
                if ancestor == dispatches[0]:
                    ends.append(event["timestamp"])
                    break
                visited.add(ancestor)
                parent = events[ancestor]
                if parent.get("type") not in {"TaskStarted", "TaskSubmitted"}:
                    break
                ancestor = parent.get("previousEventId")
        after = states.describe_execution(executionArn=record.execution_arn)
        keys = (
            "executionArn",
            "stateMachineArn",
            "status",
            "startDate",
            "stopDate",
            "redriveCount",
        )
        if any(before.get(k) != after.get(k) for k in keys) or len(ends) != 1:
            raise ValueError("execution changed")
        terminal_event = {
            "FAILED": "ExecutionFailed",
            "SUCCEEDED": "ExecutionSucceeded",
            "TIMED_OUT": "ExecutionTimedOut",
            "ABORTED": "ExecutionAborted",
        }.get(after.get("status"))
        machine = (
            str(record.execution_arn).rsplit(":", 1)[0].replace(":execution:", ":stateMachine:")
        )
        if (
            events[max(events)].get("type") != terminal_event
            or after.get("name") != record.retention_operation_id
            or after.get("stateMachineArn") != machine
        ):
            raise ValueError("terminal identity")
        fn = functions.get_function_configuration(FunctionName=record.dispatcher_arn)
        # Configuration remains memory-only; only public identities cross the boundary.
        q = Quiescence(
            after["executionArn"],
            after["status"],
            after["stopDate"],
            ends[0],
            now,
            fn["FunctionArn"],
            fn["RevisionId"],
            fn["Timeout"],
            True,
            True,
            after.get("redriveCount", -1),
            str(max(events)) + ":" + after["stopDate"].isoformat(),
        )
        q.verify(record, now)
        return q
    except Exception:
        raise ValueError("MANUAL_REVIEW_REQUIRED") from None


def read_recovery(
    *,
    record: DeletionRecord,
    reads: ExecutionReads,
    dynamodb: Any,
    locks_table: str,
    lock_name: str,
    states: Any,
    functions: Any,
    now: datetime,
    journal: DeletionRepository,
) -> RecoveryRead:
    try:
        if journal.read_operation(record.retention_operation_id) != record:
            raise ValueError("journal changed")
        inventory = reads.inventory(recovery_snapshot_id=record.snapshot_id)
        proof = inventory.proofs.get(record.snapshot_id)
        if proof is None or inventory.issues:
            raise ValueError("unknown references")
        lock = item(dynamodb, locks_table, "lock_name", lock_name)
        if lock.get("operation_type") != "RETENTION":
            raise ValueError("lock type")
        lease = LeaseProof(
            lock["resource_id"],
            lock["owner_operation_id"],
            lock["lease_id"],
            _lease_expiry(lock["lease_expires_at"]),
        )
        observation = reads.observe(record.snapshot_id)
        result = classify_absence(
            proof,
            record,
            account=inventory.context.owner_id,
            region=inventory.region,
            system_id=inventory.system_id,
            now=now,
            referenced=record.snapshot_id in inventory.holds,
            present=observation.active is True,
        )
        now = reads.clock()
        q = read_quiescence(states, functions, record, now)
        read = RecoveryRead(
            record,
            lease,
            lock["retention_delete_pending"],
            observation,
            inventory.reference_revision,
            reads.hold_revision,
            result == "DELETION_OUTCOME_UNKNOWN",
            record.snapshot_id in inventory.holds,
            not inventory.issues,
            q,
        )
        read.verify(reads.clock())
        return read
    except Exception:
        raise ValueError("MANUAL_REVIEW_REQUIRED") from None


def _lease_expiry(value: object) -> int:
    """DynamoDB N is Decimal; retain exact integral Unix seconds within UTC's range."""
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("INVALID_RECOVERY_LEASE_EXPIRY")
    elif type(value) is not int:
        raise ValueError("INVALID_RECOVERY_LEASE_EXPIRY")
    if not 1 <= value <= 253402300799:
        raise ValueError("INVALID_RECOVERY_LEASE_EXPIRY")
    return int(value)
