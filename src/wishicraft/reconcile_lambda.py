"""Thin versioned Lambda adapter for Phase 3 Reconcile."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.endpoint import Route53Api, Route53Observer
from wishicraft.reconcile import (
    ReconcileService,
    StatusFactory,
    TargetEc2Api,
    TargetResolver,
)
from wishicraft.runtime_catalog import configured_catalog
from wishicraft.ssm_probe import CanonicalHostRuntimeProbeRunner, SsmCommandApi
from wishicraft.status import Ec2Api, HostRuntimeProbeApi, SsmApi, TargetStatusObserver
from wishicraft.system_state import DynamoApi, SystemStateRepository


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class AwsStatusFactory:
    def __init__(self, ec2: object, ssm: object, *, game_id: str, timeout_seconds: int) -> None:
        self._ec2, self._ssm = ec2, ssm
        self._game_id, self._timeout = game_id, timeout_seconds

    def create(self, instance_id: str) -> TargetStatusObserver:
        return TargetStatusObserver(
            instance_id=instance_id,
            expected_game_id=self._game_id,
            ec2=cast(Ec2Api, self._ec2),
            ssm=cast(SsmApi, self._ssm),
            host_runtime_probe=cast(
                HostRuntimeProbeApi,
                CanonicalHostRuntimeProbeRunner(
                    ssm=cast(SsmCommandApi, self._ssm), timeout_seconds=self._timeout
                ),
            ),
        )


_service: ReconcileService | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    if event == {"schema_version": 1, "operation": "scheduled_reconcile"}:
        return _scheduled_reconcile()
    if not isinstance(event, dict) or event != {
        "schema_version": 1,
        "operation": "reconcile",
    }:
        raise ValueError("invalid Reconcile invocation")
    state = _get_service().reconcile(observed_at=datetime.now(UTC))
    result = state.to_item()
    if configured_catalog() is not None:
        boto3 = importlib.import_module("boto3")
        raw = boto3.client("dynamodb").get_item(
            TableName=_required_environment("SYSTEM_STATE_TABLE"),
            Key={"system_id": {"S": _required_environment("SYSTEM_ID")}},
            ConsistentRead=True,
        )["Item"]
        selected = raw.get("desired_game_id", {}).get("S") or _required_environment("GAME_ID")
        if selected != state.game_id or raw["desired_state"]["S"] != state.desired_state.value:
            raise ValueError("Game selection changed during observation")
        result["selected_game_id"] = selected
        result["current_operation_id"] = raw.get("current_operation_id", {}).get("S")
    return result


def _scheduled_reconcile() -> dict[str, object]:
    from wishicraft.monitoring_telemetry import integer

    boto3 = importlib.import_module("boto3")
    deserializer = importlib.import_module("boto3.dynamodb.types").TypeDeserializer()
    ddb = boto3.client("dynamodb")
    raw = ddb.get_item(
        TableName=_required_environment("SYSTEM_STATE_TABLE"),
        Key={"system_id": {"S": _required_environment("SYSTEM_ID")}},
        ConsistentRead=True,
    ).get("Item", {})
    state = {key: deserializer.deserialize(value) for key, value in raw.items()}
    if not state:
        raise RuntimeError("scheduled observation requires initialized SystemState")
    revision = integer(state.get("desired_revision"))
    if revision is None or revision < 0:
        raise RuntimeError("invalid scheduled observation state")
    lock = ddb.get_item(
        TableName=_required_environment("LOCKS_TABLE"),
        Key={"lock_name": {"S": _required_environment("GLOBAL_LOCK_NAME")}},
        ConsistentRead=True,
    ).get("Item")
    if state.get("current_operation_id") is not None or lock:
        return {"result": "skipped-operation-or-lock"}
    # Even stable STOPPED gets direct EC2/DNS observation, but no SSM host probe.
    service = _get_service()
    observed = service.reconcile(observed_at=datetime.now(UTC), persist=False)
    repository = cast(SystemStateRepository, service.repository)
    try:
        repository.save(observed, expected_desired_revision=revision)
    except Exception as error:
        response = getattr(error, "response", {})
        if (
            isinstance(response, dict)
            and response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
        ):
            return {"result": "skipped-concurrent-state-change"}
        raise
    return {"result": "observed", "observed_at": observed.to_item()["observed_at"]}


def _get_service() -> ReconcileService:
    global _service
    if configured_catalog() is not None:
        return _build_service()
    if _service is None:
        _service = _build_service()
    return _service


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _build_service() -> ReconcileService:
    boto3 = importlib.import_module("boto3")
    session = cast(AwsSession, boto3)
    region = _required_environment("AWS_REGION")
    ec2 = session.client("ec2", region_name=region)
    ssm = session.client("ssm", region_name=region)
    route53 = session.client("route53", region_name=region)
    dynamodb = session.client("dynamodb", region_name=region)
    game_id = _required_environment("GAME_ID")
    repository = SystemStateRepository(
        cast(DynamoApi, dynamodb),
        table_name=_required_environment("SYSTEM_STATE_TABLE"),
        system_id=_required_environment("SYSTEM_ID"),
    )
    catalog = configured_catalog()
    snapshot = repository.desired_snapshot() if catalog else None
    if catalog and snapshot:
        game_id = snapshot.desired_game_id or game_id
        catalog.data_source(game_id)
    expected_source = None
    if os.environ.get("RESET_CONTRACT") == "1":
        from wishicraft.world_reference import selected_source

        expected_source = selected_source(dynamodb, _required_environment("GAMES_TABLE"), game_id)
    return ReconcileService(
        expected_data_source=expected_source,
        system_id=_required_environment("SYSTEM_ID"),
        environment=_required_environment("STAGE"),
        game_id=game_id,
        selected_snapshot=snapshot,
        target_resolver=TargetResolver(
            cast(TargetEc2Api, ec2),
            project=_required_environment("PROJECT"),
            stage=_required_environment("STAGE"),
        ),
        status_factory=cast(
            StatusFactory,
            AwsStatusFactory(
                ec2,
                ssm,
                game_id=game_id,
                timeout_seconds=int(_required_environment("SSM_PROBE_TIMEOUT_SECONDS")),
            ),
        ),
        dns_observer=Route53Observer(
            cast(Route53Api, route53),
            hosted_zone_id=_required_environment("HOSTED_ZONE_ID"),
            record_name=_required_environment("RECORD_NAME"),
        ),
        repository=repository,
    )
