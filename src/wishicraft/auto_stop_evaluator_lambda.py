"""Scheduled D-093 candidate evaluator; it never performs STOP mutations."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from wishicraft.auto_stop import (
    AutoStopIntentStatus,
    deterministic_stop_idempotency_key,
    evaluate_candidate,
)
from wishicraft.runtime_heartbeat_producer import _decode

ACTIVE_STATUSES = {
    AutoStopIntentStatus.WARNING_PENDING.value,
    AutoStopIntentStatus.WARNING_DELIVERED.value,
}


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def put_item(self, **kwargs: object) -> object: ...
    def query(self, **kwargs: object) -> object: ...
    def update_item(self, **kwargs: object) -> object: ...


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class CloudWatchApi(Protocol):
    def put_metric_data(self, **kwargs: object) -> object: ...


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class Evaluator:
    def __init__(
        self,
        dynamodb: DynamoApi,
        lambdas: LambdaApi,
        *,
        games_table: str,
        heartbeats_table: str,
        system_state_table: str,
        intents_table: str,
        system_id: str,
        game_id: str,
        runtime_id: str,
        channel_id: str,
        message_function: str,
        admission_function: str,
        cloudwatch: CloudWatchApi | None = None,
        metric_namespace: str = "Wishicraft/ControlPlane",
        stage: str = "dev",
    ) -> None:
        self.ddb, self.lambdas = dynamodb, lambdas
        self.games_table, self.heartbeats_table = games_table, heartbeats_table
        self.system_state_table, self.intents_table = system_state_table, intents_table
        self.system_id, self.game_id, self.runtime_id = system_id, game_id, runtime_id
        self.channel_id = channel_id
        self.message_function, self.admission_function = message_function, admission_function
        self.cloudwatch, self.metric_namespace, self.stage = cloudwatch, metric_namespace, stage

    def evaluate(self, *, now: datetime) -> dict[str, object]:
        game = self._get(self.games_table, {"game_id": {"S": self.game_id}})
        state = self._get(self.system_state_table, {"system_id": {"S": self.system_id}})
        heartbeat_item = self._raw_get(self.heartbeats_table, {"system_id": {"S": self.system_id}})
        heartbeat = _decode(heartbeat_item) if heartbeat_item else None
        idle_minutes = _idle_minutes(game)
        unsafe_state = (
            state.get("health") != "HEALTHY"
            or state.get("discrepancies") not in ([], None)
            or state.get("observation_errors") not in ([], None)
        )
        candidate = evaluate_candidate(
            heartbeat=heartbeat,
            game_id=self.game_id,
            runtime_id=self.runtime_id,
            idle_timeout_minutes=idle_minutes,
            desired_state=_text(state, "desired_state"),
            now=now,
        )
        if unsafe_state:
            candidate = type(candidate)(False, "CONTROL_PLANE_UNSAFE")
        if not candidate.eligible or heartbeat is None or heartbeat.empty_since is None:
            self._cancel_active(reason=candidate.reason, now=now)
            return {"candidate": False, "reason": candidate.reason}
        assert candidate.intent_id is not None
        self._cancel_active(reason="EMPTY_PERIOD_CHANGED", now=now, keep=candidate.intent_id)
        intent = self._ensure_intent(
            intent_id=candidate.intent_id,
            boot_id=heartbeat.boot_id,
            run_id=heartbeat.run_id,
            process_id=heartbeat.process_id,
            empty_since=heartbeat.empty_since,
            idle_minutes=idle_minutes,
            now=now,
        )
        delivery = _text(intent, "warning_delivery_state")
        if delivery in {"NOT_STARTED", "RETRYABLE_FAILED"}:
            self._invoke(
                self.message_function,
                {
                    "schema_version": 1,
                    "operation": "deliver_auto_stop_warning",
                    "intent_id": candidate.intent_id,
                    "game_id": self.game_id,
                },
            )
            intent = self._get_intent(candidate.intent_id)
            delivery = _text(intent, "warning_delivery_state")
        if delivery == "FAILED":
            self._set_status(candidate.intent_id, AutoStopIntentStatus.WARNING_FAILED, now)
            self._metric("AutoStopWarningBlocked")
            return {"candidate": True, "reason": "WARNING_FAILED", "intent_id": candidate.intent_id}
        delivered_at = _optional_time(intent, "warning_delivered_at")
        eligible_at = max(
            heartbeat.empty_since.timestamp() + idle_minutes * 60,
            delivered_at.timestamp() + 300 if delivered_at is not None else float("inf"),
        )
        if delivered_at is None or now.timestamp() < eligible_at:
            return {"candidate": True, "reason": "WARNING_WAIT", "intent_id": candidate.intent_id}
        if not self._claim_admission(candidate.intent_id, now):
            return {
                "candidate": True,
                "reason": "ADMISSION_ALREADY_ATTEMPTED",
                "intent_id": candidate.intent_id,
            }
        response = self._invoke(
            self.admission_function,
            {
                "schema_version": 1,
                "operation": "admit",
                "operation_type": "STOP",
                "idempotency_key": deterministic_stop_idempotency_key(candidate.intent_id),
                "requested_by": "SCHEDULE",
                "auto_stop_intent_id": candidate.intent_id,
            },
        )
        operation_id = response.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise RuntimeError("automatic STOP admission outcome is invalid")
        self._metric("ScheduledStopAdmission")
        self.ddb.update_item(
            TableName=self.intents_table,
            Key=_intent_key(self.game_id, candidate.intent_id),
            UpdateExpression=(
                "SET #status = :requested, stop_operation_id = :operation, updated_at = :now"
            ),
            ConditionExpression="#status = :attempted",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":requested": {"S": AutoStopIntentStatus.STOP_REQUESTED.value},
                ":attempted": {"S": AutoStopIntentStatus.ADMISSION_ATTEMPTED.value},
                ":operation": {"S": operation_id},
                ":now": {"S": _time(now)},
            },
        )
        return {
            "candidate": True,
            "reason": "STOP_REQUESTED",
            "intent_id": candidate.intent_id,
            "operation_id": operation_id,
        }

    def _ensure_intent(
        self,
        *,
        intent_id: str,
        boot_id: str,
        run_id: str | None,
        process_id: str | None,
        empty_since: datetime,
        idle_minutes: int,
        now: datetime,
    ) -> dict[str, object]:
        item = {
            "game_id": self.game_id,
            "intent_id": intent_id,
            "schema_version": 1,
            "boot_id": boot_id,
            "run_id": run_id,
            "process_id": process_id,
            "empty_since": _time(empty_since),
            "idle_timeout_minutes": idle_minutes,
            "warning_lead_minutes": 5,
            "warning_delivery_id": _warning_id(intent_id),
            "warning_delivery_state": "NOT_STARTED",
            "warning_delivered_at": None,
            "warning_attempt_count": 0,
            "channel_id": self.channel_id,
            "status": AutoStopIntentStatus.WARNING_PENDING.value,
            "created_at": _time(now),
            "updated_at": _time(now),
            "block_reason": None,
        }
        try:
            self.ddb.put_item(
                TableName=self.intents_table,
                Item={key: _serialize(value) for key, value in item.items()},
                ConditionExpression=(
                    "attribute_not_exists(game_id) AND attribute_not_exists(intent_id)"
                ),
            )
        except Exception as error:
            if not _conditional(error):
                raise
        current = self._get_intent(intent_id)
        for name in (
            "game_id",
            "intent_id",
            "boot_id",
            "run_id",
            "process_id",
            "empty_since",
            "idle_timeout_minutes",
            "warning_lead_minutes",
            "warning_delivery_id",
            "channel_id",
        ):
            if current.get(name) != item[name]:
                raise RuntimeError("automatic STOP intent identity conflict")
        return current

    def _cancel_active(self, *, reason: str, now: datetime, keep: str | None = None) -> None:
        response = self.ddb.query(
            TableName=self.intents_table,
            KeyConditionExpression="game_id = :game",
            ExpressionAttributeValues={":game": {"S": self.game_id}},
            ConsistentRead=True,
        )
        items = response.get("Items") if isinstance(response, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("automatic STOP intent inventory is incomplete")
        for raw in items:
            item = _plain(raw)
            if item.get("status") not in ACTIVE_STATUSES:
                continue
            if item.get("intent_id") == keep:
                continue
            self.ddb.update_item(
                TableName=self.intents_table,
                Key=_intent_key(self.game_id, _text(item, "intent_id")),
                UpdateExpression=(
                    "SET #status = :cancelled, block_reason = :reason, updated_at = :now"
                ),
                ConditionExpression="#status = :pending OR #status = :delivered",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":cancelled": {"S": AutoStopIntentStatus.CANCELLED.value},
                    ":pending": {"S": AutoStopIntentStatus.WARNING_PENDING.value},
                    ":delivered": {"S": AutoStopIntentStatus.WARNING_DELIVERED.value},
                    ":reason": {"S": reason},
                    ":now": {"S": _time(now)},
                },
            )

    def _claim_admission(self, intent_id: str, now: datetime) -> bool:
        try:
            self.ddb.update_item(
                TableName=self.intents_table,
                Key=_intent_key(self.game_id, intent_id),
                UpdateExpression=(
                    "SET #status = :attempted, admission_attempted_at = :now, updated_at = :now"
                ),
                ConditionExpression="#status = :delivered",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":attempted": {"S": AutoStopIntentStatus.ADMISSION_ATTEMPTED.value},
                    ":delivered": {"S": AutoStopIntentStatus.WARNING_DELIVERED.value},
                    ":now": {"S": _time(now)},
                },
            )
            return True
        except Exception as error:
            if _conditional(error):
                return False
            raise

    def _set_status(self, intent_id: str, status: AutoStopIntentStatus, now: datetime) -> None:
        self.ddb.update_item(
            TableName=self.intents_table,
            Key=_intent_key(self.game_id, intent_id),
            UpdateExpression="SET #status = :status, updated_at = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": {"S": status.value}, ":now": {"S": _time(now)}},
        )

    def _get_intent(self, intent_id: str) -> dict[str, object]:
        return self._get(self.intents_table, _intent_key(self.game_id, intent_id))

    def _metric(self, name: str) -> None:
        if self.cloudwatch is None:
            return
        self.cloudwatch.put_metric_data(
            Namespace=self.metric_namespace,
            MetricData=[
                {
                    "MetricName": name,
                    "Dimensions": [{"Name": "Stage", "Value": self.stage}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )

    def _raw_get(self, table: str, key: dict[str, object]) -> dict[str, Any] | None:
        response = self.ddb.get_item(TableName=table, Key=key, ConsistentRead=True)
        item = response.get("Item") if isinstance(response, dict) else None
        if item is None:
            return None
        if not isinstance(item, dict):
            raise RuntimeError("malformed DynamoDB response")
        return cast(dict[str, Any], item)

    def _get(self, table: str, key: dict[str, object]) -> dict[str, object]:
        item = self._raw_get(table, key)
        if item is None:
            raise RuntimeError("required control-plane record is missing")
        return _plain(item)

    def _invoke(self, function: str, payload: dict[str, object]) -> dict[str, object]:
        response = self.lambdas.invoke(
            FunctionName=function,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, separators=(",", ":")).encode(),
        )
        body = response.get("Payload") if isinstance(response, dict) else None
        raw = cast(Any, body).read() if body is not None and hasattr(body, "read") else body
        if response.get("FunctionError") if isinstance(response, dict) else True:
            raise RuntimeError("automatic STOP downstream invocation failed")
        try:
            value = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("automatic STOP downstream response is invalid") from error
        if not isinstance(value, dict):
            raise RuntimeError("automatic STOP downstream response is invalid")
        return cast(dict[str, object], value)


def handler(event: object, context: object) -> dict[str, object]:
    del context
    if event != {"schema_version": 1, "operation": "evaluate_auto_stop"}:
        raise ValueError("invalid automatic STOP evaluation")
    result = _runtime().evaluate(now=datetime.now(UTC))
    print(json.dumps({"event": "auto_stop_evaluation", **result}, separators=(",", ":")))
    return result


_evaluator: Evaluator | None = None


def _runtime() -> Evaluator:
    global _evaluator
    if _evaluator is None:
        boto3 = importlib.import_module("boto3")
        region = _env("AWS_REGION")
        _evaluator = Evaluator(
            cast(DynamoApi, boto3.client("dynamodb", region_name=region)),
            cast(LambdaApi, boto3.client("lambda", region_name=region)),
            games_table=_env("GAMES_TABLE"),
            heartbeats_table=_env("RUNTIME_HEARTBEATS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            intents_table=_env("AUTO_STOP_INTENTS_TABLE"),
            system_id=_env("SYSTEM_ID"),
            game_id=_env("GAME_ID"),
            runtime_id="wishicraft-host-runtime",
            channel_id=_env("DISCORD_OPERATION_CHANNEL_ID"),
            message_function=_env("DISCORD_MESSAGE_FUNCTION_NAME"),
            admission_function=_env("ADMISSION_FUNCTION_NAME"),
            cloudwatch=cast(CloudWatchApi, boto3.client("cloudwatch", region_name=region)),
            metric_namespace=_env("METRIC_NAMESPACE"),
            stage=_env("STAGE"),
        )
    return _evaluator


def _intent_key(game_id: str, intent_id: str) -> dict[str, object]:
    return {"game_id": {"S": game_id}, "intent_id": {"S": intent_id}}


def _plain(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise RuntimeError("malformed DynamoDB item")
    return {str(key): _deserialize(value) for key, value in item.items()}


def _idle_minutes(game: dict[str, object]) -> int:
    runtime = game.get("runtime")
    value = runtime.get("idle_shutdown_minutes") if isinstance(runtime, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 5:
        raise RuntimeError("invalid per-Game idle shutdown policy")
    return value


def _text(item: dict[str, object], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"invalid {name}")
    return value


def _optional_time(item: dict[str, object], name: str) -> datetime | None:
    value = item.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"invalid {name}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeError(f"invalid {name}")
    return parsed.astimezone(UTC)


def _warning_id(intent_id: str) -> str:
    return "asw-" + hashlib.sha256(intent_id.encode()).hexdigest()[:32]


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _conditional(error: Exception) -> bool:
    response = getattr(error, "response", None)
    detail = response.get("Error") if isinstance(response, dict) else None
    return isinstance(detail, dict) and detail.get("Code") == "ConditionalCheckFailedException"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _serialize(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, int):
        return {"N": str(value)}
    raise TypeError("unsupported automatic STOP attribute")


def _deserialize(value: object) -> object:
    if not isinstance(value, dict):
        raise RuntimeError("malformed DynamoDB attribute")
    if isinstance(value.get("S"), str):
        return value["S"]
    if isinstance(value.get("N"), str):
        return int(value["N"])
    if isinstance(value.get("BOOL"), bool):
        return value["BOOL"]
    if value.get("NULL") is True:
        return None
    if isinstance(value.get("L"), list):
        return [_deserialize(item) for item in value["L"]]
    if isinstance(value.get("M"), dict):
        return {str(key): _deserialize(item) for key, item in value["M"].items()}
    raise RuntimeError("malformed DynamoDB attribute")
