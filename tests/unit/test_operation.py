from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from wishicraft.operation import (
    AdmissionConflict,
    LeaseLost,
    LeaseProof,
    LeaseRepository,
    OperationAdmissionRepository,
    OperationAdmissionService,
    OperationRepository,
    OperationRequest,
    OperationStatus,
    OperationType,
    RequestSource,
)


class TransactionCancelled(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "TransactionCanceledException"}}


class FakeDynamo:
    def __init__(self) -> None:
        self.item: object = None
        self.transactions: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.error: Exception | None = None

    def get_item(self, **kwargs: object) -> object:
        return {} if self.item is None else {"Item": self.item}

    def transact_write_items(self, **kwargs: object) -> object:
        if self.error is not None:
            raise self.error
        self.transactions.append(kwargs)
        return {}

    def update_item(self, **kwargs: object) -> object:
        self.updates.append(kwargs)
        return {}

    def delete_item(self, **kwargs: object) -> object:
        self.deletes.append(kwargs)
        return {}


def request(operation_type: OperationType = OperationType.START) -> OperationRequest:
    now = datetime(2026, 8, 29, 0, 0, tzinfo=UTC)
    return OperationRequest(
        operation_id="op-001",
        idempotency_key="request-001",
        operation_type=operation_type,
        target_game_id="game-vanilla-main",
        requested_by=RequestSource.CLI,
        requested_at=now,
        timeout_at=now + timedelta(minutes=30),
    )


def repository(api: FakeDynamo) -> OperationAdmissionRepository:
    return OperationAdmissionRepository(
        api,
        operations_table="operations",
        games_table="games",
        idempotency_table="idempotency",
        locks_table="locks",
        system_state_table="states",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
        lease_seconds=900,
        lease_id_factory=lambda: "lease-001",
    )


def transaction_items(api: FakeDynamo) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], api.transactions[0]["TransactItems"])


def test_competing_operation_admission_is_one_atomic_transaction() -> None:
    api = FakeDynamo()
    result = repository(api).admit(request())
    assert result.operation_id == "op-001"
    assert result.created is True
    assert result.lease_id == "lease-001"
    items = transaction_items(api)
    assert len(items) == 5
    idempotency_item = cast(dict[str, dict[str, object]], items[0]["Put"])["Item"]
    assert idempotency_item["expires_at"] == {"NULL": True}
    operation_item = cast(dict[str, dict[str, object]], items[1]["Put"])["Item"]
    assert operation_item["workflow_execution_name"] == {"NULL": True}
    assert operation_item["started_at"] == {"NULL": True}
    assert operation_item["completed_at"] == {"NULL": True}
    assert operation_item["expires_at"] == {"NULL": True}
    discord = cast(dict[str, dict[str, object]], operation_item["discord"])["M"]
    assert discord["guild_id"] == {"NULL": True}
    game = cast(dict[str, object], items[2]["ConditionCheck"])
    assert game["ConditionExpression"] == (
        "attribute_exists(game_id) AND lifecycle_state = :active"
    )
    lock = cast(dict[str, object], items[3]["Put"])
    assert lock["ConditionExpression"] == "attribute_not_exists(lock_name)"
    assert "expires" not in lock["ConditionExpression"]
    lock_item = cast(dict[str, dict[str, object]], lock["Item"])
    assert lock_item["owner_operation_id"] == {"S": "op-001"}
    assert lock_item["lease_id"] == {"S": "lease-001"}
    assert lock_item["lease_expires_at"] == {"N": "1787962500"}
    current = cast(dict[str, object], items[4]["Update"])
    assert current["ConditionExpression"] == (
        "attribute_exists(system_id) AND (attribute_not_exists(current_operation_id) OR "
        "attribute_type(current_operation_id, :null_type))"
    )


