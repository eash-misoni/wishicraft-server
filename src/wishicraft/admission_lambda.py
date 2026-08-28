"""Thin versioned Lambda adapter for Phase 4 Operation admission."""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.operation import (
    DynamoApi,
    OperationAdmissionRepository,
    OperationAdmissionService,
    OperationType,
    RequestSource,
)


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


_service: OperationAdmissionService | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    operation_type, idempotency_key, requested_by = _parse_event(event)
    result = _get_service().admit(
        operation_type=operation_type,
        idempotency_key=idempotency_key,
        requested_by=requested_by,
        requested_at=datetime.now(UTC),
    )
    return {
        "schema_version": 1,
        "operation_id": result.operation_id,
        "created": result.created,
        "lease_id": result.lease_id,
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
