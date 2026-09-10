from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from tests.unit.test_monitoring_telemetry import Aws, inputs
from tests.unit.test_reconcile_lambda import persisted_state
from wishicraft import reconcile_lambda
from wishicraft.system_state import SystemStateRepository


def prepare(monkeypatch: pytest.MonkeyPatch) -> tuple[Aws, list[dict[str, Any]]]:
    aws = Aws(inputs())
    monkeypatch.setattr(importlib.import_module("boto3"), "client", aws.client)
    for name, value in {
        "SYSTEM_STATE_TABLE": "state",
        "LOCKS_TABLE": "lock",
        "SYSTEM_ID": "wishicraft-main",
        "GLOBAL_LOCK_NAME": "minecraft-control",
    }.items():
        monkeypatch.setenv(name, value)
    writes: list[dict[str, Any]] = []
    repository = SimpleNamespace(save=lambda *args, **kwargs: writes.append(kwargs))

    def reconcile(**kwargs: Any) -> object:
        assert kwargs["persist"] is False
        return persisted_state()

    monkeypatch.setattr(
        reconcile_lambda, "_service", SimpleNamespace(repository=repository, reconcile=reconcile)
    )
    return aws, writes


def test_scheduled_handler_observes_then_saves_with_revision_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, writes = prepare(monkeypatch)
    result = reconcile_lambda.handler(
        {"schema_version": 1, "operation": "scheduled_reconcile"}, None
    )
    assert result["result"] == "observed"
    assert writes == [{"expected_desired_revision": 42}]


@pytest.mark.parametrize("lock,current", [({"lease_expires_at": 0}, None), ({}, "op-active")])
def test_any_lock_or_current_operation_skips_without_ssm(
    monkeypatch: pytest.MonkeyPatch, lock: dict[str, Any], current: str | None
) -> None:
    aws, writes = prepare(monkeypatch)
    aws.values["lock"] = lock
    aws.values["state"]["current_operation_id"] = current
    assert (
        reconcile_lambda.handler({"schema_version": 1, "operation": "scheduled_reconcile"}, None)[
            "result"
        ]
        == "skipped-operation-or-lock"
    )
    assert writes == []


@pytest.mark.parametrize(
    "code,expected",
    [
        ("ConditionalCheckFailedException", "skipped-concurrent-state-change"),
        ("AccessDeniedException", None),
    ],
)
def test_only_conditional_race_is_safe_skip(
    monkeypatch: pytest.MonkeyPatch, code: str, expected: str | None
) -> None:
    prepare(monkeypatch)

    def save(*args: Any, **kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": code}}, "UpdateItem")

    service = reconcile_lambda._service
    assert service is not None
    monkeypatch.setattr(service.repository, "save", save)
    if expected is None:
        with pytest.raises(ClientError):
            reconcile_lambda.handler(
                {"schema_version": 1, "operation": "scheduled_reconcile"}, None
            )
    else:
        assert (
            reconcile_lambda.handler(
                {"schema_version": 1, "operation": "scheduled_reconcile"}, None
            )["result"]
            == expected
        )


def test_scheduled_repository_condition_preserves_desired_and_operation_atomic_boundary() -> None:
    updates: list[dict[str, Any]] = []
    api = SimpleNamespace(update_item=lambda **kwargs: updates.append(kwargs))
    repository = SystemStateRepository(api, table_name="state", system_id="wishicraft-main")
    repository.save(persisted_state(), expected_desired_revision=42)
    request = updates[0]
    assert request["ExpressionAttributeValues"][":revision"] == {"N": "42"}
    assert request["ExpressionAttributeValues"][":null"] == {"NULL": True}
    assert request["ConditionExpression"].endswith("AND #revision = :revision AND #current = :null")
    assert "#current =" not in request["UpdateExpression"]
