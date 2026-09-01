from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from wishicraft import discord_message_lambda
from wishicraft.discord_delivery import (
    DeliveryRecord,
    DeliveryStatus,
    DiscordDeliveryService,
    operation_nonce,
)


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
        "current_step": {"S": "ADMITTED"},
        "progress_revision": {"N": "1"},
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


class CompletionRacingDynamo(Dynamo):
    def __init__(self, current_item: dict[str, object]) -> None:
        super().__init__()
        self.item = current_item
        self.completion_calls = 0

    def update_item(self, **kwargs: object) -> object:
        self.updates.append(kwargs)
        self.completion_calls += 1
        raise ConditionalFailure


def delivery_item(
    *,
    progress_revision: int,
    delivery_source_revision: int,
    delivery_status: str,
    delivered_revision: int | None,
    message_id: str = "1532999999999999999",
    delivery_id: str | None = None,
    attempt_id: str = "ddb:newer",
) -> dict[str, object]:
    item = operation_item()
    item["operation_type"] = {"S": "STOP"}
    item["status"] = {"S": "RUNNING"}
    item["progress_revision"] = {"N": str(progress_revision)}
    item["discord"] = attribute(
        {
            "guild_id": "1251169327554625757",
            "channel_id": "1531883129525244015",
            "interaction_id": "1532000000000000001",
            "message_id": message_id,
            "delivery_id": delivery_id or operation_nonce("op-status-001"),
            "delivery_source_revision": delivery_source_revision,
            "delivery_status": delivery_status,
            "delivery_attempt_id": attempt_id,
            "delivery_attempt_count": 1,
            "delivery_delivered_revision": delivered_revision,
            "delivery_outcome_unknown": False,
        }
    )
    return item


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
    assert "progress_revision = :source_revision" in str(api.updates[0]["ConditionExpression"])
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


def test_production_stale_completion_race_is_noop_after_newer_revision_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message_id = "1532999999999999999"
    old = delivery_item(
        progress_revision=4,
        delivery_source_revision=3,
        delivery_status="DELIVERED",
        delivered_revision=3,
    )
    newer = delivery_item(
        progress_revision=5,
        delivery_source_revision=5,
        delivery_status="DELIVERED",
        delivered_revision=5,
    )
    discord_edits = [
        {"revision": 5, "message_id": message_id},
    ]

    class InterleavingDynamo(Dynamo):
        def __init__(self) -> None:
            super().__init__()
            self.item = old
            self.completion_calls = 0

        def update_item(self, **kwargs: object) -> object:
            self.updates.append(kwargs)
            if len(self.updates) == 1:
                return {}
            self.completion_calls += 1
            self.item = newer
            raise ConditionalFailure

    class Messages:
        def create(self, **kwargs: object) -> str:
            raise AssertionError(f"unexpected create: {kwargs}")

        def edit(self, **kwargs: object) -> str:
            assert kwargs["message_id"] == message_id
            discord_edits.insert(
                0,
                {"revision": 4, "message_id": message_id},
            )
            return message_id

    class Queue:
        def schedule(self, **kwargs: object) -> None:
            raise AssertionError(f"unexpected retry: {kwargs}")

    api = InterleavingDynamo()
    store = discord_message_lambda.DynamoDeliveryStore(api, table_name="operations")
    service = DiscordDeliveryService(store, Messages(), Queue())

    monkeypatch.setattr(discord_message_lambda, "_get_service", lambda: service)
    event = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "eventID": "old-completion",
                "body": ('{"schema_version":1,"operation_id":"op-status-001","source_revision":4}'),
            }
        ]
    }

    assert discord_message_lambda.handler(event, object()) == {"batchItemFailures": []}

    assert api.completion_calls == 1
    assert discord_edits == [
        {"revision": 4, "message_id": message_id},
        {"revision": 5, "message_id": message_id},
    ]
    final = store.load("op-status-001")
    assert final.delivery_status is DeliveryStatus.DELIVERED
    assert final.delivered_revision == 5
    assert final.delivery_source_revision == 5


def test_same_revision_already_delivered_completion_is_noop() -> None:
    current = delivery_item(
        progress_revision=4,
        delivery_source_revision=4,
        delivery_status="DELIVERED",
        delivered_revision=4,
        attempt_id="ddb:winner",
    )
    store = discord_message_lambda.DynamoDeliveryStore(
        CompletionRacingDynamo(current), table_name="operations"
    )
    claimed = replace(
        store.load("op-status-001"),
        delivery_status=DeliveryStatus.PENDING,
        attempt_id="ddb:duplicate",
    )

    store.mark_delivered(
        claimed,
        attempt_id="ddb:duplicate",
        message_id="1532999999999999999",
        now_epoch=1788270466,
    )


def test_newer_pending_revision_supersedes_old_completion() -> None:
    current = delivery_item(
        progress_revision=5,
        delivery_source_revision=5,
        delivery_status="PENDING",
        delivered_revision=3,
    )
    store = discord_message_lambda.DynamoDeliveryStore(
        CompletionRacingDynamo(current), table_name="operations"
    )
    old_claim = replace(
        store.load("op-status-001"),
        source_revision=4,
        delivery_source_revision=4,
        attempt_id="ddb:older",
    )

    store.mark_failed(
        old_claim,
        attempt_id="ddb:older",
        status=DeliveryStatus.RETRYABLE_FAILED,
        code="DISCORD_NETWORK_FAILURE",
        next_attempt_epoch=1788270471,
        outcome_unknown=False,
        now_epoch=1788270466,
    )


