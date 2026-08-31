"""Scheduled read-only observer for Phase 7 release alarms."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import boto3  # type: ignore[import-not-found]
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-not-found]

from wishicraft.monitoring import (
    MonitoringSnapshot,
    MonitoringThresholds,
    evaluate_monitoring_snapshot,
)

_DESERIALIZER = TypeDeserializer()


def handler(event: dict[str, Any], context: object) -> dict[str, object]:
    del event, context
    dynamodb = boto3.client("dynamodb")
    ec2 = boto3.client("ec2")
    cloudwatch = boto3.client("cloudwatch")
    now = datetime.now(UTC)

    state = _deserialize(
        dynamodb.get_item(
            TableName=os.environ["SYSTEM_STATE_TABLE"],
            Key={"system_id": {"S": os.environ["SYSTEM_ID"]}},
            ConsistentRead=True,
        ).get("Item")
    )
    if not state:
        raise RuntimeError("SystemState item is missing")
    lock = _deserialize(
        dynamodb.get_item(
            TableName=os.environ["LOCKS_TABLE"],
            Key={"lock_name": {"S": os.environ["GLOBAL_LOCK_NAME"]}},
            ConsistentRead=True,
        ).get("Item")
    )
    target_instance_id = _string(state, "target_instance_id")
    instances = ec2.describe_instances(InstanceIds=[target_instance_id])["Reservations"]
    instance = instances[0]["Instances"][0]
    observation = state.get("observation")
    if not isinstance(observation, dict):
        observation = {}

    snapshot = MonitoringSnapshot(
        desired_state=_string(state, "desired_state"),
        desired_updated_at=_timestamp(state.get("desired_updated_at")),
        observed_at=_timestamp(state.get("observed_at")),
        observed_ec2_state=_optional_string(observation.get("ec2_state")),
        runtime_ready=observation.get("runtime_ready") is True,
        health=_optional_string(state.get("health")),
        discrepancies=tuple(state.get("discrepancies", ())),
        actual_ec2_state=str(instance["State"]["Name"]),
        ec2_launch_time=instance.get("LaunchTime"),
        lock_lease_expires_at=_optional_int(lock.get("lease_expires_at")),
    )
    thresholds = MonitoringThresholds(
        ec2_running_seconds=int(os.environ["EC2_RUNNING_WARNING_SECONDS"]),
        desired_stopped_running_seconds=int(os.environ["DESIRED_STOPPED_RUNNING_WARNING_SECONDS"]),
        desired_running_not_ready_seconds=int(
            os.environ["DESIRED_RUNNING_NOT_READY_WARNING_SECONDS"]
        ),
        observation_freshness_seconds=int(os.environ["OBSERVATION_FRESHNESS_SECONDS"]),
    )
    metrics = evaluate_monitoring_snapshot(snapshot, now=now, thresholds=thresholds)
    cloudwatch.put_metric_data(
        Namespace=os.environ["METRIC_NAMESPACE"],
        MetricData=[
            {
                "MetricName": name,
                "Dimensions": [
                    {"Name": "Stage", "Value": os.environ["STAGE"]},
                    {"Name": "SystemId", "Value": os.environ["SYSTEM_ID"]},
                ],
                "Timestamp": now,
                "Value": value,
                "Unit": "Count",
            }
            for name, value in metrics.items()
        ],
    )
    return {"metric_count": len(metrics)}


def _deserialize(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: _DESERIALIZER.deserialize(value) for key, value in item.items()}


def _string(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"missing monitoring field: {key}")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
