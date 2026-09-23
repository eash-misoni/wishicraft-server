"""Atomic maintenance fence and immutable audit events in the existing state table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]

from wishicraft.maintenance import ADMISSION_CONDITION, check_restore_lease, lease_active


def encode(item: dict[str, Any]) -> dict[str, Any]:
    serializer = TypeSerializer()
    return {k: serializer.serialize(v) for k, v in item.items()}


def check_restore_recovery(
    record: dict[str, Any], previous: dict[str, Any], *, operation: str, system_id: str
) -> None:
    """The journal must have participated in this lease, not just exist in the system."""
    check_restore_lease(previous, operation)
    plan = record.get("plan", {})
    if (
        record.get("record_type") != "RESTORE"
        or record.get("system_id") != "restore#" + operation
        or plan.get("operation_id") != operation
        or plan.get("system_id") != system_id
        or plan.get("stage") != previous.get("stage")
        or not previous.get("id")
        or record.get("last_maintenance_id", record.get("maintenance_id")) != previous["id"]
    ):
        raise ValueError("RESTORE_RECOVERY_UNRELATED_LEASE")


def transition(
    api: Any,
    *,
    table: str,
    locks_table: str,
    system_id: str,
    lock_name: str,
    state: dict[str, Any],
    lease: dict[str, Any],
    event: str,
    now: datetime,
    restore_record: dict[str, Any] | None = None,
) -> None:
    """Caller supplies fresh external preflight; transaction fences all Admission writers."""
    previous = state.get("maintenance")
    if event == "begin":
        if previous is not None and previous.get("status") != "ENDED":
            raise ValueError("maintenance already open, including expired/incident leases")
        if not lease_active(lease, now=now):
            raise ValueError("new maintenance lease is not active")
    elif event == "recover-restore":
        if (
            not isinstance(previous, dict)
            or previous.get("status") not in {"ACTIVE", "INCIDENT"}
            or lease_active(previous, now=now)
            or not lease_active(lease, now=now)
            or previous.get("id") != lease.get("previous_maintenance_id")
            or previous.get("id") == lease.get("id")
            or previous.get("stage") != lease.get("stage")
            or not lease.get("restore_operation_id")
        ):
            raise ValueError("invalid RESTORE maintenance recovery")
        check_restore_recovery(
            restore_record or {},
            previous,
            operation=lease["restore_operation_id"],
            system_id=system_id,
        )
    elif event not in {"end", "incident"} or not isinstance(previous, dict):
        raise ValueError("maintenance transition requires an existing lease")
    elif previous.get("id") != lease.get("id") or previous.get("status") == "ENDED":
        raise ValueError("maintenance identity/status conflict")

    values: dict[str, Any] = {":lease": lease}
    names: dict[str, str] = {}
    if event == "incident":
        # Incident removes suppression without pretending external resources are safe.
        condition = "maintenance = :previous"
        values[":previous"] = previous
    else:
        if state.get("desired_state") != "STOPPED" or state.get("current_operation_id") is not None:
            raise ValueError("maintenance requires stopped and unowned SystemState")
        condition = (
            "desired_state = :stopped AND desired_revision = :revision AND "
            "observed_at = :observed AND "
            "(attribute_not_exists(current_operation_id) OR current_operation_id = :null)"
        )
        values.update(
            {
                ":stopped": "STOPPED",
                ":revision": state["desired_revision"],
                ":observed": state["observed_at"],
                ":null": None,
            }
        )
        if event == "begin":
            condition += " AND " + ADMISSION_CONDITION
            names["#ms"] = "status"
            values[":maintenance_ended"] = "ENDED"
        else:
            condition += " AND maintenance = :previous"
            values[":previous"] = previous
    update: dict[str, Any] = {
        "TableName": table,
        "Key": {"system_id": {"S": system_id}},
        "UpdateExpression": "SET maintenance = :lease",
        "ConditionExpression": condition,
        "ExpressionAttributeValues": encode(values),
    }
    if names:
        update["ExpressionAttributeNames"] = names
    transaction = [
        {"Update": update},
        {
            "Put": {
                "TableName": table,
                "Item": encode(
                    {
                        "system_id": f"maintenance#{lease['id']}#{event}",
                        "event": event,
                        "recorded_at": int(now.timestamp()),
                        "maintenance": lease,
                        "subject_system_id": system_id,
                        **(
                            {"previous_maintenance": previous} if event == "recover-restore" else {}
                        ),
                    }
                ),
                "ConditionExpression": "attribute_not_exists(system_id)",
            }
        },
    ]
    if event != "incident":
        transaction.append(
            {
                "ConditionCheck": {
                    "TableName": locks_table,
                    "Key": {"lock_name": {"S": lock_name}},
                    "ConditionExpression": "attribute_not_exists(lock_name)",
                }
            }
        )
    if event == "recover-restore":
        assert restore_record is not None
        assert isinstance(previous, dict)
        # The pointer advances with the lease/audit, including recovery with no intervening work.
        binding = (
            "last_maintenance_id" if "last_maintenance_id" in restore_record else "maintenance_id"
        )
        transaction.append(
            {
                "Put": {
                    "TableName": table,
                    "Item": encode(
                        {
                            **restore_record,
                            "last_maintenance_id": lease["id"],
                            "revision": restore_record["revision"] + 1,
                        }
                    ),
                    "ConditionExpression": "#revision = :revision AND #plan = :plan AND "
                    "#binding = :previous",
                    "ExpressionAttributeNames": {
                        "#revision": "revision",
                        "#plan": "plan",
                        "#binding": binding,
                    },
                    "ExpressionAttributeValues": encode(
                        {
                            ":revision": restore_record["revision"],
                            ":plan": restore_record["plan"],
                            ":previous": previous["id"],
                        }
                    ),
                }
            }
        )
    api.transact_write_items(TransactItems=transaction)
