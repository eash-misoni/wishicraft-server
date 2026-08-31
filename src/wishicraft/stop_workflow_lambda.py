"""Versioned Lambda task boundary for the Phase 6 STOP state machine."""

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
from wishicraft.stop_workflow import (
    Ec2StopAdapter,
    Ec2StopApi,
    FixedHostStopAdapter,
    SsmStopApi,
    StopCoordinator,
    StopErrorCode,
    StopObservation,
    StopWorkflowError,
)
from wishicraft.system_state import SystemStateRepository


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


class Route53WriteApi(Protocol):
    def list_resource_record_sets(self, **kwargs: object) -> object: ...
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
        self.coordinator = StopCoordinator(
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
        self.ec2_stop = Ec2StopAdapter(cast(Ec2StopApi, self.ec2))
        self.host_stop = FixedHostStopAdapter(
            cast(SsmStopApi, self.ssm), timeout_seconds=int(_env("HOST_STOP_TIMEOUT_SECONDS"))
        )


_runtime: Runtime | None = None


def handler(event: object, context: object) -> dict[str, object]:
    del context
    payload = _payload(event)
    runtime = _get_runtime()
    now = datetime.now(UTC)
    proof = LeaseProof(
        runtime.system_id, _string(payload, "operation_id"), _string(payload, "lease_id"), 0
    )
    action = payload["action"]
    if action == "set_desired":
        observation = StopObservation.from_item(_mapping(payload, "state"))
        revision, already_stopped = runtime.coordinator.verify_and_set_desired(
            proof=proof, observation=observation, now=now
        )
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="DESIRED_STOPPED",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        return {
            "desired_revision": revision,
            "already_stopped": already_stopped,
            "runtime_stopped": observation.runtime_stopped,
        }
    if action == "renew":
        renewed = runtime.coordinator.renew(proof, now=now)
        return {"lease_expires_at": renewed.lease_expires_at}
    if action == "run_host_stop":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="HOST_RUNTIME_STOPPING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        command_id = runtime.host_stop.stop(instance_id=runtime.resolver.resolve())
        return {"command_id": command_id}
    if action == "check_host_stop":
        result = _command_result(
            cast(SsmInvocationApi, runtime.ssm),
            instance_id=runtime.resolver.resolve(),
            command_id=_string(payload, "command_id"),
        )
        return result
    if action == "stop_ec2":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="EC2_STOPPING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        stopped = runtime.ec2_stop.stop_if_needed(
            instance_id=runtime.resolver.resolve(),
            observation=StopObservation.from_item(_mapping(payload, "state")),
        )
        return {"stopped": stopped}
    if action == "delete_dns":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="ENDPOINT_CLEANUP",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        return _delete_dns(cast(Route53WriteApi, runtime.route53), runtime)
    if action == "check_dns_change":
        complete = _dns_change_complete(
            cast(Route53WriteApi, runtime.route53), _string(payload, "change_id")
        )
        return {"complete": complete}
    if action == "complete":
        observation = StopObservation.from_item(_mapping(payload, "state"))
        desired = runtime.coordinator.states.desired_snapshot()
        if desired.desired_state.value != "STOPPED" or not observation.ready_for_success():
            raise StopWorkflowError(StopErrorCode.OBSERVATION_FAILED)
        runtime.operations.complete_owned(
            proof=proof, status=OperationStatus.SUCCEEDED, completed_at=now
        )
        return {"status": "SUCCEEDED"}
    if action == "fail":
        error_code = _classified_error(payload)
        runtime.operations.complete_owned(
            proof=proof,
            status=OperationStatus.FAILED,
            completed_at=now,
            error_code=error_code,
        )
        return {"status": "FAILED"}
    raise ValueError("unsupported STOP workflow action")


def _command_result(
    api: SsmInvocationApi, *, instance_id: str, command_id: str
) -> dict[str, object]:
    response = api.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
    response_map = response if isinstance(response, dict) else {}
    status = response_map.get("Status")
    if status in {"Pending", "InProgress", "Delayed"}:
        return {"status": status, "complete": False}
    if status == "Success" and response_map.get("ResponseCode") in {None, 0}:
        return {"status": status, "complete": True}
    output = response_map.get("StandardOutputContent")
    if isinstance(output, str):
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = value.get("error_code") if isinstance(value, dict) else None
            if code in {item.value for item in StopErrorCode}:
                raise StopWorkflowError(StopErrorCode(code))
    if status in {"Failed", "TimedOut", "Cancelled", "Cancelling"}:
        raise StopWorkflowError(StopErrorCode.GRACEFUL_STOP_FAILED)
    raise StopWorkflowError(StopErrorCode.GRACEFUL_STOP_FAILED)


def _delete_dns(api: Route53WriteApi, runtime: Runtime) -> dict[str, object]:
    response = api.list_resource_record_sets(
        HostedZoneId=runtime.hosted_zone_id,
        StartRecordName=runtime.record_name,
        StartRecordType="A",
        MaxItems="1",
    )
    records = response.get("ResourceRecordSets") if isinstance(response, dict) else None
    if not isinstance(records, list):
        raise StopWorkflowError(StopErrorCode.DNS_DELETE_FAILED)
    expected_name = runtime.record_name.rstrip(".") + "."
    record = records[0] if records else None
    if (
        not isinstance(record, dict)
        or record.get("Name") != expected_name
        or record.get("Type") != "A"
    ):
        return {"absent": True}
    change = api.change_resource_record_sets(
        HostedZoneId=runtime.hosted_zone_id,
        ChangeBatch={
            "Comment": "Wishicraft Phase 6 STOP endpoint cleanup",
            "Changes": [{"Action": "DELETE", "ResourceRecordSet": record}],
        },
    )
    info = change.get("ChangeInfo") if isinstance(change, dict) else None
    change_id = info.get("Id") if isinstance(info, dict) else None
    if not isinstance(change_id, str) or not change_id.startswith("/change/"):
        raise StopWorkflowError(StopErrorCode.DNS_DELETE_FAILED)
    return {"absent": False, "change_id": change_id}


def _dns_change_complete(api: Route53WriteApi, change_id: str) -> bool:
    response = api.get_change(Id=change_id)
    info = response.get("ChangeInfo") if isinstance(response, dict) else None
    status = info.get("Status") if isinstance(info, dict) else None
    if status not in {"PENDING", "INSYNC"}:
        raise StopWorkflowError(StopErrorCode.DNS_DELETE_FAILED)
    return bool(status == "INSYNC")


def _classified_error(payload: dict[str, object]) -> str:
    default = _string(payload, "error_code")
    workflow_error = payload.get("workflow_error")
    if isinstance(workflow_error, dict):
        cause = workflow_error.get("Cause")
        if isinstance(cause, str):
            try:
                parsed = json.loads(cause)
            except json.JSONDecodeError:
                parsed = None
            message = parsed.get("errorMessage") if isinstance(parsed, dict) else None
            if message in {code.value for code in StopErrorCode}:
                return cast(str, message)
    return default


def _payload(event: object) -> dict[str, object]:
    if not isinstance(event, dict) or event.get("schema_version") != 1:
        raise ValueError("invalid STOP workflow invocation")
    if not {"schema_version", "action", "operation_id", "lease_id"} <= set(event):
        raise ValueError("invalid STOP workflow invocation")
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
