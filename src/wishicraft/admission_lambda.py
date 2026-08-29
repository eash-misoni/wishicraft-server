"""Thin versioned Lambda adapter for Phase 4 Operation admission."""

from __future__ import annotations

import importlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    OperationAdmissionRepository,
    OperationAdmissionService,
    OperationRepository,
    OperationStatus,
    OperationType,
    RequestSource,
)


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class StepFunctionsApi(Protocol):
    def start_execution(self, **kwargs: object) -> object: ...
    def describe_execution(self, **kwargs: object) -> object: ...


_service: OperationAdmissionService | None = None
_launcher: WorkflowLauncher | None = None
_stop_launcher: WorkflowLauncher | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    operation_type, idempotency_key, requested_by = _parse_event(event)
    result = _get_service().admit(
        operation_type=operation_type,
        idempotency_key=idempotency_key,
        requested_by=requested_by,
        requested_at=datetime.now(UTC),
    )
    if result.created and operation_type is OperationType.START:
        if result.lease_id is None:
            raise RuntimeError("START admission did not create a lease")
        _get_launcher().start(
            operation_id=result.operation_id,
            lease_id=result.lease_id,
            started_at=datetime.now(UTC),
        )
    if result.created and operation_type is OperationType.STOP:
        if result.lease_id is None:
            raise RuntimeError("STOP admission did not create a lease")
        _get_stop_launcher().start(
            operation_id=result.operation_id,
            lease_id=result.lease_id,
            started_at=datetime.now(UTC),
        )
    return {
        "schema_version": 1,
        "operation_id": result.operation_id,
        "created": result.created,
        "lease_id": result.lease_id,
    }


class WorkflowLauncher:
    def __init__(
        self,
        step_functions: StepFunctionsApi,
        dynamodb: DynamoApi,
        *,
        state_machine_environment: str = "START_STATE_MACHINE_ARN",
    ) -> None:
        self._step_functions = step_functions
        self._dynamodb = dynamodb
        self._state_machine_arn = _required_environment(state_machine_environment)
        self._operations_table = _required_environment("OPERATIONS_TABLE")
        self._operations = OperationRepository(
            dynamodb,
            operations_table=self._operations_table,
            locks_table=_required_environment("LOCKS_TABLE"),
            system_state_table=_required_environment("SYSTEM_STATE_TABLE"),
            system_id=_required_environment("SYSTEM_ID"),
            lock_name=_required_environment("GLOBAL_LOCK_NAME"),
        )

    def start(self, *, operation_id: str, lease_id: str, started_at: datetime) -> None:
        proof = LeaseProof(_required_environment("SYSTEM_ID"), operation_id, lease_id, 0)
        prefix, separator, state_machine_name = self._state_machine_arn.rpartition(":stateMachine:")
        if not separator or not state_machine_name:
            raise RuntimeError("invalid START State Machine ARN")
        execution_arn = f"{prefix}:execution:{state_machine_name}:{operation_id}"
        execution_registered = False
        try:
            self._dynamodb.update_item(
                TableName=self._operations_table,
                Key={"operation_id": {"S": operation_id}},
                UpdateExpression=(
                    "SET workflow_execution_name = :name, workflow_execution_arn = :arn, "
                    "started_at = :started_at, updated_at = :started_at"
                ),
                ConditionExpression=(
                    "#status = :pending AND lease_id = :lease_id "
                    "AND attribute_type(workflow_execution_arn, :null_type)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":name": {"S": operation_id},
                    ":arn": {"S": execution_arn},
                    ":started_at": {"S": started_at.isoformat().replace("+00:00", "Z")},
                    ":pending": {"S": OperationStatus.PENDING.value},
                    ":lease_id": {"S": lease_id},
                    ":null_type": {"S": "NULL"},
                },
            )
            execution_registered = True
            response = self._step_functions.start_execution(
                stateMachineArn=self._state_machine_arn,
                name=operation_id,
                input=json.dumps(
                    {
                        "schema_version": 1,
                        "operation_id": operation_id,
                        "lease_id": lease_id,
                    },
                    separators=(",", ":"),
                ),
            )
            returned_arn = response.get("executionArn") if isinstance(response, dict) else None
            if returned_arn != execution_arn:
                raise RuntimeError("malformed Step Functions start response")
        except Exception:
            execution_exists = (
                self._execution_exists(execution_arn) if execution_registered else False
            )
            if execution_exists is True:
                return
            if execution_exists is False:
                self._operations.complete_owned(
                    proof=proof,
                    status=OperationStatus.FAILED,
                    completed_at=started_at,
                    error_code="WORKFLOW_START_FAILED",
                )
            # Unknown execution state deliberately retains Operation/Lock for fresh
            # reconcile and explicit stale recovery; it must not release a live owner.
            raise

    def _execution_exists(self, execution_arn: str) -> bool | None:
        try:
            response = self._step_functions.describe_execution(executionArn=execution_arn)
        except Exception as error:
            response = getattr(error, "response", None)
            detail = response.get("Error") if isinstance(response, dict) else None
            if isinstance(detail, dict) and detail.get("Code") == "ExecutionDoesNotExist":
                return False
            return None
        if not isinstance(response, dict):
            return None
        return response.get("status") in {
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
            "ABORTED",
            "PENDING_REDRIVE",
        }


