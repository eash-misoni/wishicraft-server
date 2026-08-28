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
    if not isinstance(event, dict) or event != {
        "schema_version": 1,
        "operation": "reconcile",
    }:
        raise ValueError("invalid Reconcile invocation")
    state = _get_service().reconcile(observed_at=datetime.now(UTC))
    return state.to_item()


def _get_service() -> ReconcileService:
    global _service
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
    return ReconcileService(
        system_id=_required_environment("SYSTEM_ID"),
        environment=_required_environment("STAGE"),
        game_id=game_id,
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
        repository=SystemStateRepository(
            cast(DynamoApi, dynamodb),
            table_name=_required_environment("SYSTEM_STATE_TABLE"),
            system_id=_required_environment("SYSTEM_ID"),
        ),
    )
