from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

from tests.unit.test_daily_backup_domain import NOW, VOLUME, protected, state, view
from wishicraft import daily_backup as d
from wishicraft import daily_backup_lambda as task
from wishicraft.admission_lambda import _parse_event
from wishicraft.maintenance_repository import encode
from wishicraft.operation import (
    AdmissionConflict,
    LeaseProof,
    OperationAdmissionRepository,
    OperationRepository,
    OperationRequest,
    OperationStatus,
    OperationType,
    RequestSource,
)
from wishicraft.system_state import utc_timestamp


class Store:
    def __init__(self) -> None:
        self.state = state()
        self.operations: dict[str, dict[str, Any]] = {}
        self.transactions: list[Any] = []
        self.updates: list[Any] = []
        self.metrics: list[Any] = []
        self.invocations: list[Any] = []
        self.lock: dict[str, Any] = {}
        self.invoke_error = False

    def get_item(self, **kw: Any) -> dict[str, Any]:
        table = kw["TableName"]
        item = (
            self.state
            if table == "states"
            else self.lock
            if table == "locks"
            else self.operations.get(kw["Key"].get("operation_id", {}).get("S", ""), {})
        )
        return {"Item": encode(item)} if item else {}

    def transact_write_items(self, **kw: Any) -> dict[str, Any]:
        self.transactions.append(kw["TransactItems"])
        return {}

    def update_item(self, **kw: Any) -> dict[str, Any]:
        self.updates.append(kw)
        self.state["backup_protection"] = TypeDeserializer().deserialize(
            kw["ExpressionAttributeValues"][":bp"]
        )
        return {}

    def delete_item(self, **kw: Any) -> dict[str, Any]:
        raise AssertionError("not expected")

    def describe_instances(self, **kw: Any) -> dict[str, Any]:
        return {
            "Reservations": [
                {"Instances": [{"InstanceId": "i-test", "State": {"Name": "stopped"}}]}
            ]
        }

    def put_metric_data(self, **kw: Any) -> None:
        self.metrics.append(kw)

    def invoke(self, **kw: Any) -> dict[str, Any]:
        self.invocations.append(kw)
        if self.invoke_error:
            return {"FunctionError": "Unhandled"}
        return {"Payload": json.dumps({"outcome": "CONFLICT"}).encode()}


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in dict(
        PROTECTION_VOLUME_ID=VOLUME,
        SYSTEM_ID="system",
        SYSTEM_STATE_TABLE="states",
        LOCKS_TABLE="locks",
        OPERATIONS_TABLE="operations",
        GLOBAL_LOCK_NAME="lock",
        DAILY_BACKUP_ENABLED="1",
        DAILY_BACKUP_ADMISSION_FUNCTION="internal",
        STAGE="dev",
    ).items():
        monkeypatch.setenv(key, value)


def repo(api: Store) -> OperationAdmissionRepository:
    return OperationAdmissionRepository(
        api,
        operations_table="operations",
        games_table="games",
        idempotency_table="idempotency",
        locks_table="locks",
        system_state_table="states",
        system_id="system",
        lock_name="lock",
        lease_seconds=900,
        lease_id_factory=lambda: "lease-test",
    )


def request(kind: str, *, daily: int | None = None, game: str = "game-a") -> OperationRequest:
    return OperationRequest(
        "op-test",
        "daily-test",
        OperationType(kind),
        game,
        RequestSource.SCHEDULE if daily else RequestSource.ADMIN,
        NOW,
        NOW + timedelta(minutes=15),
        daily_boundary=daily,
    )


@pytest.mark.parametrize("kind", ["START", "SWITCH", "RESET"])
@pytest.mark.parametrize(
    "game", ["game-vanilla-main", "game-paper", "game-neoforge", "game-disposable"]
)
def test_mutation_admission_marks_possible_change_atomically(
    environment: None, kind: str, game: str
) -> None:
    api = Store()
    repo(api).admit(request(kind, game=game))
    writes = api.transactions[0]
    update = next(w["Update"] for w in writes if "Update" in w)
    assert "backup_protection = :bp_old" in update["ConditionExpression"]
    p = TypeDeserializer().deserialize(update["ExpressionAttributeValues"][":bp"])
    assert p["boundary"] == 2 and p["stopped_at"] is None
    assert len(writes) == 5  # existing admission transaction, no workflow/snapshot wait


