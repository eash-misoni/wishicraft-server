"""Bounded, nonce-deduplicated Discord warning delivery for D-093 intents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from wishicraft.discord_delivery import (
    MAX_DELIVERY_ATTEMPTS,
    DiscordFailure,
    DiscordMessages,
    operation_nonce,
)

WARNING_TEXT = "Minecraft will stop automatically in about 5 minutes if nobody connects."


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def update_item(self, **kwargs: object) -> object: ...


class WarningDelivery:
    def __init__(self, dynamodb: DynamoApi, messages: DiscordMessages, *, table_name: str) -> None:
        self.ddb, self.messages, self.table = dynamodb, messages, table_name

    def deliver(self, *, game_id: str, intent_id: str, now: datetime) -> dict[str, object]:
        item = self._load(game_id, intent_id)
        state = _text(item, "warning_delivery_state")
        if state in {"DELIVERED", "FAILED"}:
            return {"state": state, "created": False}
        attempts = _integer(item, "warning_attempt_count")
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            self._mark_failed(game_id, intent_id, attempts, "DISCORD_WARNING_RETRY_EXHAUSTED", now)
            return {"state": "FAILED", "created": False}
        next_attempt = attempts + 1
        try:
            self.ddb.update_item(
                TableName=self.table,
                Key=_key(game_id, intent_id),
                UpdateExpression=(
                    "SET warning_delivery_state = :pending, "
                    "warning_attempt_count = :count, updated_at = :now"
                ),
                ConditionExpression=(
                    "#status = :warning_pending AND warning_attempt_count = :previous AND "
                    "warning_delivery_state IN (:not_started, :retryable)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":pending": {"S": "PENDING"},
                    ":count": {"N": str(next_attempt)},
                    ":previous": {"N": str(attempts)},
                    ":not_started": {"S": "NOT_STARTED"},
                    ":retryable": {"S": "RETRYABLE_FAILED"},
                    ":warning_pending": {"S": "WARNING_PENDING"},
                    ":now": {"S": _time(now)},
                },
            )
        except Exception as error:
            if _conditional(error):
                return {
                    "state": _text(self._load(game_id, intent_id), "warning_delivery_state"),
                    "created": False,
                }
            raise
        try:
            message_id = self.messages.create(
                channel_id=_text(item, "channel_id"),
                nonce=operation_nonce(_text(item, "warning_delivery_id")),
                content=WARNING_TEXT,
            )
        except DiscordFailure as failure:
            retry = (
                failure.retryable
                and not failure.outcome_unknown
                and next_attempt < MAX_DELIVERY_ATTEMPTS
            )
            state = "RETRYABLE_FAILED" if retry else "FAILED"
            try:
                self.ddb.update_item(
                    TableName=self.table,
                    Key=_key(game_id, intent_id),
                    UpdateExpression=(
                        "SET warning_delivery_state = :state, "
                        "warning_delivery_error = :code, updated_at = :now"
                    ),
                    ConditionExpression=(
                        "#status = :warning_pending AND "
                        "warning_delivery_state = :pending AND "
                        "warning_attempt_count = :count"
                    ),
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":state": {"S": state},
                        ":code": {"S": failure.code},
                        ":now": {"S": _time(now)},
                        ":pending": {"S": "PENDING"},
                        ":count": {"N": str(next_attempt)},
                        ":warning_pending": {"S": "WARNING_PENDING"},
                    },
                )
            except Exception as error:
                if not _conditional(error):
                    raise
            return {"state": state, "created": False}
        try:
            self.ddb.update_item(
                TableName=self.table,
                Key=_key(game_id, intent_id),
                UpdateExpression=(
                    "SET warning_delivery_state = :delivered, warning_delivered_at = :now, "
                    "warning_message_id = :message, #status = :delivered_status, "
                    "updated_at = :now"
                ),
                ConditionExpression=(
                    "#status = :warning_pending AND "
                    "warning_delivery_state = :pending AND warning_attempt_count = :count"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":delivered": {"S": "DELIVERED"},
                    ":now": {"S": _time(now)},
                    ":message": {"S": message_id},
                    ":delivered_status": {"S": "WARNING_DELIVERED"},
                    ":warning_pending": {"S": "WARNING_PENDING"},
                    ":pending": {"S": "PENDING"},
                    ":count": {"N": str(next_attempt)},
                },
            )
        except Exception as error:
            if not _conditional(error):
                raise
            return {
                "state": _text(self._load(game_id, intent_id), "warning_delivery_state"),
                "created": True,
            }
        return {"state": "DELIVERED", "created": True}

    def _load(self, game_id: str, intent_id: str) -> dict[str, object]:
        response = self.ddb.get_item(
            TableName=self.table, Key=_key(game_id, intent_id), ConsistentRead=True
        )
        raw = response.get("Item") if isinstance(response, dict) else None
        if not isinstance(raw, dict):
            raise RuntimeError("automatic STOP intent is missing")
        return {str(name): _deserialize(value) for name, value in raw.items()}

    def _mark_failed(
        self, game_id: str, intent_id: str, attempts: int, code: str, now: datetime
    ) -> None:
        self.ddb.update_item(
            TableName=self.table,
            Key=_key(game_id, intent_id),
            UpdateExpression=(
                "SET warning_delivery_state = :failed, warning_delivery_error = :code, "
                "#status = :status, updated_at = :now"
            ),
            ConditionExpression="warning_attempt_count = :attempts",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":failed": {"S": "FAILED"},
                ":code": {"S": code},
                ":status": {"S": "WARNING_FAILED"},
                ":now": {"S": _time(now)},
                ":attempts": {"N": str(attempts)},
            },
        )


def _key(game_id: str, intent_id: str) -> dict[str, object]:
    return {"game_id": {"S": game_id}, "intent_id": {"S": intent_id}}


def _text(item: dict[str, object], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"invalid {name}")
    return value


def _integer(item: dict[str, object], name: str) -> int:
    value = item.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"invalid {name}")
    return value


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _conditional(error: Exception) -> bool:
    response = getattr(error, "response", None)
    detail = response.get("Error") if isinstance(response, dict) else None
    return isinstance(detail, dict) and detail.get("Code") == "ConditionalCheckFailedException"


def _deserialize(value: object) -> object:
    if not isinstance(value, dict):
        raise RuntimeError("malformed DynamoDB attribute")
    if isinstance(value.get("S"), str):
        return value["S"]
    if isinstance(value.get("N"), str):
        return int(value["N"])
    if value.get("NULL") is True:
        return None
    raise RuntimeError("malformed DynamoDB attribute")
