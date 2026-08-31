"""DynamoDB Stream/SQS adapter for Discord message delivery."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import replace
from typing import Protocol, cast

from wishicraft.discord_delivery import (
    DeliveryRecord,
    DeliveryStatus,
    DiscordDeliveryService,
    DiscordHttpClient,
    operation_nonce,
)


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def update_item(self, **kwargs: object) -> object: ...


class SsmApi(Protocol):
    def get_parameter(self, **kwargs: object) -> object: ...


class SqsApi(Protocol):
    def send_message(self, **kwargs: object) -> object: ...


class DynamoDeliveryStore:
    def __init__(self, api: DynamoApi, *, table_name: str) -> None:
        self._api = api
        self._table = table_name

    def load(self, operation_id: str) -> DeliveryRecord:
        response = self._api.get_item(
            TableName=self._table,
            Key={"operation_id": {"S": operation_id}},
            ConsistentRead=True,
        )
        item = response.get("Item") if isinstance(response, dict) else None
        if not isinstance(item, dict):
            raise ValueError("Discord delivery Operation does not exist")
        if _string(item, "operation_type") != "STATUS":
            if _string(item, "operation_type") not in {"START", "STOP"}:
                raise ValueError("unsupported Discord delivery Operation")
        operation_status = _string(item, "status")
        operation_type = _string(item, "operation_type")
        if operation_type == "STATUS" and operation_status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("Discord STATUS delivery requires a terminal Operation")
        discord = _map(item, "discord")
        result = _optional_map(item, "result") or {}
        delivery_status = _optional_string(discord, "delivery_status")
        return DeliveryRecord(
            operation_id=operation_id,
            operation_status=operation_status,
            channel_id=_string(discord, "channel_id"),
            projection=_plain_map(result),
            operation_type=operation_type,
            current_step=_string(item, "current_step"),
            source_revision=_integer(item, "progress_revision"),
            error_code=_optional_string(_optional_map(item, "error") or {}, "code"),
            delivery_status=(
                DeliveryStatus(delivery_status) if delivery_status is not None else None
            ),
            attempt_id=_optional_string(discord, "delivery_attempt_id"),
            attempt_count=_optional_int(discord, "delivery_attempt_count") or 0,
            first_attempt_epoch=_optional_int(discord, "delivery_first_attempt_epoch"),
            next_attempt_epoch=_optional_int(discord, "delivery_next_attempt_epoch"),
            outcome_unknown=_optional_bool(discord, "delivery_outcome_unknown") or False,
            message_id=_optional_string(discord, "message_id"),
            delivery_source_revision=_optional_int(discord, "delivery_source_revision"),
            delivered_revision=_optional_int(discord, "delivery_delivered_revision"),
        )

    def claim(
        self,
        record: DeliveryRecord,
        *,
        attempt_id: str,
        now_epoch: int,
    ) -> DeliveryRecord | None:
        same_source = record.delivery_source_revision == record.source_revision
        if same_source and record.delivery_status is DeliveryStatus.PENDING:
            return (
                replace(record, resumed_pending=True) if record.attempt_id == attempt_id else None
            )
        if (
            same_source
            and record.delivery_status is DeliveryStatus.RETRYABLE_FAILED
            and record.next_attempt_epoch is not None
            and now_epoch < record.next_attempt_epoch
        ):
            return None
        expected = (
            record.delivery_status.value
            if same_source and record.delivery_status is not None
            else None
        )
        next_count = record.attempt_count + 1 if same_source else 1
        names = {"#discord": "discord"}
        values: dict[str, object] = {
            ":pending": {"S": DeliveryStatus.PENDING.value},
            ":attempt": {"S": attempt_id},
            ":count": {"N": str(next_count)},
            ":now": {"N": str(now_epoch)},
            ":false": {"BOOL": False},
            ":delivery_id": {"S": operation_nonce(record.operation_id)},
            ":source_revision": {"N": str(record.source_revision)},
        }
        condition = "progress_revision = :source_revision"
        if same_source and expected is not None:
            condition += (
                " AND #discord.delivery_source_revision = :source_revision "
                "AND #discord.delivery_status = :expected"
            )
            values[":expected"] = {"S": expected}
        else:
            condition += (
                " AND (attribute_not_exists(#discord.delivery_source_revision) OR "
                "#discord.delivery_source_revision < :source_revision)"
            )
        first_attempt_update = (
            "#discord.delivery_first_attempt_epoch = if_not_exists("
            "#discord.delivery_first_attempt_epoch, :now), "
            if same_source
            else "#discord.delivery_first_attempt_epoch = :now, "
        )
        update = (
            "SET #discord.delivery_status = :pending, "
            "#discord.delivery_id = :delivery_id, "
            "#discord.delivery_source_revision = :source_revision, "
            "#discord.delivery_attempt_id = :attempt, "
            "#discord.delivery_attempt_count = :count, "
            + first_attempt_update
            + "#discord.delivery_outcome_unknown = :false "
            "REMOVE #discord.delivery_next_attempt_epoch, #discord.delivery_error_code"
        )
        try:
            self._api.update_item(
                TableName=self._table,
                Key={"operation_id": {"S": record.operation_id}},
                UpdateExpression=update,
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as error:
            if _conditional_failure(error):
                return None
            raise
        return DeliveryRecord(
            **{
                **record.__dict__,
                "delivery_status": DeliveryStatus.PENDING,
                "delivery_source_revision": record.source_revision,
                "attempt_id": attempt_id,
                "attempt_count": next_count,
                "first_attempt_epoch": (
                    record.first_attempt_epoch or now_epoch if same_source else now_epoch
                ),
                "next_attempt_epoch": None,
                "outcome_unknown": (record.outcome_unknown if same_source else False),
                "resumed_pending": same_source and record.delivery_status is DeliveryStatus.PENDING,
            }
        )

    def mark_delivered(
        self, record: DeliveryRecord, *, attempt_id: str, message_id: str, now_epoch: int
    ) -> None:
        self._finish(
            record,
            attempt_id=attempt_id,
            status=DeliveryStatus.DELIVERED,
            code=None,
            next_attempt_epoch=None,
            outcome_unknown=False,
            message_id=message_id,
            now_epoch=now_epoch,
        )

    def mark_failed(
        self,
        record: DeliveryRecord,
        *,
        attempt_id: str,
        status: DeliveryStatus,
        code: str,
        next_attempt_epoch: int | None,
        outcome_unknown: bool,
        now_epoch: int,
    ) -> None:
        self._finish(
            record,
            attempt_id=attempt_id,
            status=status,
            code=code,
            next_attempt_epoch=next_attempt_epoch,
            outcome_unknown=outcome_unknown,
            message_id=None,
            now_epoch=now_epoch,
        )

    def _finish(
        self,
        record: DeliveryRecord,
        *,
        attempt_id: str,
        status: DeliveryStatus,
        code: str | None,
        next_attempt_epoch: int | None,
        outcome_unknown: bool,
        message_id: str | None,
        now_epoch: int,
    ) -> None:
        values: dict[str, object] = {
            ":pending": {"S": DeliveryStatus.PENDING.value},
            ":attempt": {"S": attempt_id},
            ":status": {"S": status.value},
            ":code": {"S": code} if code is not None else {"NULL": True},
            ":next": (
                {"N": str(next_attempt_epoch)} if next_attempt_epoch is not None else {"NULL": True}
            ),
            ":unknown": {"BOOL": outcome_unknown},
            ":message": (
                {"S": message_id or record.message_id}
                if message_id is not None or record.message_id is not None
                else {"NULL": True}
            ),
            ":source_revision": {"N": str(record.source_revision)},
            ":delivered_revision": (
                {"N": str(record.source_revision)}
                if status is DeliveryStatus.DELIVERED
                else (
                    {"N": str(record.delivered_revision)}
                    if record.delivered_revision is not None
                    else {"NULL": True}
                )
            ),
            ":now": {"N": str(now_epoch)},
        }
        self._api.update_item(
            TableName=self._table,
            Key={"operation_id": {"S": record.operation_id}},
            UpdateExpression=(
                "SET #discord.delivery_status = :status, "
                "#discord.delivery_error_code = :code, "
                "#discord.delivery_next_attempt_epoch = :next, "
                "#discord.delivery_outcome_unknown = :unknown, "
                "#discord.message_id = :message, "
                "#discord.delivery_delivered_revision = :delivered_revision, "
                "#discord.delivery_updated_epoch = :now"
            ),
            ConditionExpression=(
                "progress_revision = :source_revision AND "
                "#discord.delivery_source_revision = :source_revision AND "
                "#discord.delivery_status = :pending AND #discord.delivery_attempt_id = :attempt"
            ),
            ExpressionAttributeNames={"#discord": "discord"},
            ExpressionAttributeValues=values,
        )


class ParameterToken:
    def __init__(self, api: SsmApi, *, parameter_name: str) -> None:
        self._api = api
        self._name = parameter_name
        self._value: str | None = None

    def get(self) -> str:
        if self._value is None:
            response = self._api.get_parameter(Name=self._name, WithDecryption=True)
            parameter = response.get("Parameter") if isinstance(response, dict) else None
            value = parameter.get("Value") if isinstance(parameter, dict) else None
            if not isinstance(value, str) or not value:
                raise RuntimeError("Discord Bot Token is unavailable")
            self._value = value
        return self._value


class QueueRetry:
    def __init__(self, api: SqsApi, *, queue_url: str) -> None:
        self._api = api
        self._queue_url = queue_url

    def schedule(self, *, operation_id: str, source_revision: int, delay_seconds: int) -> None:
        self._api.send_message(
            QueueUrl=self._queue_url,
            DelaySeconds=delay_seconds,
            MessageBody=json.dumps(
                {
                    "schema_version": 1,
                    "operation_id": operation_id,
                    "source_revision": source_revision,
                },
                separators=(",", ":"),
            ),
        )


class LazyMessages:
    def __init__(self, token: ParameterToken) -> None:
        self._token = token
        self._client: DiscordHttpClient | None = None

    def create(self, *, channel_id: str, nonce: str, content: str) -> str:
        if self._client is None:
            self._client = DiscordHttpClient(token=self._token.get())
        return self._client.create(channel_id=channel_id, nonce=nonce, content=content)

    def edit(self, *, channel_id: str, message_id: str, content: str) -> str:
        if self._client is None:
            self._client = DiscordHttpClient(token=self._token.get())
        return self._client.edit(channel_id=channel_id, message_id=message_id, content=content)


_service: DiscordDeliveryService | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    service = _get_service()
    records = _delivery_events(event)
    for operation_id, source_revision, attempt_id in records:
        service.deliver(
            operation_id=operation_id,
            source_revision=source_revision,
            attempt_id=attempt_id,
        )
    return {"batchItemFailures": []}


def _delivery_events(event: object) -> tuple[tuple[str, int, str], ...]:
    if (
        not isinstance(event, dict)
        or not isinstance(event.get("Records"), list)
        or not event["Records"]
    ):
        raise ValueError("invalid Discord delivery event")
    events: list[tuple[str, int, str]] = []
    for record in event["Records"]:
        if not isinstance(record, dict):
            raise ValueError("invalid Discord delivery event")
        source = record.get("eventSource")
        event_id = record.get("eventID")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("invalid Discord delivery event")
        if source == "aws:dynamodb" and record.get("eventName") in {"INSERT", "MODIFY"}:
            dynamodb = record.get("dynamodb")
            image = dynamodb.get("NewImage") if isinstance(dynamodb, dict) else None
            if not isinstance(image, dict):
                raise ValueError("invalid Discord delivery event")
            operation_id = _string(image, "operation_id")
            operation_type = _string(image, "operation_type")
            operation_status = _string(image, "status")
            if operation_type not in {"STATUS", "START", "STOP"}:
                continue
            if operation_type == "STATUS" and operation_status not in {"SUCCEEDED", "FAILED"}:
                continue
            if operation_type in {"START", "STOP"} and operation_status not in {
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "TIMED_OUT",
                "CANCELLED",
            }:
                raise ValueError("invalid Discord delivery event")
            source_revision = _integer(image, "progress_revision")
            if record.get("eventName") == "MODIFY":
                old_image = dynamodb.get("OldImage") if isinstance(dynamodb, dict) else None
                if not isinstance(old_image, dict):
                    raise ValueError("invalid Discord delivery event")
                if _optional_int(old_image, "progress_revision") == source_revision:
                    continue
            requested_by = _map(image, "requested_by")
            discord = _map(image, "discord")
            if (
                _string(requested_by, "source") != "DISCORD"
                or _optional_string(discord, "channel_id") is None
            ):
                continue
            events.append((operation_id, source_revision, f"ddb:{event_id}"))
        elif source == "aws:sqs":
            body = record.get("body")
            try:
                payload = json.loads(body) if isinstance(body, str) else None
            except json.JSONDecodeError as error:
                raise ValueError("invalid Discord delivery event") from error
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema_version", "operation_id", "source_revision"}
                or payload.get("schema_version") != 1
            ):
                raise ValueError("invalid Discord delivery event")
            sqs_operation_id = payload.get("operation_id")
            sqs_revision = payload.get("source_revision")
            if (
                not isinstance(sqs_operation_id, str)
                or not sqs_operation_id
                or not isinstance(sqs_revision, int)
                or isinstance(sqs_revision, bool)
                or sqs_revision < 0
            ):
                raise ValueError("invalid Discord delivery event")
            events.append((sqs_operation_id, sqs_revision, f"sqs:{event_id}"))
        else:
            raise ValueError("invalid Discord delivery event")
    return tuple(events)


def _get_service() -> DiscordDeliveryService:
    global _service
    if _service is None:
        boto3 = importlib.import_module("boto3")
        region = _required_environment("AWS_REGION")
        dynamodb = cast(DynamoApi, boto3.client("dynamodb", region_name=region))
        ssm = cast(SsmApi, boto3.client("ssm", region_name=region))
        sqs = cast(SqsApi, boto3.client("sqs", region_name=region))
        _service = DiscordDeliveryService(
            DynamoDeliveryStore(dynamodb, table_name=_required_environment("OPERATIONS_TABLE")),
            LazyMessages(
                ParameterToken(
                    ssm, parameter_name=_required_environment("BOT_TOKEN_PARAMETER_NAME")
                )
            ),
            QueueRetry(sqs, queue_url=_required_environment("DELIVERY_RETRY_QUEUE_URL")),
        )
    return _service


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _map(item: dict[str, object], name: str) -> dict[str, object]:
    raw = item.get(name)
    value = raw.get("M") if isinstance(raw, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"malformed {name}")
    return value


def _string(item: dict[str, object], name: str) -> str:
    raw = item.get(name)
    value = raw.get("S") if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value:
        raise ValueError(f"malformed {name}")
    return value


def _optional_string(item: dict[str, object], name: str) -> str | None:
    raw = item.get(name)
    if raw is None or raw == {"NULL": True}:
        return None
    return _string(item, name)


def _optional_int(item: dict[str, object], name: str) -> int | None:
    raw = item.get(name)
    if raw is None or raw == {"NULL": True}:
        return None
    value = raw.get("N") if isinstance(raw, dict) else None
    if not isinstance(value, str):
        raise ValueError(f"malformed {name}")
    return int(value)


def _integer(item: dict[str, object], name: str) -> int:
    value = _optional_int(item, name)
    if value is None or value < 0:
        raise ValueError(f"malformed {name}")
    return value


def _optional_map(item: dict[str, object], name: str) -> dict[str, object] | None:
    raw = item.get(name)
    if raw is None or raw == {"NULL": True}:
        return None
    return _map(item, name)


def _optional_bool(item: dict[str, object], name: str) -> bool | None:
    raw = item.get(name)
    if raw is None or raw == {"NULL": True}:
        return None
    value = raw.get("BOOL") if isinstance(raw, dict) else None
    if not isinstance(value, bool):
        raise ValueError(f"malformed {name}")
    return value


def _plain_map(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in item.items():
        if not isinstance(value, dict):
            raise ValueError("malformed projection")
        if "S" in value and isinstance(value["S"], str):
            result[name] = value["S"]
        elif "BOOL" in value and isinstance(value["BOOL"], bool):
            result[name] = value["BOOL"]
        elif value == {"NULL": True}:
            result[name] = None
        elif "N" in value and isinstance(value["N"], str):
            result[name] = int(value["N"])
        else:
            raise ValueError("malformed projection")
    return result


def _conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None)
    detail = response.get("Error") if isinstance(response, dict) else None
    return isinstance(detail, dict) and detail.get("Code") == "ConditionalCheckFailedException"
