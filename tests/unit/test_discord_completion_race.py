"""Reproduce progress advancing after edit but before delivery completion CAS."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from wishicraft import discord_message_lambda as adapter
from wishicraft.discord_delivery import (
    DeliveryRecord,
    DeliveryStatus,
    DiscordDeliveryService,
    DiscordFailure,
    operation_nonce,
)

OP = "op-race"
MESSAGE = "1234567890123456789"


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Dynamo:
    """Only the claim/completion conditions used by this adapter, no AWS access."""

    def __init__(self) -> None:
        self.item: dict[str, Any] = {
            "operation_id": {"S": OP},
            "operation_type": {"S": "START"},
            "status": {"S": "RUNNING"},
            "current_step": {"S": "DESIRED_RUNNING"},
            "progress_revision": {"N": "1"},
            "requested_by": {"M": {"source": {"S": "DISCORD"}}},
            "discord": {
                "M": {
                    "channel_id": {"S": "123"},
                    "message_id": {"S": MESSAGE},
                    "delivery_id": {"S": operation_nonce(OP)},
                    "delivery_source_revision": {"N": "0"},
                    "delivery_delivered_revision": {"N": "0"},
                    "delivery_status": {"S": "DELIVERED"},
                    "delivery_attempt_id": {"S": "ddb:previous"},
                }
            },
        }
        self.completion_failures = 0
        self.consistent_reads = 0

    def get_item(self, **kwargs: Any) -> object:
        assert kwargs["ConsistentRead"] is True
        self.consistent_reads += 1
        return {"Item": copy.deepcopy(self.item)}

    def update_item(self, **kwargs: Any) -> object:
        values = kwargs["ExpressionAttributeValues"]
        discord = self.item["discord"]["M"]
        revision = values[":source_revision"]
        if ":count" in values:  # Claim the next stream revision.
            assert self.item["progress_revision"] == revision
            assert int(discord["delivery_source_revision"]["N"]) < int(revision["N"])
            discord.update(
                delivery_source_revision=revision,
                delivery_status=values[":pending"],
                delivery_attempt_id=values[":attempt"],
                delivery_attempt_count=values[":count"],
                delivery_first_attempt_epoch=values[":now"],
                delivery_outcome_unknown=values[":false"],
            )
            return {}
        assert "progress_revision = :source_revision" in kwargs["ConditionExpression"]
        assert "delivery_attempt_id = :attempt" in kwargs["ConditionExpression"]
        if (
            self.item["progress_revision"] != revision
            or discord["delivery_source_revision"] != revision
            or discord["delivery_status"] != values[":pending"]
            or discord["delivery_attempt_id"] != values[":attempt"]
        ):
            self.completion_failures += 1
            raise ConditionalFailure
        discord.update(
            delivery_status=values[":status"],
            delivery_error_code=values[":code"],
            delivery_next_attempt_epoch=values[":next"],
            delivery_outcome_unknown=values[":unknown"],
            message_id=values[":message"],
            delivery_delivered_revision=values[":delivered_revision"],
        )
        return {}


def stream_event(api: Dynamo, revision: int) -> dict[str, object]:
    return {
        "Records": [
            {
                "eventSource": "aws:dynamodb",
                "eventName": "MODIFY",
                "eventID": f"revision-{revision}",
                "dynamodb": {
                    "NewImage": copy.deepcopy(api.item),
                    "OldImage": {"progress_revision": {"N": str(revision - 1)}},
                },
            }
        ]
    }


def test_progress_only_supersede_returns_success_and_next_stream_delivers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Dynamo()
    store = adapter.DynamoDeliveryStore(api, table_name="operations")
    edits: list[str] = []
    after_advance: list[dict[str, Any]] = []

    class Messages:
        def create(self, **kwargs: object) -> str:
            raise AssertionError("one existing message; never create another")

        def edit(self, **kwargs: object) -> str:
            assert kwargs["message_id"] == MESSAGE
            edits.append(str(kwargs["content"]))  # Discord has accepted the edit.
            if len(edits) == 1:
                claimed = store.load(OP)
                assert claimed.source_revision == claimed.delivery_source_revision == 1
                assert claimed.delivery_status is DeliveryStatus.PENDING
                # Exactly the production ordering: progress advances, delivery
                # remains pending under the old owner; no new claim yet.
                api.item["progress_revision"] = {"N": "2"}
                api.item["current_step"] = {"S": "EC2_STARTING"}
                after_advance.append(copy.deepcopy(api.item))
            return MESSAGE

    class Queue:
        def schedule(self, **kwargs: object) -> None:
            raise AssertionError("a superseded completion needs no retry")

    service = DiscordDeliveryService(store, Messages(), Queue())
    monkeypatch.setattr(adapter, "_get_service", lambda: service)
    assert adapter.handler(stream_event(api, 1), object()) == {"batchItemFailures": []}
    assert api.completion_failures == 1
    assert api.item == after_advance[0]  # No stale completion write or new claim.
    assert api.consistent_reads >= 3  # Includes completion conflict read-back.
    assert len(edits) == 1

    # The ordinary stream path owns the next delivery, not the old invocation.
    api.item["status"] = {"S": "SUCCEEDED"}
    assert adapter.handler(stream_event(api, 2), object()) == {"batchItemFailures": []}
    final = store.load(OP)
    assert final.source_revision == final.delivery_source_revision == final.delivered_revision == 2
    assert final.delivery_status is DeliveryStatus.DELIVERED
    assert final.message_id == MESSAGE
    assert len(edits) == 2
    assert api.completion_failures == 1


def claimed() -> DeliveryRecord:
    return DeliveryRecord(
        operation_id=OP,
        operation_type="START",
        operation_status="RUNNING",
        channel_id="123",
        projection={},
        source_revision=1,
        delivery_source_revision=1,
        delivery_status=DeliveryStatus.PENDING,
        delivery_id=operation_nonce(OP),
        attempt_id="ddb:old",
        message_id=MESSAGE,
        delivered_revision=0,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_revision": 1},
        {
            "source_revision": 1,
            "delivery_status": DeliveryStatus.DELIVERED,
            "delivered_revision": 1,
        },
        {"source_revision": 0},
        {"message_id": "other"},
        {"operation_id": "op-other"},
        {"operation_type": "STOP"},
        {"channel_id": "other"},
        {"delivery_id": "other"},
        {"attempt_id": "different-owner"},
        {"delivery_source_revision": None},
        {"delivery_source_revision": 0},
        {"delivery_source_revision": 3},
        {"delivery_status": None},
        {"delivery_status": DeliveryStatus.DELIVERED},
        {"delivered_revision": 2},
        {"outcome_unknown": True},
        {"delivery_source_revision": 2, "attempt_id": ""},
        {"delivery_source_revision": 2},  # Same old attempt cannot own the new revision.
        {"delivery_source_revision": 2, "attempt_id": "new", "delivered_revision": 3},
    ],
)
def test_unproven_supersede_fails_closed(
    changes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    class ConflictDynamo(Dynamo):
        def update_item(self, **kwargs: object) -> object:
            raise ConditionalFailure

    store = adapter.DynamoDeliveryStore(ConflictDynamo(), table_name="operations")
    old = claimed()
    current = replace(old, **{"source_revision": 2, **changes})
    monkeypatch.setattr(store, "load", lambda operation_id: current)
    with pytest.raises(ConditionalFailure):
        store.mark_delivered(old, attempt_id="ddb:old", message_id=MESSAGE, now_epoch=100)


@pytest.mark.parametrize("status", list(DeliveryStatus))
def test_coherent_newer_delivery_can_lag_authoritative_progress(status: DeliveryStatus) -> None:
    old = claimed()
    current = replace(
        old,
        source_revision=3,
        delivery_source_revision=2,
        attempt_id="ddb:new",
        delivery_status=status,
        delivered_revision=2 if status is DeliveryStatus.DELIVERED else 0,
    )
    assert adapter.DynamoDeliveryStore._completion_conflict_is_noop(
        old,
        current=current,
        completed_status=DeliveryStatus.DELIVERED,
        attempt_id="ddb:old",
        message_id=MESSAGE,
    )


def test_readback_rejects_different_operation_key() -> None:
    api = Dynamo()
    api.item["operation_id"] = {"S": "op-other"}
    with pytest.raises(ValueError, match="identity mismatch"):
        adapter.DynamoDeliveryStore(api, table_name="operations").load(OP)


def test_real_api_failure_keeps_existing_retry_contract() -> None:
    api = Dynamo()
    store = adapter.DynamoDeliveryStore(api, table_name="operations")
    retries: list[dict[str, object]] = []

    class Messages:
        def create(self, **kwargs: object) -> str:
            raise AssertionError("existing message")

        def edit(self, **kwargs: object) -> str:
            raise DiscordFailure("DISCORD_NETWORK_FAILURE", True)

    class Queue:
        def schedule(self, **kwargs: object) -> None:
            retries.append(kwargs)

    service = DiscordDeliveryService(
        store, Messages(), Queue(), clock=lambda: datetime(2026, 9, 22, tzinfo=UTC)
    )
    service.deliver(operation_id=OP, source_revision=1, attempt_id="ddb:old")
    final = store.load(OP)
    assert final.delivery_status is DeliveryStatus.RETRYABLE_FAILED
    assert final.delivered_revision == 0
    assert final.message_id == MESSAGE
    assert final.next_attempt_epoch is not None
    assert api.item["discord"]["M"]["delivery_error_code"] == {"S": "DISCORD_NETWORK_FAILURE"}
    # A subsequent delivery before the due time follows the existing queue path.
    service.deliver(operation_id=OP, source_revision=1, attempt_id="ddb:retry")
    assert len(retries) == 1 and retries[0]["source_revision"] == 1