def test_daily_admission_captures_boundary_with_lock_and_intent(environment: None) -> None:
    api = Store()
    repo(api).admit(request("BACKUP", daily=1))
    writes = api.transactions[0]
    p = TypeDeserializer().deserialize(writes[-1]["Update"]["ExpressionAttributeValues"][":bp"])
    assert p["intent"]["operation_id"] == "op-test" and p["intent"]["boundary"] == 1
    assert p["attempts"] == 1
    assert writes[1]["Put"]["Item"]["backup_boundary"] == {"N": "1"}
    condition = writes[-1]["Update"]["ConditionExpression"]
    assert (
        "maintenance" in condition and "desired_state" in condition and "observed_at" in condition
    )


def test_stale_evaluator_does_not_admit_new_boundary(environment: None) -> None:
    api = Store()
    api.state["backup_protection"] = d.dirty(api.state["backup_protection"], NOW)
    with pytest.raises(AdmissionConflict):
        repo(api).admit(request("BACKUP", daily=1))
    assert not api.transactions


@pytest.mark.parametrize("status", ["ADMITTED", "UNKNOWN"])
def test_unresolved_intent_survives_operation_ttl_and_selection_change(
    environment: None, status: str
) -> None:
    api = Store()
    api.state["backup_protection"]["intent"] = dict(operation_id="op-gone", status=status)
    api.state["desired_game_id"] = "game-b"
    with pytest.raises(AdmissionConflict):
        repo(api).admit(request("BACKUP", daily=1, game="game-b"))
    p = task.reconcile_intent(api, api.state["backup_protection"], NOW)
    assert p["intent"]["operation_id"] == "op-gone" and p["intent"]["status"] == "UNKNOWN"


def test_completed_backup_atomic_protection_and_provenance(environment: None) -> None:
    api = Store()
    api.state["backup_protection"]["intent"] = dict(
        operation_id="op-test", boundary=1, status="ADMITTED"
    )
    operations = OperationRepository(
        api,
        operations_table="operations",
        locks_table="locks",
        system_state_table="states",
        system_id="system",
        lock_name="lock",
    )
    proof = LeaseProof("system", "op-test", "lease-test", 0)
    pair: tuple[dict[str, object], ...] = (
        {"Put": {"TableName": "backups", "evidence": "snapshot"}},
        {"Put": {"TableName": "backups", "evidence": "operation"}},
    )
    operations.complete_owned(
        proof=proof,
        status=OperationStatus.SUCCEEDED,
        completed_at=NOW,
        result={"kind": "BACKUP", "snapshot_id": "snap-test"},
        additional_writes=pair,
        backup_acquired_at=utc_timestamp(NOW - timedelta(seconds=10)),
    )
    writes = api.transactions[0]
    assert writes[1:3] == list(pair)
    p = TypeDeserializer().deserialize(writes[-1]["Update"]["ExpressionAttributeValues"][":bp"])
    assert p["protected_boundary"] == 1 and p["intent"]["status"] == "SUCCEEDED"
    assert p["last_success"]["snapshot_id"] == "snap-test"
    assert "current_operation_id = :operation_id" in writes[-1]["Update"]["ConditionExpression"]


def test_evaluator_invokes_only_internal_admission_and_reports_conflict(environment: None) -> None:
    api = Store()
    result = task.evaluate(api, api, api, api, now=NOW)
    assert result["admission"]["outcome"] == "CONFLICT"
    assert api.invocations[0]["FunctionName"] == "internal"
    assert json.loads(api.invocations[0]["Payload"]) == {"schema_version": 1, "boundary": 1}
    assert api.metrics and not api.transactions


def test_response_loss_emits_no_healthy_heartbeat(environment: None) -> None:
    api = Store()
    api.invoke_error = True
    with pytest.raises(RuntimeError):
        task.evaluate(api, api, api, api, now=NOW)
    assert not api.metrics


def test_observation_failure_does_not_emit_healthy_heartbeat(environment: None) -> None:
    api = Store()
    api.state = {}
    with pytest.raises(ValueError):
        task.evaluate(api, api, api, api, now=NOW)
    assert not api.metrics


