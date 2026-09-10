from __future__ import annotations

from datetime import UTC, datetime

from wishicraft.auto_stop_warning import WARNING_TEXT, WarningDelivery


class Dynamo:
    def __init__(self) -> None:
        self.item: dict[str, object] = {
            "game_id": {"S": "game-vanilla-main"},
            "intent_id": {"S": "asi-example"},
            "channel_id": {"S": "123"},
            "warning_delivery_id": {"S": "asw-example"},
            "warning_delivery_state": {"S": "NOT_STARTED"},
            "warning_attempt_count": {"N": "0"},
            "status": {"S": "WARNING_PENDING"},
        }

    def get_item(self, **kwargs: object) -> object:
        del kwargs
        return {"Item": self.item}

    def update_item(self, **kwargs: object) -> object:
        values = kwargs["ExpressionAttributeValues"]
        assert isinstance(values, dict)
        if ":warning_pending" in values and self.item["status"] != values[":warning_pending"]:
            raise ConditionalFailure
        if ":pending" in values and values.get(":delivered") is None:
            self.item["warning_delivery_state"] = {"S": "PENDING"}
            self.item["warning_attempt_count"] = values[":count"]
        elif ":delivered" in values:
            self.item["warning_delivery_state"] = {"S": "DELIVERED"}
            self.item["warning_delivered_at"] = values[":now"]
            self.item["warning_message_id"] = values[":message"]
        return {}


class Messages:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def create(self, *, channel_id: str, nonce: str, content: str) -> str:
        self.calls.append({"channel_id": channel_id, "nonce": nonce, "content": content})
        return "message-1"

    def edit(self, *, channel_id: str, message_id: str, content: str) -> str:
        raise AssertionError((channel_id, message_id, content))


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def test_warning_delivery_creates_one_safe_deterministic_message() -> None:
    dynamo, messages = Dynamo(), Messages()
    service = WarningDelivery(dynamo, messages, table_name="intents")
    now = datetime(2026, 9, 10, tzinfo=UTC)
    assert service.deliver(game_id="game-vanilla-main", intent_id="asi-example", now=now) == {
        "state": "DELIVERED",
        "created": True,
    }
    assert service.deliver(game_id="game-vanilla-main", intent_id="asi-example", now=now) == {
        "state": "DELIVERED",
        "created": False,
    }
    assert len(messages.calls) == 1
    assert messages.calls[0]["content"] == WARNING_TEXT
    assert "snapshot" not in WARNING_TEXT.lower()


def test_late_warning_success_cannot_reactivate_an_invalidated_intent() -> None:
    dynamo = Dynamo()

    class InvalidatingMessages(Messages):
        def create(self, *, channel_id: str, nonce: str, content: str) -> str:
            result = super().create(channel_id=channel_id, nonce=nonce, content=content)
            dynamo.item["status"] = {"S": "CANCELLED"}
            dynamo.item["warning_delivery_state"] = {"S": "PENDING"}
            return result

    messages = InvalidatingMessages()
    service = WarningDelivery(dynamo, messages, table_name="intents")
    result = service.deliver(
        game_id="game-vanilla-main",
        intent_id="asi-example",
        now=datetime(2026, 9, 10, tzinfo=UTC),
    )
    assert result == {"state": "PENDING", "created": True}
    assert dynamo.item["status"] == {"S": "CANCELLED"}
    assert "warning_delivered_at" not in dynamo.item
