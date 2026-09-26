"""Five-minute evaluator and isolated internal shared BACKUP Admission entrypoint."""

from __future__ import annotations

import importlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from wishicraft import daily_backup as domain
from wishicraft.system_state import utc_timestamp


def env(name: str) -> str:
    return os.environ[name]


def clients() -> Any:
    return importlib.import_module("boto3")


def get(api: Any, table: str, key: str, value: str) -> dict[str, Any]:
    from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

    response = api.get_item(TableName=table, Key={key: {"S": value}}, ConsistentRead=True)
    decoder = TypeDeserializer()
    return {k: decoder.deserialize(v) for k, v in response.get("Item", {}).items()}


def observe(ddb: Any, ec2: Any, now: datetime) -> tuple[dict[str, Any], dict[str, Any], str, bool]:
    state = domain.load(ddb, env("SYSTEM_STATE_TABLE"), env("SYSTEM_ID"))
    p = domain.read_protection(state, env("PROTECTION_VOLUME_ID"), now)
    locked = bool(get(ddb, env("LOCKS_TABLE"), "lock_name", env("GLOBAL_LOCK_NAME")))
    instance = state.get("target_instance_id")
    actual = "unknown"
    if isinstance(instance, str) and instance:
        response = ec2.describe_instances(InstanceIds=[instance])
        instances = [i for r in response.get("Reservations", []) for i in r.get("Instances", [])]
        if len(instances) == 1 and instances[0].get("InstanceId") == instance:
            actual = instances[0].get("State", {}).get("Name", "unknown")
    if not state.get("observed_at") or domain.age(state["observed_at"], now) > 600:
        actual = "unknown"
    return state, p, actual, locked


def reconcile_intent(ddb: Any, p: dict[str, Any], now: datetime) -> dict[str, Any]:
    intent = p.get("intent") or {}
    if intent.get("status") != "ADMITTED":
        return p
    operation = get(ddb, env("OPERATIONS_TABLE"), "operation_id", intent["operation_id"])
    # Completed normal writes atomically update this authority. Missing or terminal
    # Operation without that update is not permission to recreate a request.
    if (
        not operation
        or operation.get("status") not in {"PENDING", "RUNNING"}
        or not operation.get("timeout_at")
        or datetime.fromisoformat(operation["timeout_at"].replace("Z", "+00:00")) <= now
    ):
        intent.update(
            status="UNKNOWN",
            safe_retry=False,
            finished_at=utc_timestamp(now),
            error="OPERATION_RECONCILIATION_REQUIRED",
        )
    return p


def persist(ddb: Any, state: dict[str, Any], p: dict[str, Any]) -> None:
    update = dict(
        TableName=env("SYSTEM_STATE_TABLE"),
        Key={"system_id": {"S": env("SYSTEM_ID")}},
        UpdateExpression="SET backup_protection = :bp",
        ConditionExpression="attribute_exists(system_id)",
    )
    # attach owns the assignment and CAS; avoid a second assignment to the same path.
    update["UpdateExpression"] = ""
    domain.attach(update, state, p)
    ddb.update_item(**update)