@pytest.mark.parametrize(
    "current",
    [
        delivery_item(
            progress_revision=3,
            delivery_source_revision=3,
            delivery_status="DELIVERED",
            delivered_revision=3,
        ),
        delivery_item(
            progress_revision=5,
            delivery_source_revision=5,
            delivery_status="DELIVERED",
            delivered_revision=5,
            message_id="1532888888888888888",
        ),
        delivery_item(
            progress_revision=4,
            delivery_source_revision=4,
            delivery_status="PENDING",
            delivered_revision=3,
            attempt_id="ddb:unrelated",
        ),
        delivery_item(
            progress_revision=5,
            delivery_source_revision=5,
            delivery_status="DELIVERED",
            delivered_revision=5,
            delivery_id="corrupt-delivery-identity",
        ),
    ],
)
def test_unexpected_completion_conflict_still_raises(current: dict[str, object]) -> None:
    store = discord_message_lambda.DynamoDeliveryStore(
        CompletionRacingDynamo(current), table_name="operations"
    )
    claimed = DeliveryRecord(
        operation_id="op-status-001",
        operation_status="RUNNING",
        channel_id="1531883129525244015",
        projection={},
        operation_type="STOP",
        current_step="HOST_RUNTIME_STOPPING",
        source_revision=4,
        delivery_status=DeliveryStatus.PENDING,
        attempt_id="ddb:older",
        message_id="1532999999999999999",
        delivery_id=operation_nonce("op-status-001"),
        delivery_source_revision=4,
    )

    with pytest.raises(ConditionalFailure):
        store.mark_delivered(
            claimed,
            attempt_id="ddb:older",
            message_id="1532999999999999999",
            now_epoch=1788270466,
        )


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
                        "progress_revision": {"N": "1"},
                        "requested_by": {"M": {"source": {"S": "DISCORD"}}},
                        "discord": {"M": {"channel_id": {"S": "1531883129525244015"}}},
                    },
                    "OldImage": {"progress_revision": {"N": "0"}},
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(stream) == (("op-status-001", 1, "ddb:event-1"),)
    sqs = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "eventID": "message-1",
                "body": ('{"schema_version":1,"operation_id":"op-status-001","source_revision":1}'),
            }
        ]
    }
    assert discord_message_lambda._delivery_events(sqs) == (("op-status-001", 1, "sqs:message-1"),)


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
                        "progress_revision": {"N": "1"},
                        "requested_by": {"M": {"source": {"S": "CLI"}}},
                        "discord": {"M": {"channel_id": {"NULL": True}}},
                    },
                    "OldImage": {"progress_revision": {"N": "0"}},
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(stream) == ()


def test_start_insert_and_progress_are_delivered_but_metadata_only_modify_is_noop() -> None:
    base = {
        "operation_id": {"S": "op-start-001"},
        "operation_type": {"S": "START"},
        "status": {"S": "PENDING"},
        "current_step": {"S": "ADMITTED"},
        "progress_revision": {"N": "0"},
        "requested_by": {"M": {"source": {"S": "DISCORD"}}},
        "discord": {"M": {"channel_id": {"S": "1531883129525244015"}}},
    }
    insert = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "INSERT",
                "eventID": "insert-1",
                "dynamodb": {"NewImage": base},
            }
        ]
    }
    assert discord_message_lambda._delivery_events(insert) == (("op-start-001", 0, "ddb:insert-1"),)
    metadata = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "metadata-1",
                "dynamodb": {
                    "OldImage": base,
                    "NewImage": {
                        **base,
                        "discord": {
                            "M": {
                                "channel_id": {"S": "1531883129525244015"},
                                "delivery_status": {"S": "PENDING"},
                            }
                        },
                    },
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(metadata) == ()


def test_old_start_progress_event_carries_its_revision_for_stale_rejection() -> None:
    event = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "progress-1",
                "dynamodb": {
                    "OldImage": {"progress_revision": {"N": "0"}},
                    "NewImage": {
                        "operation_id": {"S": "op-start-001"},
                        "operation_type": {"S": "START"},
                        "status": {"S": "RUNNING"},
                        "current_step": {"S": "EC2_STARTING"},
                        "progress_revision": {"N": "1"},
                        "requested_by": {"M": {"source": {"S": "DISCORD"}}},
                        "discord": {"M": {"channel_id": {"S": "1531883129525244015"}}},
                    },
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(event) == (
        ("op-start-001", 1, "ddb:progress-1"),
    )


def test_stop_progress_is_delivered_but_metadata_only_modify_is_noop() -> None:
    base = {
        "operation_id": {"S": "op-stop-001"},
        "operation_type": {"S": "STOP"},
        "status": {"S": "RUNNING"},
        "current_step": {"S": "HOST_RUNTIME_STOPPING"},
        "progress_revision": {"N": "2"},
        "requested_by": {"M": {"source": {"S": "DISCORD"}}},
        "discord": {"M": {"channel_id": {"S": "1531883129525244015"}}},
    }
    progress = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "stop-progress-2",
                "dynamodb": {
                    "OldImage": {**base, "progress_revision": {"N": "1"}},
                    "NewImage": base,
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(progress) == (
        ("op-stop-001", 2, "ddb:stop-progress-2"),
    )

    metadata = {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": "stop-metadata",
                "dynamodb": {
                    "OldImage": base,
                    "NewImage": {
                        **base,
                        "discord": {
                            "M": {
                                "channel_id": {"S": "1531883129525244015"},
                                "delivery_status": {"S": "PENDING"},
                            }
                        },
                    },
                },
            }
        ]
    }
    assert discord_message_lambda._delivery_events(metadata) == ()


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
