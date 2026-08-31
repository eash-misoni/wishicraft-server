"""Versioned Lambda task boundary for the Phase 5 START state machine."""

from __future__ import annotations

import importlib
import json
import os
from datetime import UTC, datetime
from typing import Protocol, cast

from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    LeaseRepository,
    OperationRepository,
    OperationStatus,
)
from wishicraft.reconcile import TargetEc2Api, TargetResolver
from wishicraft.start_workflow import (
    Ec2LifecycleAdapter,
    Ec2LifecycleApi,
    FixedHostStartAdapter,
    SsmStartApi,
    StartCoordinator,
    StartErrorCode,
    StartObservation,
    StartWorkflowError,
)
from wishicraft.system_state import SystemStateRepository


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class Route53WriteApi(Protocol):
    def change_resource_record_sets(self, **kwargs: object) -> object: ...
    def get_change(self, **kwargs: object) -> object: ...


class SsmInvocationApi(Protocol):
    def get_command_invocation(self, **kwargs: object) -> object: ...


class Runtime:
    def __init__(self) -> None:
        boto3 = importlib.import_module("boto3")
        session = cast(AwsSession, boto3)
        region = _env("AWS_REGION")
        self.ec2 = session.client("ec2", region_name=region)
        self.ssm = session.client("ssm", region_name=region)
        self.route53 = session.client("route53", region_name=region)
        dynamodb = cast(DynamoApi, session.client("dynamodb", region_name=region))
        self.game_id = _env("GAME_ID")
        self.system_id = _env("SYSTEM_ID")
        self.record_name = _env("RECORD_NAME")
        self.hosted_zone_id = _env("HOSTED_ZONE_ID")
        self.resolver = TargetResolver(
            cast(TargetEc2Api, self.ec2), project=_env("PROJECT"), stage=_env("STAGE")
        )
        leases = LeaseRepository(
            dynamodb, table_name=_env("LOCKS_TABLE"), lock_name=_env("GLOBAL_LOCK_NAME")
        )
        states = SystemStateRepository(
            dynamodb, table_name=_env("SYSTEM_STATE_TABLE"), system_id=self.system_id
        )
        self.coordinator = StartCoordinator(
            leases=leases, states=states, lease_seconds=int(_env("LOCK_LEASE_SECONDS"))
        )
        self.operations = OperationRepository(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            system_id=self.system_id,
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        self.ec2_lifecycle = Ec2LifecycleAdapter(cast(Ec2LifecycleApi, self.ec2))
        self.host_start = FixedHostStartAdapter(
            cast(SsmStartApi, self.ssm), timeout_seconds=int(_env("HOST_START_TIMEOUT_SECONDS"))
        )


_runtime: Runtime | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    payload = _payload(event)
    runtime = _get_runtime()
    now = datetime.now(UTC)
    proof = LeaseProof(
        runtime.system_id,
        _string(payload, "operation_id"),
        _string(payload, "lease_id"),
        0,
    )
    action = payload["action"]
    if action == "set_desired":
        observation = StartObservation.from_item(_mapping(payload, "state"))
        revision, already_ready = runtime.coordinator.verify_and_set_desired(
            proof=proof, observation=observation, game_id=runtime.game_id, now=now
        )
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="DESIRED_RUNNING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        return {"desired_revision": revision, "already_ready": already_ready}
    if action == "start_ec2":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="EC2_STARTING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        observation = StartObservation.from_item(_mapping(payload, "state"))
        started = runtime.ec2_lifecycle.start_if_needed(
            instance_id=runtime.resolver.resolve(), current_state=observation.ec2_state
        )
        return {"started": started}
    if action == "renew":
        renewed = runtime.coordinator.renew(proof, now=now)
        return {"lease_expires_at": renewed.lease_expires_at}
    if action == "run_host_start":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="HOST_RUNTIME_STARTING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        command_id = runtime.host_start.start(instance_id=runtime.resolver.resolve())
        return {"command_id": command_id}
    if action == "check_host_start":
        status = _command_status(
            cast(SsmInvocationApi, runtime.ssm),
            instance_id=runtime.resolver.resolve(),
            command_id=_string(payload, "command_id"),
        )
        return {"status": status, "complete": status == "Success"}
    if action == "upsert_dns":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="ENDPOINT_CONVERGING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        observation = StartObservation.from_item(_mapping(payload, "state"))
        if not observation.runtime_ready or observation.observed_active_game_id != runtime.game_id:
            raise StartWorkflowError(StartErrorCode.READY_TIMEOUT)
        if observation.public_ipv4 is None:
            raise StartWorkflowError(StartErrorCode.ENDPOINT_DISCREPANCY)
        change_id = _upsert_dns(
            cast(Route53WriteApi, runtime.route53), runtime, observation.public_ipv4
        )
        return {"change_id": change_id}
    if action == "check_dns_change":
        status = _dns_change_status(
            cast(Route53WriteApi, runtime.route53), _string(payload, "change_id")
        )
        return {"status": status, "complete": status == "INSYNC"}
    if action == "complete":
        observation = StartObservation.from_item(_mapping(payload, "state"))
        if not observation.ready_for_success(runtime.game_id):
            raise StartWorkflowError(StartErrorCode.ENDPOINT_DISCREPANCY)
        runtime.operations.complete_owned(
            proof=proof, status=OperationStatus.SUCCEEDED, completed_at=now
        )
        return {"status": "SUCCEEDED"}
    if action == "fail":
        error_code = _string(payload, "error_code")
        workflow_error = payload.get("workflow_error")
        if isinstance(workflow_error, dict):
            cause = workflow_error.get("Cause")
            if isinstance(cause, str):
                try:
                    parsed = json.loads(cause)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and parsed.get("errorMessage") in {
                    code.value for code in StartErrorCode
                }:
                    error_code = cast(str, parsed["errorMessage"])
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.FAILED,
            completed_at=now,
            error_code=error_code,
        )
        return {"status": "FAILED"}
    raise ValueError("unsupported START workflow action")


