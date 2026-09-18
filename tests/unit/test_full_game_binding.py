"""Complete schema-1 Game wire records through the deployed binding/failure boundary."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]

from web.local_operations import MemoryDynamo, TransactionCancelled, service
from wishicraft import start_workflow_lambda, stop_workflow_lambda
from wishicraft.artifacts import game_package
from wishicraft.game import Game, GameLifecycle, MaterializationState
from wishicraft.game_creation import REGISTRY_KEY
from wishicraft.operation import (
    OperationRepository,
    OperationType,
    RequestSource,
    _attribute_map,
    _decode_attribute,
)
from wishicraft.runtime_catalog import bind_operation
from wishicraft.runtime_contract import RuntimeTargetRepository
from wishicraft.start_workflow import StartObservation

GAMES = ("game-fixture-a", "game-fixture-b", "game-" + "c" * 64)
DIGEST = "a" * 64


def full_game(game_id: str) -> dict[str, Any]:
    """Real schema shape, synthetic identities; no production record/secret copied."""
    modded = game_id == GAMES[2]
    package = game_package.load()[int(modded)]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    game = Game(
        game_id,
        "Fixture Game",
        "fixture game",
        GameLifecycle.ACTIVE,
        MaterializationState.UNMATERIALIZED if modded else MaterializationState.MATERIALIZED,
        package["package_id"],
        package["package_version"],
        "default",
        30,
        1,
        now,
        now,
    ).to_item()
    world = game["world"]
    assert isinstance(world, dict)
    if game_id == GAMES[1]:
        world["current_id"] = "op-fixture-reset"
    if modded:
        world["seed"] = 2**63 - 1
        game["package"] = {**game["package"], "definition": package}  # type: ignore[dict-item]
        game["creation"] = {
            "operation_id": "op-fixture-create",
            "actor_id": "fixture-actor",
            "config_digest": DIGEST,
            "package_digest": game_package.digest(package),
            "reset_policy": None,
        }
    return game


class BoundaryDynamo(MemoryDynamo):
    """Existing admission harness plus the owned-completion transaction's CAS boundary."""

    game_reads = 0

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["TableName"] == "games":
            self.game_reads += 1
        return super().get_item(**kwargs)

    def transact_write_items(self, **kwargs: Any) -> dict[str, Any]:
        items = kwargs["TransactItems"]
        if not any("Delete" in item for item in items):
            return super().transact_write_items(**kwargs)
        terminal, delete, current = items[0]["Update"], items[1]["Delete"], items[2]["Update"]
        assert len(items) == 3
        assert terminal["ConditionExpression"] == "#status IN (:pending, :running)"
        assert delete["ConditionExpression"] == (
            "resource_id = :resource_id AND owner_operation_id = :operation_id "
            "AND lease_id = :lease_id AND lease_expires_at >= :now"
        )
        assert current["ConditionExpression"] == "current_operation_id = :operation_id"
        assert current["UpdateExpression"] == "REMOVE current_operation_id"
        op_key = ("operation", terminal["Key"]["operation_id"]["S"])
        lock_key = ("locks", delete["Key"]["lock_name"]["S"])
        op, lock, state = (
            self.records[op_key],
            self.records.get(lock_key, {}),
            self.records["system", "local"],
        )
        values = delete["ExpressionAttributeValues"]
        if (
            op["status"]["S"] not in {"PENDING", "RUNNING"}
            or any(
                lock.get(k) != values[v]
                for k, v in {
                    "resource_id": ":resource_id",
                    "owner_operation_id": ":operation_id",
                    "lease_id": ":lease_id",
                }.items()
            )
            or int(lock.get("lease_expires_at", {"N": "0"})["N"]) < int(values[":now"]["N"])
            or state.get("current_operation_id")
            != current["ExpressionAttributeValues"][":operation_id"]
        ):
            raise TransactionCancelled()
        op["status"] = terminal["ExpressionAttributeValues"][":status"]
        op["error"] = terminal["ExpressionAttributeValues"][":error"]
        del self.records[lock_key]
        del state["current_operation_id"]
        self.transactions += 1
        return {}


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> tuple[BoundaryDynamo, Any]:
    import boto3  # type: ignore[import-untyped]

    db = BoundaryDynamo()
    for game_id in GAMES:
        game = full_game(game_id)
        wire = {k: TypeSerializer().serialize(v) for k, v in game.items()}
        assert wire == _attribute_map(game)
        db.records["games", game_id] = wire
    db.records["games", REGISTRY_KEY] = {
        "game_id": {"S": REGISTRY_KEY},
        "registered_ids": {"SS": [GAMES[2]]},
    }
    db.records["system", "local"] = {"system_id": {"S": "local"}}
    for key, value in {
        "GAME_CREATION": "1",
        "GAME_PACKAGES": "1",
        "GAMES_TABLE": "games",
        "RUNTIME_GAMES": json.dumps(GAMES[:2]),
        "RESET_CONTRACT": "0",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: db)
    runtime = SimpleNamespace(
        targets=RuntimeTargetRepository(db, "operation"),
        system_id="local",
        config_digest=DIGEST,
        coordinator=Mock(),
        operations=OperationRepository(
            db,
            operations_table="operation",
            locks_table="locks",
            system_state_table="system",
            system_id="local",
            lock_name="minecraft-control",
        ),
    )
    monkeypatch.setattr(start_workflow_lambda, "_runtime", runtime)
    monkeypatch.setattr(stop_workflow_lambda, "_runtime", runtime)
    return db, runtime


