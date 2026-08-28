from __future__ import annotations

from datetime import datetime

import pytest

from wishicraft import admission_lambda
from wishicraft.operation import AdmissionResult, OperationType, RequestSource


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
    ) -> AdmissionResult:
        self.calls.append(
            {
                "operation_type": operation_type,
                "idempotency_key": idempotency_key,
                "requested_by": requested_by,
                "requested_at": requested_at,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


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
    monkeypatch.setattr(admission_lambda, "_service", service)
    assert admission_lambda.handler(event(), None) == {
        "schema_version": 1,
        "operation_id": "op-001",
        "created": True,
        "lease_id": "lease-001",
    }
    assert service.calls[0]["operation_type"] is OperationType.START


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
