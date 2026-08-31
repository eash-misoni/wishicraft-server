"""Phase 4 Operation admission and lease-lock persistence contracts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from wishicraft.system_state import utc_timestamp


class OperationType(StrEnum):
    STATUS = "STATUS"
    START = "START"
    STOP = "STOP"
    BACKUP = "BACKUP"
    CREATE = "CREATE"
    RESET = "RESET"
    OP_ADD = "OP_ADD"
    OP_REMOVE = "OP_REMOVE"

    @property
    def requires_lock(self) -> bool:
        return self is not OperationType.STATUS


class OperationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class RequestSource(StrEnum):
    DISCORD = "DISCORD"
    WEB = "WEB"
    SCHEDULE = "SCHEDULE"
    ADMIN = "ADMIN"
    CLI = "CLI"


@dataclass(frozen=True)
class OperationRequest:
    operation_id: str
    idempotency_key: str
    operation_type: OperationType
    target_game_id: str | None
    requested_by: RequestSource
    requested_at: datetime
    timeout_at: datetime | None

    def __post_init__(self) -> None:
        _validate_identifier(self.operation_id, "operation")
        _validate_identifier(self.idempotency_key, "idempotency")
        if (
            self.target_game_id is not None
            and re.fullmatch(r"game-[a-z0-9]+(?:-[a-z0-9]+)*", self.target_game_id) is None
        ):
            raise ValueError("invalid target game identity")
        utc_timestamp(self.requested_at)
        if self.timeout_at is not None:
            utc_timestamp(self.timeout_at)
            if self.timeout_at <= self.requested_at:
                raise ValueError("operation timeout must follow request time")


@dataclass(frozen=True)
class AdmissionResult:
    operation_id: str
    created: bool
    lease_id: str | None


@dataclass(frozen=True)
class IdempotencyRecord:
    operation_id: str
    operation_type: OperationType
    requested_by: RequestSource
    target_game_id: str | None


@dataclass(frozen=True)
class LeaseProof:
    resource_id: str
    owner_operation_id: str
    lease_id: str
    lease_expires_at: int

    def __post_init__(self) -> None:
        if not self.resource_id or not self.owner_operation_id or not self.lease_id:
            raise ValueError("lease identity must be non-empty")
        if self.lease_expires_at < 0:
            raise ValueError("invalid lease expiry")


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def transact_write_items(self, **kwargs: object) -> object: ...
    def update_item(self, **kwargs: object) -> object: ...
    def delete_item(self, **kwargs: object) -> object: ...


class AdmissionConflict(RuntimeError):
    """A competing operation or stale ownership record blocked admission."""


class LeaseLost(RuntimeError):
    """The caller no longer possesses the current unexpired lease."""


class OperationAdmissionRepository:
    def __init__(
        self,
        api: DynamoApi,
        *,
        operations_table: str,
        games_table: str,
        idempotency_table: str,
        locks_table: str,
        system_state_table: str,
        system_id: str,
        lock_name: str,
        lease_seconds: int,
        lease_id_factory: Callable[[], str],
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        self._api = api
        self._operations = operations_table
        self._games = games_table
        self._idempotency = idempotency_table
        self._locks = locks_table
        self._system_state = system_state_table
        self._system_id = system_id
        self._lock_name = lock_name
        self._lease_seconds = lease_seconds
        self._lease_id_factory = lease_id_factory

    def admit(self, request: OperationRequest) -> AdmissionResult:
        existing = self.existing(request)
        if existing is not None:
            return existing
        lease_id = self._lease_id_factory() if request.operation_type.requires_lock else None
        if lease_id is not None:
            _validate_identifier(lease_id, "lease")
        transaction = [
            self._idempotency_put(request),
            self._operation_put(request, lease_id),
        ]
        if request.target_game_id is not None:
            transaction.append(self._game_condition(request.target_game_id))
        if lease_id is not None:
            transaction.extend(self._ownership_transaction(request, lease_id))
        try:
            self._api.transact_write_items(
                TransactItems=transaction,
            )
        except Exception as error:
            if not _is_transaction_cancelled(error):
                raise
            existing = self.existing(request)
            if existing is not None:
                return existing
            raise AdmissionConflict("operation admission conflict") from error
        return AdmissionResult(request.operation_id, True, lease_id)

    def existing(self, request: OperationRequest) -> AdmissionResult | None:
        return self.existing_for(
            idempotency_key=request.idempotency_key,
            operation_type=request.operation_type,
            requested_by=request.requested_by,
            target_game_id=request.target_game_id,
        )

    def existing_for(
        self,
        *,
        idempotency_key: str,
        operation_type: OperationType,
        requested_by: RequestSource,
        target_game_id: str | None,
    ) -> AdmissionResult | None:
        record = self._existing_record(idempotency_key)
        if record is None:
            return None
        if (
            record.operation_type is not operation_type
            or record.requested_by is not requested_by
            or record.target_game_id != target_game_id
        ):
            raise AdmissionConflict("idempotency key payload conflict")
        return AdmissionResult(record.operation_id, False, None)

    def _existing_record(self, idempotency_key: str) -> IdempotencyRecord | None:
        response = self._api.get_item(
            TableName=self._idempotency,
            Key={"idempotency_key": {"S": idempotency_key}},
            ProjectionExpression=("operation_id, operation_type, #source, target_game_id"),
            ExpressionAttributeNames={"#source": "source"},
            ConsistentRead=True,
        )
        if not isinstance(response, dict):
            raise ValueError("malformed idempotency response")
        item = response.get("Item")
        if item is None:
            return None
        if not isinstance(item, dict):
            raise ValueError("malformed idempotency item")
        raw = item.get("operation_id")
        if not isinstance(raw, dict):
            raise ValueError("malformed idempotency operation identity")
        value = raw.get("S")
        if not isinstance(value, str):
            raise ValueError("malformed idempotency operation identity")
        operation_type = _string_attribute(item, "operation_type")
        source = _string_attribute(item, "source")
        target_game_id = _nullable_string_attribute(item, "target_game_id")
        try:
            return IdempotencyRecord(
                value,
                OperationType(operation_type),
                RequestSource(source),
                target_game_id,
            )
        except ValueError as error:
            raise ValueError("malformed idempotency item") from error

    def _idempotency_put(self, request: OperationRequest) -> dict[str, object]:
        return {
            "Put": {
                "TableName": self._idempotency,
                "Item": _attribute_map(
                    {
                        "idempotency_key": request.idempotency_key,
                        "operation_id": request.operation_id,
                        "operation_type": request.operation_type.value,
                        "source": request.requested_by.value,
                        "target_game_id": request.target_game_id,
                        "created_at": utc_timestamp(request.requested_at),
                        "expires_at": None,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(idempotency_key)",
            }
        }

    def _operation_put(self, request: OperationRequest, lease_id: str | None) -> dict[str, object]:
        return {
            "Put": {
                "TableName": self._operations,
                "Item": _attribute_map(
                    {
                        "operation_id": request.operation_id,
                        "schema_version": 1,
                        "idempotency_key": request.idempotency_key,
                        "workflow_execution_name": None,
                        "workflow_execution_arn": None,
                        "operation_type": request.operation_type.value,
                        "target_game_id": request.target_game_id,
                        "requested_by": {
                            "source": request.requested_by.value,
                            "discord_user_id": None,
                            "display_name": None,
                        },
                        "requested_at": utc_timestamp(request.requested_at),
                        "started_at": None,
                        "completed_at": None,
                        "status": OperationStatus.PENDING.value,
                        "current_step": "ADMITTED",
                        "timeout_at": (
                            utc_timestamp(request.timeout_at)
                            if request.timeout_at is not None
                            else None
                        ),
                        "lock_name": self._lock_name if lease_id is not None else None,
                        "lease_id": lease_id,
                        "error": {
                            "code": None,
                            "message": None,
                            "detail_ref": None,
                            "retryable": None,
                        },
                        "discord": {
                            "guild_id": None,
                            "interaction_id": None,
                            "channel_id": None,
                            "message_id": None,
                        },
                        "result": None,
                        "updated_at": utc_timestamp(request.requested_at),
                        "expires_at": None,
                    }
                ),
                "ConditionExpression": "attribute_not_exists(operation_id)",
            }
        }

    def _ownership_transaction(
        self, request: OperationRequest, lease_id: str
    ) -> list[dict[str, object]]:
        requested_epoch = int(request.requested_at.timestamp())
        return [
            {
                "Put": {
                    "TableName": self._locks,
                    "Item": _attribute_map(
                        {
                            "lock_name": self._lock_name,
                            "resource_id": self._system_id,
                            "owner_operation_id": request.operation_id,
                            "lease_id": lease_id,
                            "acquired_at": utc_timestamp(request.requested_at),
                            "lease_expires_at": requested_epoch + self._lease_seconds,
                            "updated_at": utc_timestamp(request.requested_at),
                        }
                    ),
                    "ConditionExpression": "attribute_not_exists(lock_name)",
                }
            },
            {
                "Update": {
                    "TableName": self._system_state,
                    "Key": {"system_id": {"S": self._system_id}},
                    "UpdateExpression": "SET current_operation_id = :operation_id",
                    "ConditionExpression": (
                        "attribute_exists(system_id) AND "
                        "(attribute_not_exists(current_operation_id) OR "
                        "attribute_type(current_operation_id, :null_type))"
                    ),
                    "ExpressionAttributeValues": {
                        ":operation_id": {"S": request.operation_id},
                        ":null_type": {"S": "NULL"},
                    },
                }
            },
        ]

    def _game_condition(self, game_id: str) -> dict[str, object]:
        return {
            "ConditionCheck": {
                "TableName": self._games,
                "Key": {"game_id": {"S": game_id}},
                "ConditionExpression": ("attribute_exists(game_id) AND lifecycle_state = :active"),
                "ExpressionAttributeValues": {":active": {"S": "ACTIVE"}},
            }
        }


class OperationAdmissionService:
    def __init__(
        self,
        repository: OperationAdmissionRepository,
        *,
        game_id: str,
        timeout_seconds: dict[OperationType, int],
        operation_id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._game_id = game_id
        self._timeouts = timeout_seconds
        self._operation_id_factory = operation_id_factory

    def admit(
        self,
        *,
        operation_type: OperationType,
        idempotency_key: str,
        requested_by: RequestSource,
        requested_at: datetime,
    ) -> AdmissionResult:
        timeout_seconds = self._timeouts.get(operation_type)
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("operation timeout is not configured")
        existing = self._repository.existing_for(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            requested_by=requested_by,
            target_game_id=self._game_id,
        )
        if existing is not None:
            return existing
        operation_id = self._operation_id_factory()
        request = OperationRequest(
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            target_game_id=self._game_id,
            requested_by=requested_by,
            requested_at=requested_at,
            timeout_at=requested_at + timedelta(seconds=timeout_seconds),
        )
        return self._repository.admit(request)


class LeaseRepository:
    def __init__(self, api: DynamoApi, *, table_name: str, lock_name: str) -> None:
        self._api = api
        self._table = table_name
        self._lock_name = lock_name

    def verify_owned(self, proof: LeaseProof, *, now: datetime) -> None:
        response = self._api.get_item(
            TableName=self._table,
            Key={"lock_name": {"S": self._lock_name}},
            ConsistentRead=True,
        )
        if not isinstance(response, dict) or not isinstance(response.get("Item"), dict):
            raise LeaseLost("LOCK_LOST")
        item = response["Item"]
        assert isinstance(item, dict)
        try:
            owned = (
                _string_attribute(item, "resource_id") == proof.resource_id
                and _string_attribute(item, "owner_operation_id") == proof.owner_operation_id
                and _string_attribute(item, "lease_id") == proof.lease_id
                and _integer_attribute(item, "lease_expires_at") >= int(now.timestamp())
            )
        except ValueError as error:
            raise LeaseLost("LOCK_LOST") from error
        if not owned:
            raise LeaseLost("LOCK_LOST")

    def renew(self, proof: LeaseProof, *, now: datetime, lease_seconds: int) -> LeaseProof:
        if lease_seconds <= 0:
            raise ValueError("lease duration must be positive")
        now_epoch = int(now.timestamp())
        renewed = LeaseProof(
            proof.resource_id,
            proof.owner_operation_id,
            proof.lease_id,
            now_epoch + lease_seconds,
        )
        self._api.update_item(
            TableName=self._table,
            Key={"lock_name": {"S": self._lock_name}},
            UpdateExpression="SET lease_expires_at = :next_expiry, updated_at = :updated_at",
            ConditionExpression=(
                "resource_id = :resource_id AND owner_operation_id = :operation_id "
                "AND lease_id = :lease_id "
                "AND lease_expires_at >= :now"
            ),
            ExpressionAttributeValues={
                ":resource_id": {"S": proof.resource_id},
                ":operation_id": {"S": proof.owner_operation_id},
                ":lease_id": {"S": proof.lease_id},
                ":now": {"N": str(now_epoch)},
                ":next_expiry": {"N": str(renewed.lease_expires_at)},
                ":updated_at": {"S": utc_timestamp(now)},
            },
        )
        return renewed

    def release(self, proof: LeaseProof, *, now: datetime) -> None:
        self._api.delete_item(
            TableName=self._table,
            Key={"lock_name": {"S": self._lock_name}},
            ConditionExpression=(
                "resource_id = :resource_id AND owner_operation_id = :operation_id "
                "AND lease_id = :lease_id "
                "AND lease_expires_at >= :now"
            ),
            ExpressionAttributeValues={
                ":resource_id": {"S": proof.resource_id},
                ":operation_id": {"S": proof.owner_operation_id},
                ":lease_id": {"S": proof.lease_id},
                ":now": {"N": str(int(now.timestamp()))},
            },
        )


class OperationRepository:
    def __init__(
        self,
        api: DynamoApi,
        *,
        operations_table: str,
        locks_table: str,
        system_state_table: str,
        system_id: str,
        lock_name: str,
    ) -> None:
        self._api = api
        self._operations = operations_table
        self._locks = locks_table
        self._system_state = system_state_table
        self._system_id = system_id
        self._lock_name = lock_name

    def update_step(
        self,
        *,
        operation_id: str,
        current_step: str,
        status: OperationStatus,
        updated_at: datetime,
    ) -> None:
        if status not in {OperationStatus.PENDING, OperationStatus.RUNNING}:
            raise ValueError("step update requires non-terminal operation status")
        if not current_step:
            raise ValueError("operation step must be non-empty")
        self._api.update_item(
            TableName=self._operations,
            Key={"operation_id": {"S": operation_id}},
            UpdateExpression=(
                "SET #status = :status, current_step = :step, updated_at = :updated_at"
            ),
            ConditionExpression=(
                "attribute_exists(operation_id) AND #status IN (:pending, :running)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": {"S": status.value},
                ":step": {"S": current_step},
                ":updated_at": {"S": utc_timestamp(updated_at)},
                ":pending": {"S": OperationStatus.PENDING.value},
                ":running": {"S": OperationStatus.RUNNING.value},
            },
        )

    def complete_owned(
        self,
        *,
        proof: LeaseProof,
        status: OperationStatus,
        completed_at: datetime,
        error_code: str | None = None,
    ) -> None:
        if status not in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            raise ValueError("normal completion must be SUCCEEDED or FAILED")
        now_epoch = int(completed_at.timestamp())
        self._api.transact_write_items(
            TransactItems=[
                self._terminal_update(
                    proof.owner_operation_id,
                    status,
                    completed_at,
                    error_code,
                    extra_condition=None,
                ),
                self._lock_delete(proof, require_unexpired_at=now_epoch),
                self._current_operation_remove(proof.owner_operation_id),
            ],
        )

    def complete_unlocked(
        self,
        *,
        operation_id: str,
        status: OperationStatus,
        completed_at: datetime,
        error_code: str | None = None,
        result: dict[str, object] | None = None,
    ) -> None:
        if status not in {OperationStatus.SUCCEEDED, OperationStatus.FAILED}:
            raise ValueError("normal completion must be SUCCEEDED or FAILED")
        self._api.update_item(
            TableName=self._operations,
            Key={"operation_id": {"S": operation_id}},
            UpdateExpression=(
                "SET #status = :status, completed_at = :completed_at, "
                "updated_at = :completed_at, #error = :error, #result = :result"
            ),
            ConditionExpression=(
                "attribute_exists(operation_id) AND operation_type = :status_operation "
                "AND attribute_type(lock_name, :null_type) "
                "AND #status IN (:pending, :running)"
            ),
            ExpressionAttributeNames={
                "#status": "status",
                "#error": "error",
                "#result": "result",
            },
            ExpressionAttributeValues={
                ":status": {"S": status.value},
                ":completed_at": {"S": utc_timestamp(completed_at)},
                ":error": _attribute(
                    {
                        "code": error_code,
                        "message": None,
                        "detail_ref": None,
                        "retryable": None,
                    }
                ),
                ":result": _attribute(result),
                ":status_operation": {"S": OperationType.STATUS.value},
                ":null_type": {"S": "NULL"},
                ":pending": {"S": OperationStatus.PENDING.value},
                ":running": {"S": OperationStatus.RUNNING.value},
            },
        )

    def unlocked_status_state(self, operation_id: str) -> OperationStatus:
        _validate_identifier(operation_id, "operation")
        response = self._api.get_item(
            TableName=self._operations,
            Key={"operation_id": {"S": operation_id}},
            ProjectionExpression="operation_type, #status, lock_name",
            ExpressionAttributeNames={"#status": "status"},
            ConsistentRead=True,
        )
        if not isinstance(response, dict) or not isinstance(response.get("Item"), dict):
            raise ValueError("STATUS operation does not exist")
        item = response["Item"]
        assert isinstance(item, dict)
        if _string_attribute(item, "operation_type") != OperationType.STATUS.value:
            raise ValueError("operation is not STATUS")
        if item.get("lock_name") != {"NULL": True}:
            raise ValueError("STATUS operation must not have a lock")
        return OperationStatus(_string_attribute(item, "status"))

    def recover_stale(
        self,
        *,
        proof: LeaseProof,
        timeout_at: datetime,
        reconciled_at: datetime,
        status: OperationStatus,
        error_code: str,
    ) -> None:
        if status not in {
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
            OperationStatus.TIMED_OUT,
            OperationStatus.CANCELLED,
        }:
            raise ValueError("recovery conclusion must be terminal")
        if reconciled_at <= timeout_at:
            raise ValueError("stale recovery requires observation after operation deadline")
        if not error_code:
            raise ValueError("stale recovery requires classified evidence")
        self._api.transact_write_items(
            TransactItems=[
                self._terminal_update(
                    proof.owner_operation_id,
                    status,
                    reconciled_at,
                    error_code,
                    extra_condition="timeout_at = :timeout_at",
                    timeout_at=timeout_at,
                ),
                self._lock_delete(proof, require_unexpired_at=None),
                self._current_operation_remove(
                    proof.owner_operation_id, reconciled_at=reconciled_at
                ),
            ],
        )

    def _terminal_update(
        self,
        operation_id: str,
        status: OperationStatus,
        completed_at: datetime,
        error_code: str | None,
        *,
        extra_condition: str | None,
        timeout_at: datetime | None = None,
    ) -> dict[str, object]:
        values = {
            ":status": {"S": status.value},
            ":completed_at": {"S": utc_timestamp(completed_at)},
            ":error": _attribute(
                {
                    "code": error_code,
                    "message": None,
                    "detail_ref": None,
                    "retryable": None,
                }
            ),
            ":pending": {"S": OperationStatus.PENDING.value},
            ":running": {"S": OperationStatus.RUNNING.value},
        }
        condition = "#status IN (:pending, :running)"
        if extra_condition is not None:
            condition += f" AND {extra_condition}"
        if timeout_at is not None:
            values[":timeout_at"] = {"S": utc_timestamp(timeout_at)}
        return {
            "Update": {
                "TableName": self._operations,
                "Key": {"operation_id": {"S": operation_id}},
                "UpdateExpression": (
                    "SET #status = :status, completed_at = :completed_at, "
                    "updated_at = :completed_at, #error = :error"
                ),
                "ConditionExpression": condition,
                "ExpressionAttributeNames": {"#status": "status", "#error": "error"},
                "ExpressionAttributeValues": values,
            }
        }

    def _lock_delete(
        self, proof: LeaseProof, *, require_unexpired_at: int | None
    ) -> dict[str, object]:
        values: dict[str, object] = {
            ":resource_id": {"S": proof.resource_id},
            ":operation_id": {"S": proof.owner_operation_id},
            ":lease_id": {"S": proof.lease_id},
        }
        condition = (
            "resource_id = :resource_id AND owner_operation_id = :operation_id "
            "AND lease_id = :lease_id"
        )
        if require_unexpired_at is not None:
            condition += " AND lease_expires_at >= :now"
            values[":now"] = {"N": str(require_unexpired_at)}
        return {
            "Delete": {
                "TableName": self._locks,
                "Key": {"lock_name": {"S": self._lock_name}},
                "ConditionExpression": condition,
                "ExpressionAttributeValues": values,
            }
        }

    def _current_operation_remove(
        self, operation_id: str, *, reconciled_at: datetime | None = None
    ) -> dict[str, object]:
        condition = "current_operation_id = :operation_id"
        values: dict[str, object] = {":operation_id": {"S": operation_id}}
        if reconciled_at is not None:
            condition += " AND observed_at = :reconciled_at"
            values[":reconciled_at"] = {"S": utc_timestamp(reconciled_at)}
        return {
            "Update": {
                "TableName": self._system_state,
                "Key": {"system_id": {"S": self._system_id}},
                "UpdateExpression": "REMOVE current_operation_id",
                "ConditionExpression": condition,
                "ExpressionAttributeValues": values,
            }
        }


def _validate_identifier(value: str, kind: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise ValueError(f"invalid {kind} identity")


def _attribute(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, dict):
        return {"M": _attribute_map(value)}
    raise TypeError("unsupported operation value")


def _attribute_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _attribute(item) for key, item in value.items()}


def _is_transaction_cancelled(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    detail = response.get("Error")
    return isinstance(detail, dict) and detail.get("Code") == "TransactionCanceledException"


def _string_attribute(item: dict[str, object], name: str) -> str:
    raw = item.get(name)
    if not isinstance(raw, dict):
        raise ValueError(f"malformed {name}")
    value = raw.get("S")
    if not isinstance(value, str):
        raise ValueError(f"malformed {name}")
    return value


def _nullable_string_attribute(item: dict[str, object], name: str) -> str | None:
    raw = item.get(name)
    if raw == {"NULL": True}:
        return None
    return _string_attribute(item, name)


def _integer_attribute(item: dict[str, object], name: str) -> int:
    raw = item.get(name)
    if not isinstance(raw, dict):
        raise ValueError(f"malformed {name}")
    value = raw.get("N")
    if not isinstance(value, str):
        raise ValueError(f"malformed {name}")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"malformed {name}") from error
