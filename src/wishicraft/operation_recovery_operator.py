"""Canonical operator recovery for a failed pre-commit scheduled STOP."""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from wishicraft.config import load_configuration
from wishicraft.naming import resource_name
from wishicraft.operation import LeaseProof, OperationRepository, OperationStatus

RECOVERY_ERROR_CODE = "STOP_PRECONDITION_FAILED"
FAILED_EXECUTION_ERROR = "STOP_CLEANUP_FAILED"
MUTATION_STATES = frozenset(
    {
        "SetDesiredStopped",
        "RunHostStop",
        "StopEc2",
        "DeleteDns",
    }
)


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...

    def update_item(self, **kwargs: object) -> object: ...

    def delete_item(self, **kwargs: object) -> object: ...

    def transact_write_items(self, **kwargs: object) -> object: ...


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class StepFunctionsApi(Protocol):
    def describe_execution(self, **kwargs: object) -> object: ...

    def get_execution_history(self, **kwargs: object) -> object: ...


class Ec2Api(Protocol):
    def describe_volumes(self, **kwargs: object) -> object: ...


class Session(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


def recover_failed_scheduled_stop(
    *,
    dynamodb: DynamoApi,
    step_functions: StepFunctionsApi,
    reconcile: LambdaApi,
    ec2: Ec2Api,
    operation_id: str,
    operations_table: str,
    locks_table: str,
    system_state_table: str,
    intents_table: str,
    reconcile_function: str,
    system_id: str,
    game_id: str,
    lock_name: str,
    data_volume_id: str,
    data_volume_device: str,
    now: datetime,
) -> None:
    operation = _item(
        dynamodb,
        table=operations_table,
        key={"operation_id": {"S": operation_id}},
    )
    if (
        _s(operation, "operation_type") != "STOP"
        or _nested_s(operation, "requested_by", "source") != "SCHEDULE"
        or _s(operation, "status") != "PENDING"
    ):
        raise RuntimeError("operation is not the expected pending scheduled STOP")
    lease_id = _s(operation, "lease_id")
    execution_arn = _s(operation, "workflow_execution_arn")
    timeout_at = _timestamp(_s(operation, "timeout_at"))
    if now <= timeout_at:
        raise RuntimeError("operation deadline has not elapsed")

    execution = step_functions.describe_execution(executionArn=execution_arn)
    if not isinstance(execution, dict) or execution.get("status") != "FAILED":
        raise RuntimeError("STOP execution is not FAILED")
    if execution.get("error") != FAILED_EXECUTION_ERROR:
        raise RuntimeError("STOP execution has an unexpected failure")
    execution_input = _json_object(execution.get("input"), "execution input")
    intent_id = execution_input.get("auto_stop_intent_id")
    if (
        execution_input.get("operation_id") != operation_id
        or execution_input.get("lease_id") != lease_id
        or execution_input.get("requested_by") != "SCHEDULE"
        or not isinstance(intent_id, str)
    ):
        raise RuntimeError("STOP execution identity mismatch")
    entered = _entered_states(step_functions, execution_arn=execution_arn)
    if "AutomaticStopFinalGate" not in entered or entered & MUTATION_STATES:
        raise RuntimeError("STOP execution is not a proven pre-commit failure")

    lock = _item(
        dynamodb,
        table=locks_table,
        key={"lock_name": {"S": lock_name}},
    )
    if (
        _s(lock, "resource_id") != system_id
        or _s(lock, "owner_operation_id") != operation_id
        or _s(lock, "lease_id") != lease_id
    ):
        raise RuntimeError("Lock ownership mismatch")
    state_before = _item(
        dynamodb,
        table=system_state_table,
        key={"system_id": {"S": system_id}},
    )
    if _s(state_before, "current_operation_id") != operation_id:
        raise RuntimeError("Current Operation ownership mismatch")
    intent = _item(
        dynamodb,
        table=intents_table,
        key={"game_id": {"S": game_id}, "intent_id": {"S": intent_id}},
    )
    if (
        _s(intent, "status") != "STOP_REQUESTED"
        or _s(intent, "stop_operation_id") != operation_id
        or _s(intent, "game_id") != game_id
        or _s(operation, "idempotency_key") != f"auto-stop:{intent_id}"
    ):
        raise RuntimeError("Auto-stop Intent identity mismatch")

    state = _fresh_reconcile(reconcile, function_name=reconcile_function)
    observed_at = _timestamp(_required_string(state, "observed_at"))
    observation = state.get("observation")
    if (
        state.get("system_id") != system_id
        or state.get("game_id") != game_id
        or state.get("desired_state") != "RUNNING"
        or state.get("health") != "HEALTHY"
        or state.get("discrepancies") != []
        or state.get("observation_errors") != []
        or not isinstance(observation, dict)
        or observation.get("instance_id") is None
        or observation.get("ec2_state") != "running"
        or observation.get("runtime_ready") is not True
        or observation.get("minecraft_protocol_state") != "ready"
        or observation.get("dns_state") != "present"
        or observation.get("expected_game_id") != game_id
        or observation.get("observed_active_game_id") != game_id
    ):
        raise RuntimeError("fresh Reconcile did not prove safe RUNNING state")
    if observed_at <= timeout_at:
        raise RuntimeError("fresh Reconcile is not after the operation deadline")
    _verify_volume(
        ec2,
        volume_id=data_volume_id,
        instance_id=_required_string(observation, "instance_id"),
        device=data_volume_device,
    )

    OperationRepository(
        dynamodb,
        operations_table=operations_table,
        locks_table=locks_table,
        system_state_table=system_state_table,
        system_id=system_id,
        lock_name=lock_name,
    ).recover_stale(
        proof=LeaseProof(system_id, operation_id, lease_id, 0),
        timeout_at=timeout_at,
        reconciled_at=observed_at,
        status=OperationStatus.FAILED,
        error_code=RECOVERY_ERROR_CODE,
    )


def _item(api: DynamoApi, *, table: str, key: dict[str, dict[str, str]]) -> dict[str, object]:
    response = api.get_item(TableName=table, Key=key, ConsistentRead=True)
    item = response.get("Item") if isinstance(response, dict) else None
    if not isinstance(item, dict):
        raise RuntimeError("required recovery evidence does not exist")
    return item


def _s(item: dict[str, object], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, dict) or not isinstance(value.get("S"), str):
        raise RuntimeError(f"invalid recovery evidence: {name}")
    return cast(str, value["S"])


def _nested_s(item: dict[str, object], name: str, nested: str) -> str:
    value = item.get(name)
    mapping = value.get("M") if isinstance(value, dict) else None
    if not isinstance(mapping, dict):
        raise RuntimeError(f"invalid recovery evidence: {name}")
    return _s(mapping, nested)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("invalid recovery timestamp") from error
    if parsed.tzinfo is None:
        raise RuntimeError("invalid recovery timestamp")
    return parsed.astimezone(UTC)


def _json_object(value: object, name: str) -> dict[str, object]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else None
    except json.JSONDecodeError as error:
        raise RuntimeError(f"invalid {name}") from error
    if not isinstance(parsed, dict):
        raise RuntimeError(f"invalid {name}")
    return parsed


def _entered_states(api: StepFunctionsApi, *, execution_arn: str) -> set[str]:
    names: set[str] = set()
    token: str | None = None
    while True:
        kwargs: dict[str, object] = {"executionArn": execution_arn, "maxResults": 1000}
        if token is not None:
            kwargs["nextToken"] = token
        response = api.get_execution_history(**kwargs)
        if not isinstance(response, dict) or not isinstance(response.get("events"), list):
            raise RuntimeError("invalid STOP execution history")
        for event in response["events"]:
            if not isinstance(event, dict) or event.get("type") != "TaskStateEntered":
                continue
            detail = event.get("stateEnteredEventDetails")
            if isinstance(detail, dict) and isinstance(detail.get("name"), str):
                names.add(cast(str, detail["name"]))
        raw_token = response.get("nextToken")
        if raw_token is None:
            return names
        if not isinstance(raw_token, str) or raw_token == token:
            raise RuntimeError("invalid STOP execution history pagination")
        token = raw_token


def _fresh_reconcile(api: LambdaApi, *, function_name: str) -> dict[str, object]:
    response = api.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=b'{"schema_version":1,"operation":"reconcile"}',
    )
    if not isinstance(response, dict) or response.get("FunctionError") is not None:
        raise RuntimeError("fresh Reconcile failed")
    payload = response.get("Payload")
    reader = getattr(payload, "read", None)
    raw = reader() if callable(reader) else payload
    if isinstance(raw, bytes):
        raw = raw.decode()
    return _json_object(raw, "Reconcile response")