def _parse_event(event: object) -> tuple[OperationType, str, RequestSource]:
    if not isinstance(event, dict) or set(event) != {
        "schema_version",
        "operation",
        "operation_type",
        "idempotency_key",
        "requested_by",
    }:
        raise ValueError("invalid Operation admission invocation")
    if event.get("schema_version") != 1 or event.get("operation") != "admit":
        raise ValueError("invalid Operation admission invocation")
    operation_type = event.get("operation_type")
    idempotency_key = event.get("idempotency_key")
    requested_by = event.get("requested_by")
    if not isinstance(operation_type, str) or not isinstance(idempotency_key, str):
        raise ValueError("invalid Operation admission invocation")
    if not isinstance(requested_by, str):
        raise ValueError("invalid Operation admission invocation")
    try:
        return OperationType(operation_type), idempotency_key, RequestSource(requested_by)
    except ValueError as error:
        raise ValueError("invalid Operation admission invocation") from error


def _get_service() -> OperationAdmissionService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def _get_launcher() -> WorkflowLauncher:
    global _launcher
    if _launcher is None:
        boto3 = importlib.import_module("boto3")
        session = cast(AwsSession, boto3)
        region = _required_environment("AWS_REGION")
        _launcher = WorkflowLauncher(
            cast(StepFunctionsApi, session.client("stepfunctions", region_name=region)),
            cast(DynamoApi, session.client("dynamodb", region_name=region)),
        )
    return _launcher


def _get_stop_launcher() -> WorkflowLauncher:
    global _stop_launcher
    if _stop_launcher is None:
        boto3 = importlib.import_module("boto3")
        session = cast(AwsSession, boto3)
        region = _required_environment("AWS_REGION")
        _stop_launcher = WorkflowLauncher(
            cast(StepFunctionsApi, session.client("stepfunctions", region_name=region)),
            cast(DynamoApi, session.client("dynamodb", region_name=region)),
            state_machine_environment="STOP_STATE_MACHINE_ARN",
        )
    return _stop_launcher


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _build_service() -> OperationAdmissionService:
    boto3 = importlib.import_module("boto3")
    session = cast(AwsSession, boto3)
    dynamodb = cast(
        DynamoApi,
        session.client("dynamodb", region_name=_required_environment("AWS_REGION")),
    )
    repository = OperationAdmissionRepository(
        dynamodb,
        operations_table=_required_environment("OPERATIONS_TABLE"),
        games_table=_required_environment("GAMES_TABLE"),
        idempotency_table=_required_environment("IDEMPOTENCY_TABLE"),
        locks_table=_required_environment("LOCKS_TABLE"),
        system_state_table=_required_environment("SYSTEM_STATE_TABLE"),
        system_id=_required_environment("SYSTEM_ID"),
        lock_name=_required_environment("GLOBAL_LOCK_NAME"),
        lease_seconds=int(_required_environment("LOCK_LEASE_SECONDS")),
        lease_id_factory=lambda: f"lease-{uuid.uuid4()}",
    )
    timeout_by_type = {
        operation_type: int(_required_environment(f"{operation_type.value}_TIMEOUT_SECONDS"))
        for operation_type in (
            OperationType.STATUS,
            OperationType.START,
            OperationType.STOP,
            OperationType.BACKUP,
        )
    }
    return OperationAdmissionService(
        repository,
        game_id=_required_environment("GAME_ID"),
        timeout_seconds=timeout_by_type,
        operation_id_factory=lambda: f"op-{uuid.uuid4()}",
    )
