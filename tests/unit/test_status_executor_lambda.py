from __future__ import annotations

import io
import json

import pytest

from wishicraft import status_executor_lambda
from wishicraft.operation import OperationStatus


class Operations:
    def __init__(self, state: OperationStatus = OperationStatus.PENDING) -> None:
        self.state = state
        self.steps: list[dict[str, object]] = []
        self.completions: list[dict[str, object]] = []

    def unlocked_status_state(self, operation_id: str) -> OperationStatus:
        return self.state

    def update_step(self, **kwargs: object) -> None:
        self.steps.append(kwargs)

    def complete_unlocked(self, **kwargs: object) -> None:
        self.completions.append(kwargs)


class Reconcile:
    def __init__(self, result: dict[str, object] | Exception) -> None:
        self.result = result
        self.calls = 0

    def reconcile(self) -> dict[str, object]:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def reconciled_state() -> dict[str, object]:
    return {
        "schema_version": 1,
        "desired_state": "STOPPED",
        "health": "HEALTHY",
        "observed_at": "2026-08-31T00:00:00.000000Z",
        "observation": {
            "ec2_state": "stopped",
            "runtime_ready": False,
            "dns_state": "absent",
            "dns_record_name": "mc-dev.wishicraft.net.",
        },
        "discrepancies": [],
        "observation_errors": [],
    }


def stream_event() -> dict[str, object]:
    return {
        "Records": [
            {
                "eventName": "INSERT",
                "dynamodb": {
                    "NewImage": {
                        "operation_id": {"S": "op-status-001"},
                        "operation_type": {"S": "STATUS"},
                        "status": {"S": "PENDING"},
                        "lock_name": {"NULL": True},
                    }
                },
            }
        ]
    }


def test_executor_runs_fresh_reconcile_and_existing_unlocked_terminalization() -> None:
    operations = Operations()
    reconcile = Reconcile(reconciled_state())
    status_executor_lambda.StatusExecutor(operations, reconcile).execute(
        operation_id="op-status-001"
    )
    assert reconcile.calls == 1
    assert operations.steps == [
        {
            "operation_id": "op-status-001",
            "current_step": "RECONCILING",
            "status": OperationStatus.RUNNING,
            "updated_at": operations.steps[0]["updated_at"],
        }
    ]
    assert operations.completions[0]["status"] is OperationStatus.SUCCEEDED
    result = operations.completions[0]["result"]
    assert isinstance(result, dict)
    assert result["status"] == "stopped"


def test_executor_retry_uses_same_operation_and_skips_terminal_result() -> None:
    operations = Operations(OperationStatus.SUCCEEDED)
    reconcile = Reconcile(reconciled_state())
    status_executor_lambda.StatusExecutor(operations, reconcile).execute(
        operation_id="op-status-001"
    )
    assert reconcile.calls == 0
    assert operations.steps == []
    assert operations.completions == []


def test_reconcile_failure_terminalizes_status_failed_without_raw_detail() -> None:
    operations = Operations()
    reconcile = Reconcile(RuntimeError("raw SSM stderr and secret-like detail"))
    status_executor_lambda.StatusExecutor(operations, reconcile).execute(
        operation_id="op-status-001"
    )
    completion = operations.completions[0]
    assert completion["status"] is OperationStatus.FAILED
    assert completion["error_code"] == "STATUS_RECONCILE_FAILED"
    assert "raw SSM" not in str(completion)
    result = completion["result"]
    assert isinstance(result, dict)
    assert result["status"] == "unknown"


def test_stream_handler_passes_admitted_operation_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Executor:
        calls: list[str] = []

        def execute(self, *, operation_id: str) -> None:
            self.calls.append(operation_id)

    executor = Executor()
    monkeypatch.setattr(status_executor_lambda, "_executor", executor)
    assert status_executor_lambda.handler(stream_event(), None) == {"batchItemFailures": []}
    assert executor.calls == ["op-status-001"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda event: event["Records"][0].update({"eventName": "MODIFY"}),
        lambda event: event["Records"][0]["dynamodb"]["NewImage"].update(
            {"operation_type": {"S": "START"}}
        ),
        lambda event: event["Records"][0]["dynamodb"]["NewImage"].update(
            {"lock_name": {"S": "minecraft-control"}}
        ),
    ],
)
def test_stream_boundary_rejects_non_status_or_locked_record(mutation: object) -> None:
    event = stream_event()
    assert callable(mutation)
    mutation(event)
    with pytest.raises(ValueError, match="invalid STATUS stream event"):
        status_executor_lambda.handler(event, None)


def test_reconcile_invoker_requires_successful_lambda_payload() -> None:
    class Api:
        def invoke(self, **kwargs: object) -> object:
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(json.dumps(reconciled_state()).encode()),
            }

    assert (
        status_executor_lambda.ReconcileInvoker(Api(), function_name="reconcile").reconcile()[
            "health"
        ]
        == "HEALTHY"
    )