def _required_string(item: dict[str, object], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"invalid Reconcile evidence: {name}")
    return value


def _verify_volume(api: Ec2Api, *, volume_id: str, instance_id: str, device: str) -> None:
    response = api.describe_volumes(VolumeIds=[volume_id])
    volumes = response.get("Volumes") if isinstance(response, dict) else None
    if not isinstance(volumes, list) or len(volumes) != 1 or not isinstance(volumes[0], dict):
        raise RuntimeError("Data EBS identity mismatch")
    volume = volumes[0]
    attachments = volume.get("Attachments")
    if (
        volume.get("VolumeId") != volume_id
        or volume.get("Encrypted") is not True
        or not isinstance(attachments, list)
        or len(attachments) != 1
        or not isinstance(attachments[0], dict)
        or attachments[0].get("InstanceId") != instance_id
        or attachments[0].get("Device") != device
        or attachments[0].get("State") != "attached"
        or attachments[0].get("DeleteOnTermination") is not False
    ):
        raise RuntimeError("Data EBS binding mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    config = load_configuration(root, args.stage)
    session = cast(Session, importlib.import_module("boto3").Session(profile_name=args.profile))
    prefix = config.project.resource_prefix
    stage = config.stage
    recover_failed_scheduled_stop(
        dynamodb=cast(DynamoApi, session.client("dynamodb", region_name=stage.aws_region)),
        step_functions=cast(
            StepFunctionsApi, session.client("stepfunctions", region_name=stage.aws_region)
        ),
        reconcile=cast(LambdaApi, session.client("lambda", region_name=stage.aws_region)),
        ec2=cast(Ec2Api, session.client("ec2", region_name=stage.aws_region)),
        operation_id=args.operation_id,
        operations_table=resource_name(prefix, args.stage, "operations"),
        locks_table=resource_name(prefix, args.stage, "locks"),
        system_state_table=resource_name(prefix, args.stage, "system-state"),
        intents_table=resource_name(prefix, args.stage, "auto-stop-intents"),
        reconcile_function=resource_name(prefix, args.stage, "reconcile"),
        system_id=config.project.system_id,
        game_id=config.project.initial_game_id,
        lock_name=stage.global_lock_name,
        data_volume_id=str(stage.host_runtime_value("target_host.existing_data_volume_id")),
        data_volume_device=str(stage.host_runtime_value("target_host.existing_data_volume_device")),
        now=datetime.now(UTC),
    )
    print(f"operation_id={args.operation_id} recovered=failed")


if __name__ == "__main__":
    main()
