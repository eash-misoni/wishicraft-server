from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from wishicraft.system_state import (
    DesiredState,
    DesiredStateSnapshot,
    Health,
    SystemState,
    SystemStateRepository,
)


class FakeDynamo:
    def __init__(self, item: object = None) -> None:
        self.item = item
        self.updates: list[dict[str, object]] = []

    def get_item(self, **kwargs: object) -> object:
        return {} if self.item is None else {"Item": self.item}

    def update_item(self, **kwargs: object) -> object:
        self.updates.append(kwargs)
        return {}


def state(at: datetime) -> SystemState:
    return SystemState(
        system_id="wishicraft-main",
        environment="dev",
        game_id="game-vanilla-main",
        desired_state=DesiredState.STOPPED,
        target_instance_id=None,
        observation={"ec2_state": "stopped", "runtime_ready": False},
        discrepancies=(),
        health=Health.HEALTHY,
        observation_errors=(),
        observed_at=at,
    )


def test_first_write_uses_monotonic_conditional_update() -> None:
    api = FakeDynamo()
    repository = SystemStateRepository(api, table_name="states", system_id="wishicraft-main")
    repository.save(state(datetime(2026, 8, 28, tzinfo=UTC)))
    request = api.updates[0]
    assert request["ConditionExpression"] == (
        "attribute_not_exists(#observed_at) OR #observed_at < :observed_at"
    )
    assert cast(str, request["UpdateExpression"]).startswith("SET ")
    expression = cast(str, request["UpdateExpression"])
    assert "#desired_state = if_not_exists(#desired_state, :desired_state)" in expression
    assert "#observation = :observation" in expression
    assert "current_operation_id" not in expression


def test_timestamp_representation_orders_older_and_newer() -> None:
    api = FakeDynamo()
    repository = SystemStateRepository(api, table_name="states", system_id="wishicraft-main")
    older = state(datetime(2026, 8, 28, 0, 0, 0, 1, tzinfo=UTC))
    newer = state(datetime(2026, 8, 28, 0, 0, 0, 2, tzinfo=UTC))
    repository.save(older)
    repository.save(newer)
    old_values = cast(dict[str, dict[str, str]], api.updates[0]["ExpressionAttributeValues"])
    new_values = cast(dict[str, dict[str, str]], api.updates[1]["ExpressionAttributeValues"])
    old_value = old_values[":observed_at"]["S"]
    new_value = new_values[":observed_at"]["S"]
    assert old_value < new_value
    assert "<" in cast(str, api.updates[1]["ConditionExpression"])


def test_repository_condition_rejects_older_and_equal_timestamp() -> None:
    class ConditionalDynamo(FakeDynamo):
        def __init__(self) -> None:
            super().__init__()
            self.stored: str | None = None

        def update_item(self, **kwargs: object) -> object:
            values = cast(dict[str, dict[str, str]], kwargs["ExpressionAttributeValues"])
            incoming = values[":observed_at"]["S"]
            if self.stored is not None and incoming <= self.stored:
                raise RuntimeError("ConditionalCheckFailedException")
            self.stored = incoming
            return super().update_item(**kwargs)

    api = ConditionalDynamo()
    repository = SystemStateRepository(api, table_name="states", system_id="wishicraft-main")
    newer = state(datetime(2026, 8, 28, 0, 0, 2, tzinfo=UTC))
    same = state(datetime(2026, 8, 28, 0, 0, 2, tzinfo=UTC))
    older = state(datetime(2026, 8, 28, 0, 0, 1, tzinfo=UTC))
    repository.save(newer)
    with pytest.raises(RuntimeError, match="ConditionalCheckFailed"):
        repository.save(same)
    with pytest.raises(RuntimeError, match="ConditionalCheckFailed"):
        repository.save(older)


def test_existing_desired_state_is_preserved_and_missing_defaults_stopped() -> None:
    assert (
        SystemStateRepository(FakeDynamo(), table_name="t", system_id="s").desired_state()
        is DesiredState.STOPPED
    )


def test_desired_snapshot_separates_revision_from_observed_freshness() -> None:
    item = {
        "desired_state": {"S": "RUNNING"},
        "desired_game_id": {"S": "game-vanilla-main"},
        "desired_revision": {"N": "7"},
        "observed_at": {"S": "2099-01-01T00:00:00.000000Z"},
    }
    repository = SystemStateRepository(FakeDynamo(item), table_name="t", system_id="s")
    assert repository.desired_snapshot() == DesiredStateSnapshot(
        DesiredState.RUNNING, "game-vanilla-main", 7
    )