def evaluate(ddb: Any, ec2: Any, lambdas: Any, cw: Any, *, now: datetime) -> dict[str, Any]:
    enabled = os.environ.get("DAILY_BACKUP_ENABLED") == "1"
    state, p, actual, locked = observe(ddb, ec2, now)
    p = reconcile_intent(ddb, p, now)
    if "backup_protection" not in state:
        previous = get(
            ddb,
            env("OPERATIONS_TABLE"),
            "operation_id",
            str(state.get("last_operation_id", "absent")),
        )
        if (
            previous.get("operation_type") == "STOP"
            and previous.get("status") == "SUCCEEDED"
            and actual == "stopped"
            and state.get("health") == "HEALTHY"
            and state.get("desired_state") == "STOPPED"
            and not locked
            and not state.get("current_operation_id")
            and (state.get("maintenance") or {}).get("status", "ENDED") == "ENDED"
        ):
            p = domain.stopped(p, now)
    if state.get("backup_protection") != p:
        persist(ddb, state, p)
        state["backup_protection"] = p
    result = domain.status(p, state, now=now, enabled=enabled, actual=actual, locked=locked)
    reason = result["reason"]
    retry = (
        reason == "FAILED"
        and (p.get("intent") or {}).get("safe_retry")
        and p["attempts"] < domain.MAX_ATTEMPTS
        and domain.age(p["intent"]["finished_at"], now)
        >= domain.RETRY_SECONDS[min(max(int(p["attempts"]) - 1, 0), 1)]
    )
    if reason == "AVAILABLE" or retry:
        response = lambdas.invoke(
            FunctionName=env("DAILY_BACKUP_ADMISSION_FUNCTION"),
            InvocationType="RequestResponse",
            Payload=json.dumps({"schema_version": 1, "boundary": int(p["boundary"])}).encode(),
        )
        if response.get("FunctionError"):
            raise RuntimeError("daily Admission outcome unknown; next run reconciles authority")
        payload = response.get("Payload")
        raw = payload.read() if hasattr(payload, "read") else payload
        admitted = json.loads(raw)
        if admitted.get("outcome") not in {"ADMITTED", "EXISTING", "CONFLICT", "DISABLED"}:
            raise ValueError("invalid internal Admission response")
        result["admission"] = admitted
    # Failure to observe protection never emits a healthy execution signal.
    metrics = {
        "DailyBackupHeartbeat": 1,
        "DailyBackupStoppedOverdue": int(result["stopped_warning"]),
        "DailyBackupIntervalOverdue": int(result["interval_warning"]),
        "DailyBackupNeedsOperator": int(
            enabled
            and result["needs_operator"]
            # Observation failures keep their existing dedicated alarm.
            and reason != "OBSERVATION_UNKNOWN"
        ),
        "DailyBackupObservationUnknown": int(enabled and reason == "OBSERVATION_UNKNOWN"),
    }
    cw.put_metric_data(
        Namespace="Wishicraft/ControlPlane",
        MetricData=[
            dict(
                MetricName=name,
                Value=value,
                Unit="Count",
                Timestamp=now,
                Dimensions=[
                    dict(Name="Stage", Value=env("STAGE")),
                    dict(Name="SystemId", Value=env("SYSTEM_ID")),
                ],
            )
            for name, value in metrics.items()
        ],
    )
    print(
        json.dumps(
            {
                "reason": reason,
                "unprotected": result["unprotected"],
                "stopped_warning": result["stopped_warning"],
                "interval_warning": result["interval_warning"],
            }
        )
    )
    return result


def handler(event: object, context: object) -> dict[str, Any]:
    del context
    if event != {"schema_version": 1, "operation": "evaluate_daily_backup"}:
        raise ValueError("invalid evaluator invocation")
    sdk = clients()
    return evaluate(
        sdk.client("dynamodb"),
        sdk.client("ec2"),
        sdk.client("lambda"),
        sdk.client("cloudwatch"),
        now=datetime.now(UTC),
    )


def admit(event: object, context: object) -> dict[str, Any]:
    """IAM grants this separate Lambda only to the evaluator. No public routing."""
    del context
    if (
        not isinstance(event, dict)
        or set(event) != {"schema_version", "boundary"}
        or event["schema_version"] != 1
        or type(event["boundary"]) is not int
    ):
        raise ValueError("invalid internal BACKUP request")
    if os.environ.get("DAILY_BACKUP_ENABLED") != "1":
        return {"outcome": "DISABLED"}
    from wishicraft.admission_lambda import _get_backup_launcher, _get_service
    from wishicraft.operation import AdmissionConflict, OperationType, RequestSource
    from wishicraft.runtime_catalog import configured_catalog

    sdk = clients()
    now = datetime.now(UTC)
    state, p, actual, locked = observe(sdk.client("dynamodb"), sdk.client("ec2"), now)
    intent = p.get("intent") or {}
    if intent.get("status") in {"ADMITTED", "UNKNOWN"}:
        return {"outcome": "EXISTING", "operation_id": intent["operation_id"]}
    probe = domain.status(p, state, now=now, enabled=True, actual=actual, locked=locked)
    # FAILED may be retryable, but physical and lifecycle gates still apply.
    if (
        probe["reason"] not in {"AVAILABLE", "FAILED"}
        or actual != "stopped"
        or locked
        or state.get("current_operation_id")
        or (state.get("maintenance") or {}).get("status", "ENDED") != "ENDED"
    ):
        return {"outcome": "CONFLICT"}
    game = state.get("desired_game_id")
    catalog = configured_catalog()
    if catalog is None or not isinstance(game, str):
        raise ValueError("shared runtime catalog required")
    catalog.data_source(game)
    key = f"daily-backup:{env('PROTECTION_VOLUME_ID')}:{event['boundary']}:{int(p['attempts']) + 1}"
    try:
        result = _get_service().admit(
            operation_type=OperationType.BACKUP,
            idempotency_key=key,
            requested_by=RequestSource.SCHEDULE,
            requested_at=now,
            target_game_id=game,
            daily_boundary=event["boundary"],
        )
    except AdmissionConflict:
        return {"outcome": "CONFLICT"}
    if result.created:
        if result.lease_id is None:
            raise ValueError("BACKUP lease missing")
        _get_backup_launcher().start(
            operation_id=result.operation_id, lease_id=result.lease_id, started_at=now
        )
    return {
        "outcome": "ADMITTED" if result.created else "EXISTING",
        "operation_id": result.operation_id,
    }