def test_disabled_handler_never_accepts_new_backup(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DAILY_BACKUP_ENABLED")
    assert task.admit({"schema_version": 1, "boundary": 1}, None) == {"outcome": "DISABLED"}


def test_public_schedule_field_does_not_authorize_backup() -> None:
    with pytest.raises(ValueError):
        _parse_event(
            dict(
                schema_version=1,
                operation="admit",
                operation_type="BACKUP",
                idempotency_key="fake",
                requested_by="SCHEDULE",
            )
        )


@pytest.mark.parametrize(
    "attempts,elapsed,allowed",
    [(1, 899, False), (1, 900, True), (2, 3599, False), (2, 3600, True), (3, 86400, False)],
)
def test_bounded_retry_backoff(
    environment: None, attempts: int, elapsed: int, allowed: bool
) -> None:
    api = Store()
    p = api.state["backup_protection"]
    p["attempts"] = attempts
    p["intent"] = dict(
        status="FAILED",
        safe_retry=True,
        operation_id="op-old",
        finished_at=utc_timestamp(NOW - timedelta(seconds=elapsed)),
    )
    if allowed:
        repo(api).admit(request("BACKUP", daily=1))
        assert len(api.transactions) == 1
    else:
        with pytest.raises(AdmissionConflict):
            repo(api).admit(request("BACKUP", daily=1))
        assert not api.transactions


def test_import_restore_maintenance_unknown_requires_new_baseline() -> None:
    p = d.dirty(protected(), NOW, unknown=True)
    assert p["unknown_since"] and p["boundary"] > p["protected_boundary"]


def test_status_is_a_read_only_projection() -> None:
    s = state()
    before = deepcopy(s)
    for i in range(5):
        view(s["backup_protection"], state=s, now=NOW + timedelta(minutes=i))
    assert s == before


@pytest.mark.parametrize("source", [RequestSource.ADMIN, RequestSource.SCHEDULE])
def test_normal_and_idle_stop_record_waiting_in_terminal_transaction(
    environment: None, source: RequestSource
) -> None:
    api = Store()
    api.state["backup_protection"] = d.dirty(protected(), NOW)
    operations = OperationRepository(
        api,
        operations_table="operations",
        locks_table="locks",
        system_state_table="states",
        system_id="system",
        lock_name="lock",
    )
    api.operations["op-stop"] = {"operation_type": "STOP", "requested_by": {"source": source.value}}
    operations.complete_owned(
        proof=LeaseProof("system", "op-stop", "lease", 0),
        status=OperationStatus.SUCCEEDED,
        completed_at=NOW,
        normal_stop=True,
    )
    writes = api.transactions[0]
    p = TypeDeserializer().deserialize(writes[-1]["Update"]["ExpressionAttributeValues"][":bp"])
    assert p["stopped_at"] == utc_timestamp(NOW) and p["protected_boundary"] == 1


@pytest.mark.parametrize(
    "error,reserved,snapshot,expected,safe",
    [
        ("WORKFLOW_START_FAILED", False, False, "FAILED", True),
        ("BACKUP_PRECONDITION_FAILED", False, False, "FAILED", True),
        ("BACKUP_SNAPSHOT_CREATE_FAILED", True, False, "FAILED", True),
        ("BACKUP_SNAPSHOT_CREATE_OUTCOME_UNKNOWN", True, False, "UNKNOWN", False),
        ("BACKUP_SNAPSHOT_FAILED", True, True, "FAILED", False),
        ("BACKUP_PROVENANCE_OUTCOME_UNKNOWN", True, True, "UNKNOWN", False),
        ("BACKUP_SNAPSHOT_TIMEOUT", True, True, "UNKNOWN", False),
        ("LOCK_LOST", False, False, "UNKNOWN", False),
    ],
)
def test_failure_classification_never_duplicates_possible_snapshot(
    environment: None, error: str, reserved: bool, snapshot: bool, expected: str, safe: bool
) -> None:
    api = Store()
    api.state["backup_protection"]["intent"] = dict(
        operation_id="op-test", boundary=1, status="ADMITTED"
    )
    api.operations["op-test"] = {
        **({"backup_create_intent": {"tag": "value"}} if reserved else {}),
        **({"backup_snapshot_id": "snap-test"} if snapshot else {}),
    }
    operations = OperationRepository(
        api,
        operations_table="operations",
        locks_table="locks",
        system_state_table="states",
        system_id="system",
        lock_name="lock",
    )
    operations.complete_owned(
        proof=LeaseProof("system", "op-test", "lease", 0),
        status=OperationStatus.FAILED,
        completed_at=NOW,
        error_code=error,
    )
    p = TypeDeserializer().deserialize(
        api.transactions[0][-1]["Update"]["ExpressionAttributeValues"][":bp"]
    )
    assert p["intent"]["status"] == expected and p["intent"]["safe_retry"] is safe
    assert p["protected_boundary"] == 0


class ApplyingStore(Store):
    """Transactional fixture enforces the contested authority/lock conditions before publication."""

    def __init__(self) -> None:
        super().__init__()
        self.idempotency: dict[str, dict[str, Any]] = {}

    def get_item(self, **kw: Any) -> dict[str, Any]:
        if kw["TableName"] == "idempotency":
            item = self.idempotency.get(kw["Key"]["idempotency_key"]["S"])
            return {"Item": encode(item)} if item else {}
        return super().get_item(**kw)

    def transact_write_items(self, **kw: Any) -> dict[str, Any]:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        writes = kw["TransactItems"]
        update = next(w["Update"] for w in writes if "Update" in w)
        values = update["ExpressionAttributeValues"]
        if (
            self.lock
            or self.state.get("current_operation_id")
            or values.get(":bp_old") != encode({"p": self.state["backup_protection"]})["p"]
            or (self.state.get("maintenance") or {}).get("status", "ENDED") != "ENDED"
        ):
            raise ClientError(
                {"Error": {"Code": "TransactionCanceledException"}}, "TransactWriteItems"
            )
        decoder = TypeDeserializer()
        for w in writes:
            if "Put" not in w:
                continue
            put = w["Put"]
            item = {k: decoder.deserialize(v) for k, v in put["Item"].items()}
            if put["TableName"] == "operations":
                self.operations[item["operation_id"]] = item
            elif put["TableName"] == "idempotency":
                self.idempotency[item["idempotency_key"]] = item
            elif put["TableName"] == "locks":
                self.lock = item
        self.state["backup_protection"] = decoder.deserialize(values[":bp"])
        self.state["current_operation_id"] = decoder.deserialize(values[":operation_id"])
        self.transactions.append(writes)
        return {}


def test_real_internal_handler_duplicate_and_response_loss_reuses_durable_intent(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wishicraft import admission_lambda as admission
    from wishicraft.operation import OperationAdmissionService
    from wishicraft.runtime_catalog import RuntimeCatalog

    api = ApplyingStore()
    service = OperationAdmissionService(
        repo(api),
        game_id="game-a",
        timeout_seconds={OperationType.BACKUP: 900},
        operation_id_factory=lambda: "op-test",
    )
    monkeypatch.setattr(admission, "_get_service", lambda: service)
    monkeypatch.setattr(
        "wishicraft.runtime_catalog.configured_catalog",
        lambda: RuntimeCatalog(("game-a", "game-b")),
    )

    class Clock:
        fromisoformat = staticmethod(datetime.fromisoformat)

        @staticmethod
        def now(zone: object) -> datetime:
            return NOW

    monkeypatch.setattr(task, "datetime", Clock)

    class Sdk:
        def client(self, name: str) -> Store:
            return api

    monkeypatch.setattr(task, "clients", Sdk)

    class Launcher:
        calls = 0

        def start(self, **kwargs: Any) -> None:
            self.calls += 1
            raise TimeoutError("lost workflow-start response")

    launcher = Launcher()
    monkeypatch.setattr(admission, "_get_backup_launcher", lambda: launcher)
    event = {"schema_version": 1, "boundary": 1}
    with pytest.raises(TimeoutError):
        task.admit(event, None)
    api.idempotency.clear()  # No finite request record may create a second BACKUP.
    api.state["desired_game_id"] = "game-b"
    assert task.admit(event, None) == {"outcome": "EXISTING", "operation_id": "op-test"}
    assert len(api.transactions) == 1 and launcher.calls == 1
    result = task.evaluate(api, api, api, api, now=NOW)
    assert result["reason"] == "BACKUP_RUNNING" and not api.invocations


def test_atomic_concurrent_evaluators_cannot_multiply_intent(environment: None) -> None:
    api = ApplyingStore()
    first = repo(api).admit(request("BACKUP", daily=1))
    again = repo(api).admit(request("BACKUP", daily=1))
    assert first.created and not again.created and len(api.transactions) == 1


def test_start_wins_transaction_race_before_daily_backup(environment: None) -> None:
    api = ApplyingStore()
    original = api.transact_write_items

    def raced(**kw: Any) -> dict[str, Any]:
        api.state["backup_protection"] = d.dirty(api.state["backup_protection"], NOW)
        api.state["current_operation_id"] = "op-start"
        return original(**kw)

    api.transact_write_items = raced  # type: ignore[method-assign]
    with pytest.raises(AdmissionConflict):
        repo(api).admit(request("BACKUP", daily=1))
    assert not api.transactions and not api.operations