def test_status_admission_does_not_take_lock_or_current_operation() -> None:
    api = FakeDynamo()
    result = repository(api).admit(request(OperationType.STATUS))
    assert result.lease_id is None
    assert len(transaction_items(api)) == 3
    for item in transaction_items(api):
        put = item.get("Put")
        assert not isinstance(put, dict) or put.get("TableName") != "locks"
        assert "Update" not in item
    operation_item = cast(
        dict[str, dict[str, object]],
        cast(dict[str, object], transaction_items(api)[1]["Put"])["Item"],
    )
    assert operation_item["lock_name"] == {"NULL": True}
    assert operation_item["lease_id"] == {"NULL": True}


def test_same_idempotency_key_returns_existing_operation_without_write() -> None:
    api = FakeDynamo()
    api.item = idempotency_item("op-existing")
    result = repository(api).admit(request())
    assert result.operation_id == "op-existing"
    assert result.created is False
    assert api.transactions == []


def test_admission_service_uses_configured_game_timeout_and_generated_operation() -> None:
    api = FakeDynamo()
    service = OperationAdmissionService(
        repository(api),
        game_id="game-vanilla-main",
        timeout_seconds={OperationType.START: 1800},
        operation_id_factory=lambda: "op-service-001",
    )
    result = service.admit(
        operation_type=OperationType.START,
        idempotency_key="service-request",
        requested_by=RequestSource.ADMIN,
        requested_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert result.operation_id == "op-service-001"
    operation_put = cast(dict[str, object], transaction_items(api)[1]["Put"])
    item = cast(dict[str, dict[str, object]], operation_put["Item"])
    assert item["timeout_at"] == {"S": "2026-08-29T00:30:00.000000Z"}


def test_duplicate_service_request_does_not_generate_a_new_operation_id() -> None:
    api = FakeDynamo()
    api.item = idempotency_item("op-existing")
    generated = 0

    def generate() -> str:
        nonlocal generated
        generated += 1
        return "op-should-not-exist"

    service = OperationAdmissionService(
        repository(api),
        game_id="game-vanilla-main",
        timeout_seconds={OperationType.START: 1800},
        operation_id_factory=generate,
    )
    result = service.admit(
        operation_type=OperationType.START,
        idempotency_key="request-001",
        requested_by=RequestSource.CLI,
        requested_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert result.operation_id == "op-existing"
    assert generated == 0


def test_duplicate_discord_status_returns_same_operation_without_new_dispatch_source() -> None:
    api = FakeDynamo()
    api.item = idempotency_item(
        "op-status-existing",
        operation_type=OperationType.STATUS,
        source=RequestSource.DISCORD,
    )
    service = OperationAdmissionService(
        repository(api),
        game_id="game-vanilla-main",
        timeout_seconds={OperationType.STATUS: 120},
        operation_id_factory=lambda: "op-must-not-be-created",
    )
    result = service.admit(
        operation_type=OperationType.STATUS,
        idempotency_key="discord:1532000000000000001",
        requested_by=RequestSource.DISCORD,
        requested_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert result == type(result)("op-status-existing", False, None)
    assert api.transactions == []


def test_idempotency_key_reuse_with_different_payload_is_rejected() -> None:
    api = FakeDynamo()
    api.item = idempotency_item("op-existing")
    with pytest.raises(AdmissionConflict, match="payload conflict"):
        repository(api).admit(request(OperationType.STOP))


def test_transaction_conflict_does_not_create_operation_or_take_expired_lock() -> None:
    api = FakeDynamo()
    api.error = TransactionCancelled()
    with pytest.raises(AdmissionConflict):
        repository(api).admit(request())
    assert api.transactions == []


def test_duplicate_race_returns_winning_operation() -> None:
    class RacingDynamo(FakeDynamo):
        reads = 0

        def get_item(self, **kwargs: object) -> object:
            self.reads += 1
            if self.reads == 1:
                return {}
            return {"Item": idempotency_item("op-winner")}

    api = RacingDynamo()
    api.error = TransactionCancelled()
    result = repository(api).admit(request())
    assert result == type(result)("op-winner", False, None)


def test_non_transaction_aws_failure_is_not_mislabeled_as_conflict() -> None:
    api = FakeDynamo()
    api.error = RuntimeError("network unavailable")
    with pytest.raises(RuntimeError, match="network unavailable"):
        repository(api).admit(request())


def test_renew_requires_operation_lease_and_unexpired_conditions() -> None:
    api = FakeDynamo()
    locks = LeaseRepository(api, table_name="locks", lock_name="minecraft-control")
    now = datetime(2026, 8, 29, tzinfo=UTC)
    proof = LeaseProof("wishicraft-main", "op-001", "lease-001", int(now.timestamp()) + 1)
    renewed = locks.renew(proof, now=now, lease_seconds=900)
    assert renewed.lease_id == proof.lease_id
    request_value = api.updates[0]
    assert request_value["ConditionExpression"] == (
        "resource_id = :resource_id AND owner_operation_id = :operation_id "
        "AND lease_id = :lease_id AND lease_expires_at >= :now"
    )


def test_side_effect_ownership_check_requires_resource_operation_lease_and_freshness() -> None:
    api = FakeDynamo()
    now = datetime(2026, 8, 29, tzinfo=UTC)
    proof = LeaseProof("wishicraft-main", "op-001", "lease-001", int(now.timestamp()) + 1)
    api.item = {
        "resource_id": {"S": "wishicraft-main"},
        "owner_operation_id": {"S": "op-001"},
        "lease_id": {"S": "lease-001"},
        "lease_expires_at": {"N": str(int(now.timestamp()))},
    }
    locks = LeaseRepository(api, table_name="locks", lock_name="minecraft-control")
    locks.verify_owned(proof, now=now)
    api.item = {**cast(dict[str, object], api.item), "lease_id": {"S": "lease-new"}}
    with pytest.raises(LeaseLost, match="LOCK_LOST"):
        locks.verify_owned(proof, now=now)


def test_release_cannot_delete_another_or_expired_lease() -> None:
    api = FakeDynamo()
    locks = LeaseRepository(api, table_name="locks", lock_name="minecraft-control")
    now = datetime(2026, 8, 29, tzinfo=UTC)
    locks.release(
        LeaseProof("wishicraft-main", "op-001", "lease-001", int(now.timestamp()) + 1),
        now=now,
    )
    condition = cast(str, api.deletes[0]["ConditionExpression"])
    assert "resource_id = :resource_id" in condition
    assert "owner_operation_id = :operation_id" in condition
    assert "lease_id = :lease_id" in condition
    assert "lease_expires_at >= :now" in condition


def test_operation_contract_rejects_invalid_or_non_utc_inputs() -> None:
    with pytest.raises(ValueError, match="operation identity"):
        OperationRequest(**{**request().__dict__, "operation_id": "contains space"})
    with pytest.raises(ValueError, match="timezone-aware"):
        OperationRequest(**{**request().__dict__, "requested_at": datetime(2026, 8, 29)})


def operation_repository(api: FakeDynamo) -> OperationRepository:
    return OperationRepository(
        api,
        operations_table="operations",
        locks_table="locks",
        system_state_table="states",
        system_id="wishicraft-main",
        lock_name="minecraft-control",
    )


def test_step_update_only_accepts_non_terminal_operation() -> None:
    api = FakeDynamo()
    operation_repository(api).update_step(
        operation_id="op-001",
        current_step="WAITING_FOR_SSM",
        status=OperationStatus.RUNNING,
        updated_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert "#status IN (:pending, :running)" in cast(str, api.updates[0]["ConditionExpression"])
    with pytest.raises(ValueError, match="non-terminal"):
        operation_repository(api).update_step(
            operation_id="op-001",
            current_step="DONE",
            status=OperationStatus.SUCCEEDED,
            updated_at=datetime(2026, 8, 29, tzinfo=UTC),
        )


def test_normal_completion_releases_only_current_unexpired_lease_and_operation() -> None:
    api = FakeDynamo()
    now = datetime(2026, 8, 29, tzinfo=UTC)
    proof = LeaseProof("wishicraft-main", "op-001", "lease-001", int(now.timestamp()) + 10)
    operation_repository(api).complete_owned(
        proof=proof,
        status=OperationStatus.SUCCEEDED,
        completed_at=now,
    )
    items = transaction_items(api)
    assert len(items) == 3
    lock_delete = cast(dict[str, object], items[1]["Delete"])
    assert "lease_expires_at >= :now" in cast(str, lock_delete["ConditionExpression"])
    current_update = cast(dict[str, object], items[2]["Update"])
    assert current_update["ConditionExpression"] == "current_operation_id = :operation_id"


def test_status_completion_requires_an_unlocked_status_operation() -> None:
    api = FakeDynamo()
    operation_repository(api).complete_unlocked(
        operation_id="op-status-001",
        status=OperationStatus.SUCCEEDED,
        completed_at=datetime(2026, 8, 29, tzinfo=UTC),
        result={"status": "stopped", "ready": False},
    )
    update = api.updates[0]
    condition = cast(str, update["ConditionExpression"])
    assert "operation_type = :status_operation" in condition
    assert "attribute_type(lock_name, :null_type)" in condition
    assert "#status IN (:pending, :running)" in condition
    assert update["ExpressionAttributeNames"] == {
        "#status": "status",
        "#error": "error",
        "#result": "result",
    }
    values = cast(dict[str, object], update["ExpressionAttributeValues"])
    assert values[":result"] == {"M": {"status": {"S": "stopped"}, "ready": {"BOOL": False}}}
    with pytest.raises(ValueError, match="normal completion"):
        operation_repository(FakeDynamo()).complete_unlocked(
            operation_id="op-status-001",
            status=OperationStatus.TIMED_OUT,
            completed_at=datetime(2026, 8, 29, tzinfo=UTC),
        )


def test_status_state_read_requires_status_without_lock() -> None:
    api = FakeDynamo()
    api.item = {
        "operation_type": {"S": "STATUS"},
        "status": {"S": "RUNNING"},
        "lock_name": {"NULL": True},
    }
    assert (
        operation_repository(api).unlocked_status_state("op-status-001") is OperationStatus.RUNNING
    )
    assert isinstance(api.item, dict)
    api.item = {**api.item, "lock_name": {"S": "minecraft-control"}}
    with pytest.raises(ValueError, match="must not have a lock"):
        operation_repository(api).unlocked_status_state("op-status-001")


def test_stale_recovery_requires_fresh_observation_and_exact_lease_cleanup() -> None:
    api = FakeDynamo()
    timeout = datetime(2026, 8, 29, tzinfo=UTC)
    reconciled = timeout + timedelta(seconds=1)
    proof = LeaseProof("wishicraft-main", "op-001", "lease-001", int(timeout.timestamp()) - 1)
    operation_repository(api).recover_stale(
        proof=proof,
        timeout_at=timeout,
        reconciled_at=reconciled,
        status=OperationStatus.TIMED_OUT,
        error_code="RECOVERY_RECONCILED_TIMED_OUT",
    )
    items = transaction_items(api)
    operation_update = cast(dict[str, object], items[0]["Update"])
    assert "timeout_at = :timeout_at" in cast(str, operation_update["ConditionExpression"])
    lock_delete = cast(dict[str, object], items[1]["Delete"])
    assert lock_delete["ConditionExpression"] == (
        "resource_id = :resource_id AND owner_operation_id = :operation_id AND lease_id = :lease_id"
    )
    current_update = cast(dict[str, object], items[2]["Update"])
    assert "observed_at = :reconciled_at" in cast(str, current_update["ConditionExpression"])
    with pytest.raises(ValueError, match="after operation deadline"):
        operation_repository(FakeDynamo()).recover_stale(
            proof=proof,
            timeout_at=timeout,
            reconciled_at=timeout,
            status=OperationStatus.FAILED,
            error_code="OBSERVED_FAILURE",
        )


def idempotency_item(
    operation_id: str,
    *,
    operation_type: OperationType = OperationType.START,
    source: RequestSource = RequestSource.CLI,
) -> dict[str, object]:
    return {
        "operation_id": {"S": operation_id},
        "operation_type": {"S": operation_type.value},
        "source": {"S": source.value},
        "target_game_id": {"S": "game-vanilla-main"},
    }
