"""Test-only in-memory AWS boundary. Not imported by or bundled with production handlers."""

from __future__ import annotations

import io
import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from wishicraft.operation import (
    OperationAdmissionRepository,
    OperationAdmissionService,
    OperationType,
    RequestSource,
)
from wishicraft.system_state import _to_attribute
from wishicraft.web_auth import Policy
from wishicraft.web_operations import Operations, admission_actor


class TransactionCancelled(Exception):
    response = {"Error": {"Code": "TransactionCanceledException"}}


class MemoryDynamo:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.mutex = threading.RLock()
        self.transactions = 0

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        with self.mutex:
            value = self.records.get((kwargs["TableName"], next(iter(kwargs["Key"].values()))["S"]))
            return {"Item": json.loads(json.dumps(value))} if value else {}

    def transact_write_items(self, **kwargs: Any) -> dict[str, Any]:
        with self.mutex:
            items = kwargs["TransactItems"]
            for action in items:
                if "Put" in action:
                    put = action["Put"]
                    item = put["Item"]
                    key = next(
                        item[k]["S"]
                        for k in ("idempotency_key", "operation_id", "lock_name")
                        if k in item
                        and (k != "idempotency_key" or put["TableName"] == "idempotency")
                    )
                    # Operations use operation_id as the table key.
                    if put["TableName"] == "operation":
                        key = item["operation_id"]["S"]
                    if (put["TableName"], key) in self.records:
                        raise TransactionCancelled()
                elif "ConditionCheck" in action:
                    check = action["ConditionCheck"]
                    key = check["Key"]["game_id"]["S"]
                    if self.records.get((check["TableName"], key), {}).get("lifecycle_state") != {
                        "S": "ACTIVE"
                    }:
                        raise TransactionCancelled()
                elif "Update" in action:
                    update = action["Update"]
                    key = update["Key"]["system_id"]["S"]
                    state = self.records.get((update["TableName"], key))
                    if state is None or state.get("current_operation_id", {"NULL": True}) != {
                        "NULL": True
                    }:
                        raise TransactionCancelled()
            for action in items:
                if "Put" in action:
                    put = action["Put"]
                    item = put["Item"]
                    field = {
                        "operation": "operation_id",
                        "idempotency": "idempotency_key",
                        "locks": "lock_name",
                    }[put["TableName"]]
                    self.records[put["TableName"], item[field]["S"]] = json.loads(json.dumps(item))
                elif "Update" in action:
                    update = action["Update"]
                    state = self.records[update["TableName"], update["Key"]["system_id"]["S"]]
                    state["current_operation_id"] = update["ExpressionAttributeValues"][
                        ":operation_id"
                    ]
                    state["last_operation_id"] = state["current_operation_id"]
            self.transactions += 1
            return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Use an explicit test launcher")

    def delete_item(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("No implicit cleanup")


def service(db: MemoryDynamo) -> OperationAdmissionService:
    return OperationAdmissionService(
        OperationAdmissionRepository(
            db,
            operations_table="operation",
            games_table="games",
            idempotency_table="idempotency",
            locks_table="locks",
            system_state_table="system",
            system_id="local",
            lock_name="minecraft-control",
            lease_seconds=900,
            lease_id_factory=lambda: "lease-" + str(uuid.uuid4()),
        ),
        game_id="game-demo-one",
        timeout_seconds={kind: 3000 for kind in OperationType},
        operation_id_factory=lambda: "op-" + str(uuid.uuid4()),
    )


class LocalOperations(Operations):
    def __init__(self, policy: Policy, scenario: str) -> None:
        self.db = MemoryDynamo()
        self.scenario = scenario
        self.started: dict[str, float] = {}
        self.domain = service(self.db)
        catalog = ("game-demo-one", "game-demo-two")
        for i, game in enumerate(catalog):
            self.db.records["games", game] = {
                k: _to_attribute(v)
                for k, v in {
                    "game_id": game,
                    "display_name": f"Local Game {i + 1}",
                    "lifecycle_state": "ACTIVE",
                    "world": {},
                    "updated_at": datetime.now(UTC).isoformat(),
                }.items()
            }
        self.db.records["system", "local"] = {
            "system_id": {"S": "local"},
            "desired_game_id": {"S": catalog[0]},
        }
        super().__init__(
            self.db,
            self,
            {key: key for key in ("system", "operation", "idempotency", "games")},
            "local",
            policy,
            catalog,
            {catalog[1]: {"retain_previous": 3}},
            "local-only",
        )

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        event = json.loads(kwargs["Payload"])
        if self.scenario in {"conflict", "rejection"}:
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(
                    json.dumps(
                        {"error": "conflict" if self.scenario == "conflict" else "invalid_input"}
                    ).encode()
                ),
            }
        if self.scenario == "players" and event["operation_type"] in {"SWITCH", "RESET"}:
            return {"StatusCode": 200, "Payload": io.BytesIO(b'{"error":"conflict"}')}
        web = admission_actor(event["web"], event["operation_type"], self.policy)
        result = self.domain.admit(
            operation_type=OperationType(event["operation_type"]),
            idempotency_key=event["idempotency_key"],
            requested_by=RequestSource.WEB,
            requested_at=datetime.now(UTC),
            target_game_id=event.get("target_game_id"),
            reset_seed_mode=event.get("seed_mode"),
            web=web,
        )
        if result.created:
            self.started[result.operation_id] = datetime.now(UTC).timestamp()
        return {
            "StatusCode": 200,
            "Payload": io.BytesIO(
                json.dumps(
                    {"operation_id": result.operation_id, "created": result.created}
                ).encode()
            ),
        }

    def read(self, actor: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        with self.db.mutex:
            for operation_id, started in self.started.items():
                elapsed = datetime.now(UTC).timestamp() - started
                item = self.db.records["operation", operation_id]
                if elapsed > 2:
                    item["status"] = {"S": "RUNNING"}
                    item["current_step"] = {"S": "RECONCILING"}
                    item["progress_reconciling_at"] = {"S": datetime.now(UTC).isoformat()}
                if elapsed > 7:
                    item["status"] = {"S": "FAILED" if self.scenario == "failure" else "SUCCEEDED"}
                    item["completed_at"] = {"S": datetime.now(UTC).isoformat()}
                    self.db.records["system", "local"]["current_operation_id"] = {"NULL": True}
                    self.db.records.pop(("locks", "minecraft-control"), None)
                item["updated_at"] = {"S": datetime.now(UTC).isoformat()}
        return super().read(actor, request_id)