def _command_status(api: SsmInvocationApi, *, instance_id: str, command_id: str) -> str:
    response = api.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
    status = response.get("Status") if isinstance(response, dict) else None
    if status in {"Pending", "InProgress", "Delayed", "Success"}:
        return cast(str, status)
    raise StartWorkflowError(StartErrorCode.HOST_RUNTIME_FAILED)


def _upsert_dns(api: Route53WriteApi, runtime: Runtime, public_ipv4: str) -> str:
    response = api.change_resource_record_sets(
        HostedZoneId=runtime.hosted_zone_id,
        ChangeBatch={
            "Comment": "Wishicraft Phase 5 START endpoint convergence",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": runtime.record_name,
                        "Type": "A",
                        "TTL": int(_env("RECORD_TTL_SECONDS")),
                        "ResourceRecords": [{"Value": public_ipv4}],
                    },
                }
            ],
        },
    )
    change = response.get("ChangeInfo") if isinstance(response, dict) else None
    change_id = change.get("Id") if isinstance(change, dict) else None
    if not isinstance(change_id, str) or not change_id.startswith("/change/"):
        raise StartWorkflowError(StartErrorCode.ENDPOINT_DISCREPANCY)
    return change_id


def _dns_change_status(api: Route53WriteApi, change_id: str) -> str:
    response = api.get_change(Id=change_id)
    change = response.get("ChangeInfo") if isinstance(response, dict) else None
    status = change.get("Status") if isinstance(change, dict) else None
    if status not in {"PENDING", "INSYNC"}:
        raise StartWorkflowError(StartErrorCode.ENDPOINT_DISCREPANCY)
    return cast(str, status)


def _payload(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("invalid START workflow invocation")
    required = {"schema_version", "action", "operation_id", "lease_id"}
    if not required <= set(event):
        raise ValueError("invalid START workflow invocation")
    _string(event, "action")
    _string(event, "operation_id")
    _string(event, "lease_id")
    return event


def _mapping(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise ValueError(f"invalid {name}")
    return result


def _string(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result:
        raise ValueError(f"invalid {name}")
    return result


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing Lambda configuration: {name}")
    return value


def _get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime
