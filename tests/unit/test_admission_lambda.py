from __future__ import annotations

from datetime import datetime

import pytest

from wishicraft import admission_lambda
from wishicraft.operation import (
    AdmissionResult,
    DiscordOperationContext,
    OperationType,
    RequestSource,
)


class Service:
    def __init__(self, result: AdmissionResult | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def admit(
        self,
        *,
        operation_type: OperationType,
        idempotency_key: str,
        requested_by: RequestSource,
        requested_at: datetime,
        discord: DiscordOperationContext | None = None,
    ) -> AdmissionResult:
        self.calls.append(
            {
                "operation_type": operation_type,
                "idempotency_key": idempotency_key,
                "requested_by": requested_by,
                "requested_at": requested_at,
                "discord": discord,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Launcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start(
        self,
        *,
        operation_id: str,
        lease_id: str,
        started_at: datetime,
        **metadata: object,
    ) -> None:
        self.calls.append(
            {
                "operation_id": operation_id,
                "lease_id": lease_id,
                "started_at": started_at,
                **metadata,
            }
        )


def event() -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": "admit",
        "operation_type": "START",
        "idempotency_key": "cli-request-001",
        "requested_by": "CLI",
    }


def test_valid_admission_invocation_uses_domain_service(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Service(AdmissionResult("op-001", True, "lease-001"))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_launcher", launcher)
    assert admission_lambda.handler(event(), None) == {
        "schema_version": 1,
        "operation_id": "op-001",
        "created": True,
        "lease_id": "lease-001",
    }
    assert service.calls[0]["operation_type"] is OperationType.START
    assert launcher.calls[0]["operation_id"] == "op-001"


def test_stop_admission_launches_stop_workflow_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Service(AdmissionResult("op-stop", True, "lease-stop"))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_stop_launcher", launcher)
    stop_event = {**event(), "operation_type": "STOP", "idempotency_key": "stop-001"}
    result = admission_lambda.handler(stop_event, None)
    assert result["operation_id"] == "op-stop"
    assert service.calls[0]["operation_type"] is OperationType.STOP
    assert launcher.calls[0]["lease_id"] == "lease-stop"


def test_scheduled_stop_requires_and_forwards_auto_stop_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-auto-stop", True, "lease-auto-stop"))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_stop_launcher", launcher)
    scheduled = {
        **event(),
        "operation_type": "STOP",
        "requested_by": "SCHEDULE",
        "idempotency_key": "auto-stop:asi-example",
        "auto_stop_intent_id": "asi-example",
    }
    assert admission_lambda.handler(scheduled, None)["operation_id"] == "op-auto-stop"
    assert service.calls[0]["requested_by"] is RequestSource.SCHEDULE
    assert launcher.calls[0]["auto_stop_intent_id"] == "asi-example"

    scheduled.pop("auto_stop_intent_id")
    with pytest.raises(ValueError, match="invalid Operation admission"):
        admission_lambda.handler(scheduled, None)


def test_duplicate_stop_admission_does_not_launch_new_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-stop", False, None))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_stop_launcher", launcher)
    stop_event = {**event(), "operation_type": "STOP", "idempotency_key": "stop-001"}
    assert admission_lambda.handler(stop_event, None)["created"] is False
    assert launcher.calls == []


def test_backup_admission_launches_backup_workflow_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service = Service(AdmissionResult("op-backup", True, "lease-backup"))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_backup_launcher", launcher)
    monkeypatch.setenv("BACKUP_STATE_MACHINE_ARN", "arn:backup")
    backup_event = {**event(), "operation_type": "BACKUP", "idempotency_key": "backup-001"}
    result = admission_lambda.handler(backup_event, None)
    assert result["operation_id"] == "op-backup"
    assert service.calls[0]["operation_type"] is OperationType.BACKUP
    assert launcher.calls[0]["lease_id"] == "lease-backup"


def test_duplicate_backup_admission_does_not_launch_or_create_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-backup", False, None))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_backup_launcher", launcher)
    monkeypatch.setenv("BACKUP_STATE_MACHINE_ARN", "arn:backup")
    backup_event = {**event(), "operation_type": "BACKUP", "idempotency_key": "backup-001"}
    assert admission_lambda.handler(backup_event, None)["created"] is False
    assert launcher.calls == []


def test_backup_is_rejected_before_admission_when_phase_eight_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-backup", True, "lease-backup"))
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.delenv("BACKUP_STATE_MACHINE_ARN", raising=False)
    backup_event = {**event(), "operation_type": "BACKUP", "idempotency_key": "backup-001"}
    with pytest.raises(ValueError, match="not configured"):
        admission_lambda.handler(backup_event, None)
    assert service.calls == []


def test_retention_admission_launches_dry_run_workflow_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-retention", True, "lease-retention"))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_retention_launcher", launcher)
    monkeypatch.setenv("RETENTION_STATE_MACHINE_ARN", "arn:retention")
    retention_event = {
        **event(),
        "operation_type": "RETENTION",
        "idempotency_key": "retention:request-001",
        "requested_by": "ADMIN",
    }
    result = admission_lambda.handler(retention_event, None)
    assert result["operation_id"] == "op-retention"
    assert service.calls[0]["operation_type"] is OperationType.RETENTION
    assert launcher.calls == [
        {
            "operation_id": "op-retention",
            "lease_id": "lease-retention",
            "started_at": launcher.calls[0]["started_at"],
        }
    ]


def test_duplicate_retention_admission_does_not_launch_new_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-retention", False, None))
    launcher = Launcher()
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.setattr(admission_lambda, "_retention_launcher", launcher)
    monkeypatch.setenv("RETENTION_STATE_MACHINE_ARN", "arn:retention")
    retention_event = {
        **event(),
        "operation_type": "RETENTION",
        "idempotency_key": "retention:request-001",
        "requested_by": "ADMIN",
    }
    assert admission_lambda.handler(retention_event, None)["created"] is False
    assert launcher.calls == []


def test_retention_is_rejected_before_admission_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Service(AdmissionResult("op-retention", True, "lease-retention"))
    monkeypatch.setattr(admission_lambda, "_service", service)
    monkeypatch.delenv("RETENTION_STATE_MACHINE_ARN", raising=False)
    retention_event = {
        **event(),
        "operation_type": "RETENTION",
        "idempotency_key": "retention:request-001",
        "requested_by": "ADMIN",
    }
    with pytest.raises(ValueError, match="not configured"):
        admission_lambda.handler(retention_event, None)
    assert service.calls == []


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {**event(), "schema_version": 2},
        {**event(), "operation": "reconcile"},
        {**event(), "operation_type": "DELETE_WORLD"},
        {**event(), "requested_by": "ANONYMOUS"},
        {**event(), "target_game_id": "game-other"},
    ],
)
def test_invalid_or_extensible_input_is_rejected(invalid: object) -> None:
    with pytest.raises(ValueError, match="invalid Operation admission invocation"):
        admission_lambda.handler(invalid, None)


def test_domain_or_repository_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(admission_lambda, "_service", Service(RuntimeError("write failed")))
    with pytest.raises(RuntimeError, match="write failed"):
        admission_lambda.handler(event(), None)
