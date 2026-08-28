from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from wishicraft import reconcile_lambda
from wishicraft.system_state import DesiredState, Health, SystemState


def persisted_state() -> SystemState:
    return SystemState(
        system_id="wishicraft-main",
        environment="dev",
        game_id="game-vanilla-main",
        desired_state=DesiredState.STOPPED,
        target_instance_id=None,
        observation={"ec2_state": "stopped", "runtime_ready": False},
        discrepancies=(),
        health=Health.HEALTHY,
        observation_errors=(),
        observed_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


class Service:
    def __init__(self, result: SystemState | Exception) -> None:
        self.result = result

    def reconcile(self, *, observed_at: datetime) -> SystemState:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_valid_versioned_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconcile_lambda, "_service", Service(persisted_state()))
    result = reconcile_lambda.handler({"schema_version": 1, "operation": "reconcile"}, None)
    assert result["schema_version"] == 1
    assert cast(dict[str, object], result["observation"])["runtime_ready"] is False


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"schema_version": 2, "operation": "reconcile"},
        {"schema_version": 1, "operation": "other"},
    ],
)
def test_invalid_invocation_is_rejected(event: object) -> None:
    with pytest.raises(ValueError, match="invalid Reconcile invocation"):
        reconcile_lambda.handler(event, None)


def test_domain_failure_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconcile_lambda, "_service", Service(RuntimeError("domain failed")))
    with pytest.raises(RuntimeError, match="domain failed"):
        reconcile_lambda.handler({"schema_version": 1, "operation": "reconcile"}, None)


def test_repository_failure_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconcile_lambda, "_service", Service(RuntimeError("write failed")))
    with pytest.raises(RuntimeError, match="write failed"):
        reconcile_lambda.handler({"schema_version": 1, "operation": "reconcile"}, None)
