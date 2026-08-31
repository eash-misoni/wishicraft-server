"""DynamoDB Stream driven asynchronous STATUS executor."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.operation import DynamoApi, OperationRepository, OperationStatus
from wishicraft.status_projection import project_status, unavailable_projection


class PayloadStream(Protocol):
    def read(self) -> bytes: ...


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class StatusOperations(Protocol):
    def unlocked_status_state(self, operation_id: str) -> OperationStatus: ...
    def update_step(
        self,
        *,
        operation_id: str,
        current_step: str,
        status: OperationStatus,
        updated_at: datetime,
    ) -> None: ...

    def complete_unlocked(
        self,
        *,
        operation_id: str,
        status: OperationStatus,
        completed_at: datetime,
        error_code: str | None = None,
        result: dict[str, object] | None = None,
    ) -> None: ...


class FreshReconcile(Protocol):
    def reconcile(self) -> dict[str, object]: ...


class ReconcileInvoker:
    def __init__(self, api: LambdaApi, *, function_name: str) -> None:
        self._api = api
        self._function_name = function_name

    def reconcile(self) -> dict[str, object]:
        response = self._api.invoke(
            FunctionName=self._function_name,
            InvocationType="RequestResponse",
            Payload=b'{"schema_version":1,"operation":"reconcile"}',
        )
        if not isinstance(response, dict) or response.get("StatusCode") != 200:
            raise RuntimeError("Reconcile invocation failed")
        if response.get("FunctionError") is not None:
            raise RuntimeError("Reconcile invocation failed")
        payload = response.get("Payload")
        if not hasattr(payload, "read"):
            raise RuntimeError("Reconcile invocation failed")
        raw = cast(PayloadStream, payload).read()
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Reconcile invocation failed") from error
        if not isinstance(value, dict):
            raise RuntimeError("Reconcile invocation failed")
        return value


class StatusExecutor:
    def __init__(
        self,
        operations: StatusOperations,
        reconcile: FreshReconcile,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._operations = operations
        self._reconcile = reconcile
        self._clock = clock

    def execute(self, *, operation_id: str) -> None:
        current = self._operations.unlocked_status_state(operation_id)
        if current in {
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
            OperationStatus.TIMED_OUT,
            OperationStatus.CANCELLED,
        }:
            return
        self._operations.update_step(
            operation_id=operation_id,
            current_step="RECONCILING",
            status=OperationStatus.RUNNING,
            updated_at=self._clock(),
        )
        try:
            projection = project_status(self._reconcile.reconcile())
        except Exception:  # noqa: BLE001 - async boundary terminalizes without raw detail.
            self._operations.complete_unlocked(
                operation_id=operation_id,
                status=OperationStatus.FAILED,
                completed_at=self._clock(),
                error_code="STATUS_RECONCILE_FAILED",
                result=unavailable_projection(),
            )
            return
        self._operations.complete_unlocked(
            operation_id=operation_id,
            status=OperationStatus.SUCCEEDED,
            completed_at=self._clock(),
            result=projection,
        )


_executor: StatusExecutor | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    operation_ids = _operation_ids(event)
    executor = _get_executor()
    for operation_id in operation_ids:
        executor.execute(operation_id=operation_id)
    return {"batchItemFailures": []}


def _operation_ids(event: object) -> tuple[str, ...]:
    if not isinstance(event, dict) or not isinstance(event.get("Records"), list):
        raise ValueError("invalid STATUS stream event")
    result: list[str] = []
    for raw_record in event["Records"]:
        if not isinstance(raw_record, dict) or raw_record.get("eventName") != "INSERT":
            raise ValueError("invalid STATUS stream event")
        dynamodb = raw_record.get("dynamodb")
        if not isinstance(dynamodb, dict) or not isinstance(dynamodb.get("NewImage"), dict):
            raise ValueError("invalid STATUS stream event")
        image = dynamodb["NewImage"]
        assert isinstance(image, dict)
        operation_id = _dynamo_string(image, "operation_id")
        if (
            _dynamo_string(image, "operation_type") != "STATUS"
            or image.get("lock_name") != {"NULL": True}
            or _dynamo_string(image, "status") != "PENDING"
        ):
            raise ValueError("invalid STATUS stream event")
        result.append(operation_id)
    if not result:
        raise ValueError("invalid STATUS stream event")
    return tuple(result)


def _dynamo_string(image: dict[str, object], name: str) -> str:
    attribute = image.get(name)
    if not isinstance(attribute, dict) or not isinstance(attribute.get("S"), str):
        raise ValueError("invalid STATUS stream event")
    value = attribute.get("S")
    assert isinstance(value, str)
    if not value:
        raise ValueError("invalid STATUS stream event")
    return value


def _get_executor() -> StatusExecutor:
    global _executor
    if _executor is None:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
        region = _required_environment("AWS_REGION")
        dynamodb = cast(DynamoApi, boto3.client("dynamodb", region_name=region))
        lambda_api = cast(
            LambdaApi,
            boto3.client(
                "lambda",
                region_name=region,
                config=botocore_config.Config(
                    connect_timeout=3,
                    read_timeout=125,
                    retries={"max_attempts": 2, "mode": "standard"},
                ),
            ),
        )
        _executor = StatusExecutor(
            OperationRepository(
                dynamodb,
                operations_table=_required_environment("OPERATIONS_TABLE"),
                locks_table=_required_environment("LOCKS_TABLE"),
                system_state_table=_required_environment("SYSTEM_STATE_TABLE"),
                system_id=_required_environment("SYSTEM_ID"),
                lock_name=_required_environment("GLOBAL_LOCK_NAME"),
            ),
            ReconcileInvoker(
                lambda_api, function_name=_required_environment("RECONCILE_FUNCTION_NAME")
            ),
        )
    return _executor


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value
