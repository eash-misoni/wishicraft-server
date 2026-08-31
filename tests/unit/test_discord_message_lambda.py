from __future__ import annotations

import json
from typing import cast

import pytest

from wishicraft import discord_message_lambda
from wishicraft.discord_delivery import DeliveryStatus


def attribute(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": {key: attribute(item) for key, item in value.items()}}
    raise TypeError


def operation_item() -> dict[str, object]:
    return {
        "operation_id": {"S": "op-status-001"},
        "operation_type": {"S": "STATUS"},
        "status": {"S": "SUCCEEDED"},
        "discord": attribute(
            {
                "guild_id": "1251169327554625757",
                "channel_id": "1531883129525244015",
                "interaction_id": "1532000000000000001",
                "message_id": None,
            }
        ),
        "result": attribute(
            {
                "schema_version": 1,
                "kind": "STATUS",
                "status": "stopped",
                "ready": False,
                "health": "healthy",
                "endpoint": None,
                "observed_at": "2026-08-31T00:00:00.000000Z",
                "summary": "The server is stopped.",
            }
        ),
    }


class Dynamo:
    def __init__(self) -> None:
        self.item = operation_item()
        self.updates: list[dict[str, object]] = []

    def get_item(self, **kwargs: object) -> object:
        return {"Item": self.item}

    def update_item(self, **kwargs: object) -> object:
        self.updates.append(kwargs)
        return {}


class ConditionalFailure(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def test_store_claim_and_delivery_metadata_are_conditional_and_separate() -> None:
    api = Dynamo()
    store = discord_message_lambda.DynamoDeliveryStore(api, table_name="operations")
    record = store.load("op-status-001")
    claimed = store.claim(record, attempt_id="ddb:event-1", now_epoch=100)
    assert claimed is not None
    store.mark_delivered(
        claimed, attempt_id="ddb:event-1", message_id="1532999999999999999", now_epoch=101
    )
    assert len(api.updates) == 2
    assert "#status IN (:succeeded, :failed)" in str(api.updates[0]["ConditionExpression"])
    assert "delivery_attempt_id = :attempt" in str(api.updates[1]["ConditionExpression"])
    values = cast(dict[str, object], api.updates[1]["ExpressionAttributeValues"])
    assert values[":status"] == {"S": DeliveryStatus.DELIVERED.value}
    rendered = json.dumps(api.updates)
    assert "result =" not in rendered
    assert "desired" not in rendered
    assert "lock" not in rendered


def test_conditional_claim_race_loses_without_delivery_side_effect() -> None:
    class RacingDynamo(Dynamo):
        def update_item(self, **kwargs: object) -> object:
            raise ConditionalFailure

    store = discord_message_lambda.DynamoDeliveryStore(RacingDynamo(), table_name="operations")
    assert store.claim(store.load("op-status-001"), attempt_id="worker-2", now_epoch=100) is None


def test_stream_and_sqs_event_preserve_operation_identity() -> None:
    stream = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "event-1",
                "dynamodb": {
                    "NewImage": {
                        "operation_id": {"S": "op-status-001"},
                        "operation_type": {"S": "STATUS"},
                        "status": {"S": "SUCCEEDED"},
                        "requested_by": {"M": {"source": {"S": "DISCORD"}}},
                        "discord": {"M": {"channel_id": {"S": "1531883129525244015"}}},
                    }
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(stream) == (("op-status-001", "ddb:event-1"),)
    sqs = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "eventID": "message-1",
                "body": '{"schema_version":1,"operation_id":"op-status-001"}',
            }
        ]
    }
    assert discord_message_lambda._delivery_events(sqs) == (("op-status-001", "sqs:message-1"),)


def test_non_discord_terminal_status_is_not_delivered() -> None:
    stream = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "event-cli",
                "dynamodb": {
                    "NewImage": {
                        "operation_id": {"S": "op-cli-status"},
                        "operation_type": {"S": "STATUS"},
                        "status": {"S": "SUCCEEDED"},
                        "requested_by": {"M": {"source": {"S": "CLI"}}},
                        "discord": {"M": {"channel_id": {"NULL": True}}},
                    }
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(stream) == ()


@pytest.mark.parametrize(
    "event",
    [
        {"Records": []},
        {
            "Records": [
                {
                    "eventSource": "aws:dynamodb",
                    "eventName": "INSERT",
                    "eventID": "event-1",
                }
            ]
        },
        {
            "Records": [
                {
                    "eventSource": "aws:sqs",
                    "eventID": "message-1",
                    "body": '{"schema_version":1,"operation_id":"op","extra":true}',
                }
            ]
        },
    ],
)
def test_event_parser_fails_closed(event: object) -> None:
    with pytest.raises(ValueError, match="invalid Discord delivery event"):
        discord_message_lambda._delivery_events(event)


def test_parameter_token_fetches_exact_parameter_without_logging_value() -> None:
    class Ssm:
        calls: list[dict[str, object]] = []

        def get_parameter(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            return {"Parameter": {"Value": "synthetic-unit-token"}}

    api = Ssm()
    token = discord_message_lambda.ParameterToken(
        api, parameter_name="/wishicraft/dev/secret/discord-bot-token"
    )
    assert token.get() == "synthetic-unit-token"
    assert token.get() == "synthetic-unit-token"
    assert api.calls == [
        {
            "Name": "/wishicraft/dev/secret/discord-bot-token",
            "WithDecryption": True,
        }
    ]
