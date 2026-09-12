"""Versioned Lambda task boundary for the Phase 6 STOP state machine."""

from __future__ import annotations

import importlib
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast

from wishicraft.auto_stop import AutoStopIntent, AutoStopIntentStatus, intent_matches_heartbeat
from wishicraft.operation import (
    DynamoApi,
    LeaseProof,
    LeaseRepository,
    OperationRepository,
    OperationStatus,
)
from wishicraft.reconcile import TargetEc2Api, TargetResolver
from wishicraft.reconcile_lambda import AwsStatusFactory
from wishicraft.runtime_catalog import bind_operation, configured_catalog
from wishicraft.runtime_contract import RuntimeTargetRepository, bound_instance, select_target
from wishicraft.runtime_heartbeat_producer import _decode
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
from wishicraft.switch_contract import prepare_switch
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
        self.cloudwatch = session.client("cloudwatch", region_name=region)
        dynamodb = cast(DynamoApi, session.client("dynamodb", region_name=region))
        self.system_id = _env("SYSTEM_ID")
        self.game_id = _env("GAME_ID")
        self.data_source = _env("RUNTIME_DATA_SOURCE")
        self.config_digest = _env("RUNTIME_CONFIG_DIGEST")
        self.targets = RuntimeTargetRepository(dynamodb, _env("OPERATIONS_TABLE"))
        self.runtime_id = "wishicraft-host-runtime"
        self.data_volume_id = _env("DATA_VOLUME_ID")
        self.data_volume_device = _env("DATA_VOLUME_DEVICE")
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
            leases=leases,
            states=states,
            lease_seconds=int(_env("LOCK_LEASE_SECONDS")),
            preserve_selection=configured_catalog() is not None,
        )
        self.operations = OperationRepository(
            dynamodb,
            operations_table=_env("OPERATIONS_TABLE"),
            locks_table=_env("LOCKS_TABLE"),
            system_state_table=_env("SYSTEM_STATE_TABLE"),
            system_id=self.system_id,
            lock_name=_env("GLOBAL_LOCK_NAME"),
        )
        self.dynamodb = dynamodb
        self.heartbeats_table = _env("RUNTIME_HEARTBEATS_TABLE")
        self.intents_table = _env("AUTO_STOP_INTENTS_TABLE")
        self.status_factory = AwsStatusFactory(
            self.ec2,
            self.ssm,
            game_id=self.game_id,
            timeout_seconds=int(_env("SSM_PROBE_TIMEOUT_SECONDS")),
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
    if payload["action"] not in {"prepare_switch", "prepare_reset"}:
        bind_operation(runtime, _string(payload, "operation_id"), action="STOP")
        if configured_catalog() is not None:
            runtime.status_factory = AwsStatusFactory(
                runtime.ec2,
                runtime.ssm,
                game_id=runtime.game_id,
                timeout_seconds=int(_env("SSM_PROBE_TIMEOUT_SECONDS")),
            )
    now = datetime.now(UTC)
    proof = LeaseProof(
        runtime.system_id, _string(payload, "operation_id"), _string(payload, "lease_id"), 0
    )
    action = payload["action"]
    if action in {
        "prepare_reset",
        "run_reset_prepare",
        "check_reset_prepare",
        "commit_reset",
        "run_reset_cleanup",
        "check_reset_cleanup",
    }:
        from wishicraft.reset_workflow import task

        return task(runtime, proof, payload, now)
    if action == "prepare_switch":
        prepare_switch(runtime, proof, _mapping(payload, "state"), now)
        return {"prepared": True}
    if action == "verify_switch_stopped":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        if not _receipt_stopped(payload, runtime, proof.owner_operation_id):
            raise ValueError("SWITCH source stop is not confirmed")
        return {"source_stopped": True}
    if action == "automatic_final_gate":
        if payload.get("requested_by") != "SCHEDULE":
            return {"proceed": True, "automatic": False}
        intent_id = _string(payload, "auto_stop_intent_id")
        runtime.coordinator.leases.verify_owned(proof, now=now)
        try:
            reason = _automatic_gate_reason(runtime, payload, intent_id=intent_id, now=now)
        except Exception:  # noqa: BLE001 - observation failures cancel before mutation.
            reason = "FINAL_GATE_OBSERVATION_UNKNOWN"
        if reason is not None:
            runtime.operations.complete_owned(
                proof=proof,
                status=OperationStatus.CANCELLED,
                completed_at=now,
                result={"automatic_stop": True, "intent_id": intent_id, "reason": reason},
            )
            try:
                _cancel_intent(runtime, intent_id=intent_id, reason=reason, now=now)
            except Exception:  # noqa: BLE001 - Operation/Lock convergence remains authoritative.
                pass
            print(
                json.dumps(
                    {
                        "event": "automatic_stop_cancelled",
                        "operation_id": proof.owner_operation_id,
                        "reason": reason,
                    },
                    separators=(",", ":"),
                )
            )
            try:
                cast(Any, runtime.cloudwatch).put_metric_data(
                    Namespace=_env("METRIC_NAMESPACE"),
                    MetricData=[
                        {
                            "MetricName": "ScheduledStopCancelled",
                            "Dimensions": [{"Name": "Stage", "Value": _env("STAGE")}],
                            "Value": 1,
                            "Unit": "Count",
                        }
                    ],
                )
            except Exception:  # noqa: BLE001 - monitoring cannot undo safe cancellation.
                pass
            return {"proceed": False, "automatic": True, "reason": reason}
        return {"proceed": True, "automatic": True}
    if action == "set_desired":
        runtime.coordinator.leases.verify_owned(proof, now=now)
        select_target(runtime, proof, _mapping(payload, "state"), action="STOP")
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
            "runtime_stopped": observation.runtime_stopped
            and _receipt_stopped(payload, runtime, proof.owner_operation_id),
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
        command_id = runtime.host_stop.stop(
            instance_id=bound_instance(runtime, proof.owner_operation_id),
            operation_id=proof.owner_operation_id,
            lease_id=proof.lease_id,
        )
        return {"command_id": command_id}
    if action == "check_host_stop":
        result = _command_result(
            cast(SsmInvocationApi, runtime.ssm),
            instance_id=bound_instance(runtime, proof.owner_operation_id),
            command_id=_string(payload, "command_id"),
        )
        return result
    if action == "stop_ec2":
        state = _mapping(payload, "state")
        if StopObservation.from_item(state).ec2_state != "stopped" and not _receipt_stopped(
            payload, runtime, proof.owner_operation_id
        ):
            raise ValueError("runtime stop receipt not confirmed")
        runtime.coordinator.leases.verify_owned(proof, now=now)
        runtime.operations.update_step(
            operation_id=proof.owner_operation_id,
            current_step="EC2_STOPPING",
            status=OperationStatus.RUNNING,
            updated_at=now,
        )
        stopped = runtime.ec2_stop.stop_if_needed(
            instance_id=bound_instance(runtime, proof.owner_operation_id),
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


def _automatic_gate_reason(
    runtime: Runtime, payload: dict[str, object], *, intent_id: str, now: datetime
) -> str | None:
    state = _mapping(payload, "state")
    if (
        state.get("game_id") != runtime.game_id
        or state.get("desired_state") != "RUNNING"
        or state.get("health") != "HEALTHY"
        or state.get("discrepancies") != []
        or state.get("observation_errors") != []
    ):
        return "RECONCILE_NOT_SAFE"
    intent = _load_intent(runtime, intent_id)
    heartbeat_response = runtime.dynamodb.get_item(
        TableName=runtime.heartbeats_table,
        Key={"system_id": {"S": runtime.system_id}},
        ConsistentRead=True,
    )
    heartbeat_item = (
        heartbeat_response.get("Item") if isinstance(heartbeat_response, dict) else None
    )
    heartbeat = _decode(heartbeat_item) if isinstance(heartbeat_item, dict) else None
    if not intent_matches_heartbeat(intent, heartbeat, runtime_id=runtime.runtime_id, now=now):
        return "HEARTBEAT_NOT_TRUSTED_EMPTY"
    eligible_at = intent.stop_eligible_at()
    if (
        intent.status
        not in {
            AutoStopIntentStatus.ADMISSION_ATTEMPTED,
            AutoStopIntentStatus.STOP_REQUESTED,
        }
        or intent.warning_delivery_state != "DELIVERED"
        or eligible_at is None
        or now < eligible_at
    ):
        return "WARNING_OR_IDLE_WINDOW_INCOMPLETE"
    instance_id = runtime.resolver.resolve()
    if state.get("target_instance_id") != instance_id:
        return "TARGET_IDENTITY_MISMATCH"
    if not _volume_binding_safe(runtime, instance_id=instance_id):
        return "DATA_VOLUME_BINDING_MISMATCH"
    direct = runtime.status_factory.create(instance_id).observe(observed_at=now)
    if (
        not direct.ready
        or direct.observed_active_game_id != runtime.game_id
        or direct.player_count != 0
    ):
        return "DIRECT_PLAYER_OBSERVATION_NOT_ZERO"
    if intent.run_id is not None:
        execution = direct.execution
        if not isinstance(execution, dict) or not isinstance(execution.get("target"), dict):
            return "DIRECT_RUN_ID_UNKNOWN"
        if cast(dict[str, object], execution["target"]).get("run_id") != intent.run_id:
            return "DIRECT_RUN_ID_MISMATCH"
        if execution.get("process_id") != intent.process_id:
            return "DIRECT_PROCESS_ID_MISMATCH"
    return None


def _volume_binding_safe(runtime: Runtime, *, instance_id: str) -> bool:
    response = cast(Any, runtime.ec2).describe_volumes(VolumeIds=[runtime.data_volume_id])
    volumes = response.get("Volumes") if isinstance(response, dict) else None
    if not isinstance(volumes, list) or len(volumes) != 1:
        return False
    volume = volumes[0]
    if not isinstance(volume, dict) or volume.get("VolumeId") != runtime.data_volume_id:
        return False
    attachments = volume.get("Attachments")
    return bool(
        isinstance(attachments, list)
        and len(attachments) == 1
        and isinstance(attachments[0], dict)
        and attachments[0].get("InstanceId") == instance_id
        and attachments[0].get("Device") == runtime.data_volume_device
        and attachments[0].get("State") == "attached"
        and attachments[0].get("DeleteOnTermination") is False
    )


def _load_intent(runtime: Runtime, intent_id: str) -> AutoStopIntent:
    response = runtime.dynamodb.get_item(
        TableName=runtime.intents_table,
        Key={"game_id": {"S": runtime.game_id}, "intent_id": {"S": intent_id}},
        ConsistentRead=True,
    )
    item = response.get("Item") if isinstance(response, dict) else None
    if not isinstance(item, dict):
        raise ValueError("automatic STOP intent is missing")
    from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

    decode = TypeDeserializer()
    plain = {str(name): decode.deserialize(value) for name, value in item.items()}
    return AutoStopIntent(
        intent_id=_string(plain, "intent_id"),
        game_id=_string(plain, "game_id"),
        boot_id=_string(plain, "boot_id"),
        run_id=cast(str | None, plain.get("run_id")),
        process_id=cast(str | None, plain.get("process_id")),
        empty_since=_timestamp(plain, "empty_since"),
        idle_timeout_minutes=_integer(plain, "idle_timeout_minutes"),
        warning_lead_minutes=_integer(plain, "warning_lead_minutes"),
        warning_delivery_id=_string(plain, "warning_delivery_id"),
        warning_delivery_state=_string(plain, "warning_delivery_state"),
        warning_delivered_at=_optional_timestamp(plain, "warning_delivered_at"),
        status=AutoStopIntentStatus(_string(plain, "status")),
        created_at=_timestamp(plain, "created_at"),
        updated_at=_timestamp(plain, "updated_at"),
        block_reason=plain.get("block_reason")
        if isinstance(plain.get("block_reason"), str)
        else None,
    )


def _cancel_intent(runtime: Runtime, *, intent_id: str, reason: str, now: datetime) -> None:
    runtime.dynamodb.update_item(
        TableName=runtime.intents_table,
        Key={"game_id": {"S": runtime.game_id}, "intent_id": {"S": intent_id}},
        UpdateExpression="SET #status = :cancelled, block_reason = :reason, updated_at = :now",
        ConditionExpression="#status IN (:attempted, :requested)",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":cancelled": {"S": AutoStopIntentStatus.CANCELLED.value},
            ":attempted": {"S": AutoStopIntentStatus.ADMISSION_ATTEMPTED.value},
            ":requested": {"S": AutoStopIntentStatus.STOP_REQUESTED.value},
            ":reason": {"S": reason},
            ":now": {"S": now.isoformat().replace("+00:00", "Z")},
        },
    )


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


def _integer(value: dict[str, object], name: str) -> int:
    result = value.get(name)
    if isinstance(result, bool):
        raise ValueError(f"invalid {name}")
    if isinstance(result, int):
        normalized = result
    elif isinstance(result, Decimal):
        if not result.is_finite() or result != result.to_integral_value():
            raise ValueError(f"invalid {name}")
        normalized = int(result)
    else:
        raise ValueError(f"invalid {name}")
    if normalized <= 0:
        raise ValueError(f"invalid {name}")
    return normalized


def _timestamp(value: dict[str, object], name: str) -> datetime:
    result = value.get(name)
    if not isinstance(result, str):
        raise ValueError(f"invalid {name}")
    parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"invalid {name}")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: dict[str, object], name: str) -> datetime | None:
    return None if value.get(name) is None else _timestamp(value, name)


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


def _receipt_stopped(payload: dict[str, object], runtime: Runtime, operation_id: str) -> bool:
    state = _mapping(payload, "state")
    observation = _mapping(state, "observation")
    execution = observation.get("execution")
    return (
        isinstance(execution, dict)
        and execution.get("phase") == "stopped"
        and execution.get("target") == runtime.targets.read(operation_id)
    )
