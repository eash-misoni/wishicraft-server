"""Shared-volume protection authority; pure transitions and conditional state writes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any

from wishicraft.maintenance_repository import encode
from wishicraft.system_state import utc_timestamp

MAX_ATTEMPTS = 3
RETRY_SECONDS = (900, 3600)


def initial(volume: str, now: datetime) -> dict[str, Any]:
    return dict(
        schema_version=1,
        volume_id=volume,
        boundary=1,
        protected_boundary=0,
        oldest_at=None,
        unknown_since=utc_timestamp(now),
        stopped_at=None,
        intent=None,
        attempts=0,
        last_success=None,
    )


def read_protection(state: dict[str, Any], volume: str, now: datetime) -> dict[str, Any]:
    value = state.get("backup_protection")
    if value is None:
        return initial(volume, now)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("volume_id") != volume
        or not isinstance(value.get("boundary"), (int, Decimal))
        or value["boundary"] < value.get("protected_boundary", -1)
    ):
        raise ValueError("protection authority invalid")
    result = deepcopy(value)
    for key in ("schema_version", "boundary", "protected_boundary", "attempts"):
        number = result.get(key)
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, Decimal))
            or number != int(number)
            or number < 0
        ):
            raise ValueError("invalid protection counter")
        result[key] = int(number)
    for key in ("intent", "last_success"):
        if result.get(key) is not None and "boundary" in result[key]:
            result[key]["boundary"] = int(result[key]["boundary"])
    return result


def dirty(p: dict[str, Any], now: datetime, *, unknown: bool = False) -> dict[str, Any]:
    p = deepcopy(p)
    if p["boundary"] == p["protected_boundary"]:
        p["oldest_at"] = utc_timestamp(now)
        p["attempts"] = 0
    p["boundary"] += 1
    if not unknown:
        p["stopped_at"] = None
    if unknown:
        p["unknown_since"] = p.get("unknown_since") or utc_timestamp(now)
    return p


def stopped(p: dict[str, Any], now: datetime) -> dict[str, Any]:
    p = deepcopy(p)
    if p["boundary"] > p["protected_boundary"] and p.get("stopped_at") is None:
        p["stopped_at"] = utc_timestamp(now)
    return p


def success(
    p: dict[str, Any],
    *,
    boundary: int,
    operation: str,
    snapshot: str,
    acquired_at: str,
    now: datetime,
) -> dict[str, Any]:
    p = deepcopy(p)
    if boundary > p["boundary"]:
        raise ValueError("future protection boundary")
    if boundary > p["protected_boundary"]:
        p["protected_boundary"] = boundary
        p["last_success"] = dict(
            operation_id=operation,
            snapshot_id=snapshot,
            acquired_at=acquired_at,
            verified_at=utc_timestamp(now),
            boundary=boundary,
        )
    if boundary == p["boundary"]:
        p.update(oldest_at=None, unknown_since=None, stopped_at=None, attempts=0)
    # A delayed older completion must not clear a newer request or unknown interval.
    if p.get("intent") and p["intent"]["operation_id"] == operation:
        p["intent"]["status"] = "SUCCEEDED"
    return p


def age(value: str | None, now: datetime) -> float:
    if value is None:
        return 0
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed > now:
        raise ValueError("invalid protection time")
    return (now - parsed).total_seconds()


def status(
    p: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime,
    enabled: bool,
    actual: str,
    locked: bool,
) -> dict[str, Any]:
    unprotected = p["boundary"] > p["protected_boundary"]
    intent = p.get("intent") or {}
    reason = "AVAILABLE"
    if intent.get("status") in {"UNKNOWN", "FAILED"}:
        reason = "RECONCILIATION_REQUIRED" if intent["status"] == "UNKNOWN" else "FAILED"
    elif intent.get("status") == "ADMITTED":
        reason = "BACKUP_RUNNING"
    elif not unprotected:
        reason = "PROTECTED"
    elif (state.get("maintenance") or {}).get("status", "ENDED") != "ENDED":
        reason = "MAINTENANCE"
    elif locked or state.get("current_operation_id"):
        reason = "OTHER_OPERATION"
    elif state.get("desired_state") == "RUNNING" and actual == "running":
        reason = "RUNNING"
    elif (
        state.get("desired_state") != "STOPPED"
        or state.get("health") != "HEALTHY"
        or actual != "stopped"
        or state.get("observation", {}).get("ec2_state") != "stopped"
        or state.get("observation_errors")
        or state.get("discrepancies")
    ):
        reason = "OBSERVATION_UNKNOWN"
    elif not p.get("stopped_at"):
        reason = "NORMAL_STOP_REQUIRED"
    if not enabled:
        reason = "DISABLED"
    waiting = age(p.get("stopped_at"), now) if state.get("desired_state") == "STOPPED" else 0
    oldest = age(p.get("oldest_at") or p.get("unknown_since"), now)
    return dict(
        reason=reason,
        unprotected=unprotected,
        protection=p,
        stopped_warning=enabled and unprotected and waiting >= 1800,
        interval_warning=enabled and unprotected and oldest >= 86400,
        history_unknown=p.get("unknown_since") is not None,
        needs_operator=(
            reason in {"RECONCILIATION_REQUIRED", "OBSERVATION_UNKNOWN", "NORMAL_STOP_REQUIRED"}
            or (
                reason == "FAILED"
                and (not intent.get("safe_retry") or p["attempts"] >= MAX_ATTEMPTS)
            )
        ),
    )


def attach(update: dict[str, Any], state: dict[str, Any], p: dict[str, Any]) -> None:
    """Extend an existing SystemState update without replacing unrelated attributes."""
    expression = update["UpdateExpression"]
    if expression.startswith("SET "):
        expression = expression.replace("SET ", "SET backup_protection = :bp, ", 1)
    else:
        expression = "SET backup_protection = :bp " + expression
    update["UpdateExpression"] = expression
    values = update.setdefault("ExpressionAttributeValues", {})
    values.update(encode({":bp": p}))
    if "backup_protection" in state:
        update["ConditionExpression"] += " AND backup_protection = :bp_old"
        values.update(encode({":bp_old": state["backup_protection"]}))
    else:
        update["ConditionExpression"] += " AND attribute_not_exists(backup_protection)"


def load(api: Any, table: str, system: str) -> dict[str, Any]:
    from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

    response = api.get_item(TableName=table, Key={"system_id": {"S": system}}, ConsistentRead=True)
    if not isinstance(response, dict) or not isinstance(response.get("Item"), dict):
        raise ValueError("SystemState unavailable")
    decoder = TypeDeserializer()
    return {k: decoder.deserialize(v) for k, v in response["Item"].items()}


def admission(
    repository: Any, request: Any, transaction: list[dict[str, Any]], volume: str
) -> None:
    from wishicraft.operation import AdmissionConflict

    state = load(repository._api, repository._system_state, repository._system_id)
    p = read_protection(state, volume, request.requested_at)
    kind = request.operation_type.value
    if kind in {"START", "SWITCH", "RESET"}:
        p = dirty(p, request.requested_at)
    elif kind == "BACKUP":
        current = p.get("intent") or {}
        if request.daily_boundary is not None:
            if (
                p["boundary"] != request.daily_boundary
                or p["boundary"] <= p["protected_boundary"]
                or not p.get("stopped_at")
                or state.get("desired_state") != "STOPPED"
                or state.get("health") != "HEALTHY"
                or current.get("status") in {"ADMITTED", "UNKNOWN"}
                or p["attempts"] >= MAX_ATTEMPTS
            ):
                raise AdmissionConflict("daily protection changed")
            if current.get("status") == "FAILED":
                if (
                    not current.get("safe_retry")
                    or age(current["finished_at"], request.requested_at)
                    < RETRY_SECONDS[min(max(int(p["attempts"]) - 1, 0), 1)]
                ):
                    raise AdmissionConflict("daily retry blocked")
            p["attempts"] += 1
        elif current.get("status") in {"ADMITTED", "UNKNOWN"}:
            raise AdmissionConflict("unresolved shared BACKUP")
        p["intent"] = dict(
            operation_id=request.operation_id,
            boundary=p["boundary"],
            status="ADMITTED",
            requested_at=utc_timestamp(request.requested_at),
            automatic=request.daily_boundary is not None,
        )
        transaction[1]["Put"]["Item"].update(encode({"backup_boundary": p["boundary"]}))
    else:
        return
    update = next(
        x["Update"]
        for x in transaction
        if "Update" in x and x["Update"]["TableName"] == repository._system_state
    )
    if request.daily_boundary is not None:
        update["ConditionExpression"] += (
            " AND desired_state = :daily_stopped AND health = :daily_healthy "
            "AND observed_at = :daily_observed"
        )
        update["ExpressionAttributeValues"].update(
            encode(
                {
                    ":daily_stopped": "STOPPED",
                    ":daily_healthy": "HEALTHY",
                    ":daily_observed": state["observed_at"],
                }
            )
        )
    attach(update, state, p)


def completion(
    repository: Any,
    update: dict[str, Any],
    *,
    operation: str,
    result: dict[str, Any] | None,
    now: datetime,
    normal_stop: bool,
    error: str | None,
    acquired_at: str | None,
    volume: str,
) -> None:
    state = load(repository._api, repository._system_state, repository._system_id)
    p = read_protection(state, volume, now)
    if normal_stop:
        p = stopped(p, now)
    elif result and result.get("kind") == "BACKUP":
        intent = p.get("intent") or {}
        if intent.get("operation_id") != operation:
            raise ValueError("BACKUP protection capture missing")
        if acquired_at is None:
            raise ValueError("snapshot acquisition time required")
        p = success(
            p,
            boundary=int(intent["boundary"]),
            operation=operation,
            snapshot=result["snapshot_id"],
            acquired_at=acquired_at,
            now=now,
        )
    elif (p.get("intent") or {}).get("operation_id") == operation:
        # Only a proven failure before CreateSnapshot reservation is automatically retried.
        raw = repository._api.get_item(
            TableName=repository._operations,
            Key={"operation_id": {"S": operation}},
            ConsistentRead=True,
        ).get("Item", {})
        before_reservation = error in {
            "WORKFLOW_START_FAILED",
            "BACKUP_PRECONDITION_FAILED",
            "BACKUP_SOURCE_VOLUME_MISMATCH",
            "OBSERVATION_FAILED",
        } and not any(k in raw for k in ("backup_create_intent", "backup_snapshot_id"))
        rejected = error == "BACKUP_SNAPSHOT_CREATE_FAILED" and "backup_snapshot_id" not in raw
        safe = before_reservation or rejected
        known_failure = safe or error == "BACKUP_SNAPSHOT_FAILED"
        p["intent"].update(
            status="FAILED" if known_failure else "UNKNOWN",
            safe_retry=safe,
            error=error,
            finished_at=utc_timestamp(now),
        )
    else:
        return
    attach(update, state, p)