def admit(db: BoundaryDynamo, game_id: str) -> Any:
    return service(db).admit(
        operation_type=OperationType.START,
        idempotency_key="fixture-request",
        requested_by=RequestSource.CLI,
        requested_at=datetime.now(UTC),
        target_game_id=game_id,
    )


@pytest.mark.parametrize("game_id", GAMES)
def test_full_game_binding_and_start_preparation(
    boundary: Any, monkeypatch: pytest.MonkeyPatch, game_id: str
) -> None:
    db, runtime = boundary
    request = admit(db, game_id)
    original = copy.deepcopy(db.records["games", game_id])
    decoded = {k: _decode_attribute(v) for k, v in original.items()}
    assert decoded == full_game(game_id)
    for _ in range(2):
        bind_operation(runtime, request.operation_id, action="START")
        assert runtime.game_id == game_id
        assert runtime.data_source == f"/srv/minecraft/games/{game_id}/server"
    select = Mock()
    monkeypatch.setattr(start_workflow_lambda, "select_target", select)
    monkeypatch.setattr(StartObservation, "from_item", Mock())
    runtime.coordinator.verify_and_set_desired.return_value = (1, False)
    runtime.operations.update_step = Mock()
    assert start_workflow_lambda.handler(
        {
            "schema_version": 1,
            "action": "set_desired",
            "operation_id": request.operation_id,
            "lease_id": request.lease_id,
            "state": {},
        },
        None,
    ) == {"desired_revision": 1, "already_ready": False}
    select.assert_called_once()
    assert db.records["games", game_id] == original
    assert admit(db, game_id).operation_id == request.operation_id


@pytest.mark.parametrize("module", [start_workflow_lambda, stop_workflow_lambda])
def test_invalid_package_failure_finalizes_without_rebinding(boundary: Any, module: Any) -> None:
    db, runtime = boundary
    request = admit(db, GAMES[2])
    db.records["games", GAMES[2]]["runtime"]["M"]["class"] = {"S": "invalid"}
    before = copy.deepcopy(db.records["games", GAMES[2]])
    with pytest.raises(ValueError, match="PACKAGE_RUNTIME_CLASS"):
        start_workflow_lambda.handler(
            {
                "schema_version": 1,
                "action": "set_desired",
                "operation_id": request.operation_id,
                "lease_id": request.lease_id,
                "state": {},
            },
            None,
        )
    reads = db.game_reads
    event = {
        "schema_version": 1,
        "action": "fail",
        "operation_id": request.operation_id,
        "lease_id": request.lease_id,
        "error_code": "START_PRECONDITION_FAILED",
    }
    with pytest.raises(TransactionCancelled):
        module.handler({**event, "lease_id": "lease-other"}, None)
    assert db.records["system", "local"]["current_operation_id"] == {"S": request.operation_id}
    assert module.handler(event, None) == {"status": "FAILED"}
    assert db.game_reads == reads
    assert db.records["operation", request.operation_id]["status"] == {"S": "FAILED"}
    assert ("locks", "minecraft-control") not in db.records
    assert "current_operation_id" not in db.records["system", "local"]
    assert db.records["games", GAMES[2]] == before
    assert admit(db, GAMES[2]).operation_id == request.operation_id
    with pytest.raises(TransactionCancelled):
        module.handler(event, None)
    assert ("locks", "minecraft-control") not in db.records


def test_recursive_null_and_existing_scalar_types() -> None:
    value = {
        "s": "text",
        "n": 2**63 - 1,
        "b": False,
        "none": None,
        "list": [None, {"nested": None}],
    }
    assert _decode_attribute({"M": _attribute_map(value)}) == value


@pytest.mark.parametrize(
    "wire",
    [
        {"NULL": False},
        {"NULL": 1},
        {"NULL": True, "S": "x"},
        {"S": "x", "N": "1"},
        {"M": {"bad": {"NULL": False}}},
        {"L": [{"BOOL": True, "N": "1"}]},
    ],
)
def test_malformed_attribute_fails_closed(wire: Any) -> None:
    with pytest.raises(ValueError):
        _decode_attribute(wire)


@pytest.mark.parametrize("ready", [False, True])
def test_first_materialization_requires_exact_ready_before_commit(
    boundary: Any, monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    from wishicraft import game_creation
    from wishicraft.start_workflow import StartWorkflowError

    db, runtime = boundary
    request = admit(db, GAMES[2])
    before = copy.deepcopy(db.records["games", GAMES[2]])
    monkeypatch.setattr(start_workflow_lambda, "assert_observed", Mock())
    observation = Mock()
    observation.ready_for_success.return_value = ready
    monkeypatch.setattr(StartObservation, "from_item", Mock(return_value=observation))
    commit = Mock()
    monkeypatch.setattr(game_creation, "complete_materialization", commit)
    runtime.operations.complete_owned = Mock()
    event = {
        "schema_version": 1,
        "action": "complete",
        "operation_id": request.operation_id,
        "lease_id": request.lease_id,
        "state": {},
    }
    if ready:
        assert start_workflow_lambda.handler(event, None) == {"status": "SUCCEEDED"}
        commit.assert_called_once()
        runtime.operations.complete_owned.assert_called_once()
    else:
        with pytest.raises(StartWorkflowError):
            start_workflow_lambda.handler(event, None)
        commit.assert_not_called()
        runtime.operations.complete_owned.assert_not_called()
    observation.ready_for_success.assert_called_once_with(GAMES[2])
    assert db.records["games", GAMES[2]] == before
