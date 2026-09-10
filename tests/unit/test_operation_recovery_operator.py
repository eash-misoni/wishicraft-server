from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import cast

import pytest

from wishicraft.operation_recovery_operator import recover_failed_scheduled_stop


class Dynamo:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, object]] = {
            "operations": {
                "operation_type": {"S": "STOP"},
                "requested_by": {"M": {"source": {"S": "SCHEDULE"}}},
                "status": {"S": "PENDING"},
                "lease_id": {"S": "lease-001"},
                "workflow_execution_arn": {"S": "arn:execution"},
                "timeout_at": {"S": "2026-09-10T04:31:49Z"},
                "idempotency_key": {"S": "auto-stop:asi-001"},
            },
            "locks": {
                "resource_id": {"S": "wishicraft-main"},
                "owner_operation_id": {"S": "op-001"},
                "lease_id": {"S": "lease-001"},
            },
            "states": {"current_operation_id": {"S": "op-001"}},
            "intents": {
                "game_id": {"S": "game-vanilla-main"},
                "status": {"S": "STOP_REQUESTED"},
                "stop_operation_id": {"S": "op-001"},
            },
        }
        self.transactions: list[dict[str, object]] = []

    def get_item(self, **kwargs: object) -> object:
        return {"Item": self.items[cast(str, kwargs["TableName"])]}

    def transact_write_items(self, **kwargs: object) -> object:
        self.transactions.append(kwargs)
        return {}

    def update_item(self, **kwargs: object) -> object:
        raise AssertionError(kwargs)

    def delete_item(self, **kwargs: object) -> object:
        raise AssertionError(kwargs)


class Steps:
    mutation_reached = False

    def describe_execution(self, **kwargs: object) -> object:
        return {
            "status": "FAILED",
            "error": "STOP_CLEANUP_FAILED",
            "input": json.dumps(
                {
                    "operation_id": "op-001",
                    "lease_id": "lease-001",
                    "requested_by": "SCHEDULE",
                    "auto_stop_intent_id": "asi-001",
                }
            ),
        }

    def get_execution_history(self, **kwargs: object) -> object:
        names = ["ReconcileBeforeStop", "AutomaticStopFinalGate"]
        if self.mutation_reached:
            names.append("SetDesiredStopped")
        return {
            "events": [
                {
                    "type": "TaskStateEntered",
                    "stateEnteredEventDetails": {"name": name},
                }
                for name in names
            ]
        }


class Reconcile:
    def invoke(self, **kwargs: object) -> object:
        return {
            "Payload": io.BytesIO(
                json.dumps(
                    {
                        "system_id": "wishicraft-main",
                        "game_id": "game-vanilla-main",
                        "desired_state": "RUNNING",
                        "health": "HEALTHY",
                        "discrepancies": [],
                        "observation_errors": [],
                        "observed_at": "2026-09-10T04:32:01Z",
                        "observation": {
                            "instance_id": "i-target",
                            "ec2_state": "running",
                            "runtime_ready": True,
                            "minecraft_protocol_state": "ready",
                            "dns_state": "present",
                            "expected_game_id": "game-vanilla-main",
                            "observed_active_game_id": "game-vanilla-main",
                        },
                    }
                ).encode()
            )
        }


class Ec2:
    def describe_volumes(self, **kwargs: object) -> object:
        return {
            "Volumes": [
                {
                    "VolumeId": "vol-data",
                    "Encrypted": True,
                    "Attachments": [
                        {
                            "InstanceId": "i-target",
                            "Device": "/dev/sdf",
                            "State": "attached",
                            "DeleteOnTermination": False,
                        }
                    ],
                }
            ]
        }


def recover(dynamo: Dynamo, *, steps: Steps | None = None) -> None:
    recover_failed_scheduled_stop(
        dynamodb=dynamo,
        step_functions=steps or Steps(),
        reconcile=Reconcile(),
        ec2=Ec2(),
        operation_id="op-001",
        operations_table="operations",
        locks_table="locks",
        system_state_table="states",
        intents_table="intents",
        reconcile_function="reconcile",
        system_id="wishicraft-main",
        game_id="game-vanilla-main",
        lock_name="minecraft-control",
        data_volume_id="vol-data",
        data_volume_device="/dev/sdf",
        now=datetime(2026, 9, 10, 4, 32, 2, tzinfo=UTC),
    )


def test_recovery_uses_existing_owned_atomic_stale_primitive() -> None:
    dynamo = Dynamo()
    recover(dynamo)
    items = cast(list[dict[str, object]], dynamo.transactions[0]["TransactItems"])
    assert len(items) == 3
    update = cast(dict[str, object], items[0]["Update"])
    values = cast(dict[str, object], update["ExpressionAttributeValues"])
    assert values[":status"] == {"S": "FAILED"}
    assert cast(dict[str, object], values[":error"])["M"] == {
        "code": {"S": "STOP_PRECONDITION_FAILED"},
        "message": {"NULL": True},
        "detail_ref": {"NULL": True},
        "retryable": {"NULL": True},
    }


def test_recovery_rejects_commit_point_or_wrong_intent_without_write() -> None:
    dynamo = Dynamo()
    steps = Steps()
    steps.mutation_reached = True
    with pytest.raises(RuntimeError, match="pre-commit"):
        recover(dynamo, steps=steps)
    assert dynamo.transactions == []

    steps.mutation_reached = False
    dynamo.items["intents"]["status"] = {"S": "WARNING_DELIVERED"}
    with pytest.raises(RuntimeError, match="Intent identity"):
        recover(dynamo, steps=steps)
    assert dynamo.transactions == []


def test_recovery_does_not_bypass_operation_deadline() -> None:
    dynamo = Dynamo()
    dynamo.items["operations"]["timeout_at"] = {"S": "2026-09-10T04:33:00Z"}
    with pytest.raises(RuntimeError, match="deadline"):
        recover(dynamo)
    assert dynamo.transactions == []