def test_desired_update_uses_revision_cas_and_current_operation_condition() -> None:
    api = FakeDynamo()
    repository = SystemStateRepository(api, table_name="states", system_id="wishicraft-main")
    next_revision = repository.update_desired(
        desired_state=DesiredState.RUNNING,
        desired_game_id="game-vanilla-main",
        expected_revision=3,
        operation_id="op-start-1",
        updated_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert next_revision == 4
    request = api.updates[0]
    condition = cast(str, request["ConditionExpression"])
    assert "#desired_revision = :expected_revision" in condition
    assert "#current_operation_id = :operation_id" in condition
    assert "observed_at" not in condition
    assert "#desired_revision = :next_revision" in cast(str, request["UpdateExpression"])


def test_desired_revision_rejects_stale_or_wrong_operation_mutation() -> None:
    class ConditionalDesired(FakeDynamo):
        def __init__(self) -> None:
            super().__init__()
            self.revision = 2
            self.operation_id = "op-current"

        def update_item(self, **kwargs: object) -> object:
            values = cast(dict[str, dict[str, str]], kwargs["ExpressionAttributeValues"])
            expected = int(values[":expected_revision"]["N"])
            operation_id = values[":operation_id"]["S"]
            if expected != self.revision or operation_id != self.operation_id:
                raise RuntimeError("ConditionalCheckFailedException")
            self.revision = int(values[":next_revision"]["N"])
            return super().update_item(**kwargs)

    api = ConditionalDesired()
    repository = SystemStateRepository(api, table_name="states", system_id="wishicraft-main")
    assert (
        repository.update_desired(
            desired_state=DesiredState.STOPPED,
            desired_game_id=None,
            expected_revision=2,
            operation_id="op-current",
            updated_at=datetime(2026, 8, 29, tzinfo=UTC),
        )
        == 3
    )
    with pytest.raises(RuntimeError, match="ConditionalCheckFailed"):
        repository.update_desired(
            desired_state=DesiredState.RUNNING,
            desired_game_id="game-vanilla-main",
            expected_revision=2,
            operation_id="op-current",
            updated_at=datetime(2026, 8, 29, 0, 0, 1, tzinfo=UTC),
        )
    with pytest.raises(RuntimeError, match="ConditionalCheckFailed"):
        repository.update_desired(
            desired_state=DesiredState.RUNNING,
            desired_game_id="game-vanilla-main",
            expected_revision=3,
            operation_id="op-stale-executor",
            updated_at=datetime(2026, 8, 29, 0, 0, 2, tzinfo=UTC),
        )


def test_desired_state_validation_distinguishes_stopped_and_running_game() -> None:
    with pytest.raises(ValueError, match="requires a game"):
        DesiredStateSnapshot(DesiredState.RUNNING, None, 1)
    assert DesiredStateSnapshot(DesiredState.STOPPED, None, 0).desired_revision == 0
    api = FakeDynamo({"desired_state": {"S": "RUNNING"}})
    assert (
        SystemStateRepository(api, table_name="t", system_id="s").desired_state()
        is DesiredState.RUNNING
    )


def test_malformed_or_unsafe_state_is_rejected() -> None:
    with pytest.raises(ValueError):
        SystemStateRepository(
            FakeDynamo({"desired_state": {"N": "1"}}), table_name="t", system_id="s"
        ).desired_state()
    with pytest.raises(ValueError, match="unsafe"):
        SystemState(**{**state(datetime.now(UTC)).__dict__, "observation": {"raw_secret": "no"}})
    with pytest.raises(ValueError, match="unsafe"):
        SystemState(
            **{
                **state(datetime.now(UTC)).__dict__,
                "observation": {"nested": {"raw_motd": "no"}},
            }
        )


def test_repository_rejects_mismatched_system_identity() -> None:
    repository = SystemStateRepository(
        FakeDynamo(), table_name="states", system_id="wishicraft-main"
    )
    mismatched = SystemState(
        **{**state(datetime.now(UTC)).__dict__, "system_id": "wishicraft-other"}
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        repository.save(mismatched)


def test_dynamodb_error_propagates() -> None:
    class Failing(FakeDynamo):
        def update_item(self, **kwargs: object) -> object:
            raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        SystemStateRepository(Failing(), table_name="t", system_id="wishicraft-main").save(
            state(datetime.now(UTC))
        )
