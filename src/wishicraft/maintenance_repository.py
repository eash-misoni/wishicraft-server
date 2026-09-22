"""Atomic maintenance fence and immutable audit events in the existing state table."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]

from wishicraft.maintenance import ADMISSION_CONDITION, lease_active


def encode(item: dict[str, Any]) -> dict[str, Any]:
    serializer = TypeSerializer()
    return {k: serializer.serialize(v) for k, v in item.items()}


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
) -> None:
    """Caller supplies fresh external preflight; transaction fences all Admission writers."""
    previous = state.get("maintenance")
    if event == "begin":
        if previous is not None and previous.get("status") != "ENDED":
            raise ValueError("maintenance already open, including expired/incident leases")
        if not lease_active(lease, now=now):
            raise ValueError("new maintenance lease is not active")
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
    api.transact_write_items(TransactItems=transaction)
