"""Canonical current SystemState and monotonic DynamoDB persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class DesiredState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


class Health(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class SystemState:
    system_id: str
    environment: str
    game_id: str
    desired_state: DesiredState
    target_instance_id: str | None
    observation: dict[str, object]
    discrepancies: tuple[str, ...]
    health: Health
    observation_errors: tuple[str, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.system_id or not self.environment:
            raise ValueError("SystemState identity must be non-empty")
        if re.fullmatch(r"game-[a-z0-9]+(?:-[a-z0-9]+)*", self.game_id) is None:
            raise ValueError("invalid SystemState game identity")
        utc_timestamp(self.observed_at)
        _validate_safe_value(self.observation)
        if not all(isinstance(value, str) and value for value in self.discrepancies):
            raise ValueError("invalid SystemState discrepancy")
        if not all(isinstance(value, str) and value for value in self.observation_errors):
            raise ValueError("invalid SystemState observation error")

    def to_item(self) -> dict[str, object]:
        return {
            "system_id": self.system_id,
            "schema_version": 1,
            "environment": self.environment,
            "game_id": self.game_id,
            "desired_state": self.desired_state.value,
            "target_instance_id": self.target_instance_id,
            "observation": self.observation,
            "discrepancies": list(self.discrepancies),
            "health": self.health.value,
            "observation_errors": list(self.observation_errors),
            "observed_at": utc_timestamp(self.observed_at),
        }


class DynamoApi(Protocol):
    def get_item(self, **kwargs: object) -> object: ...
    def update_item(self, **kwargs: object) -> object: ...


class SystemStateRepository:
    def __init__(self, api: DynamoApi, *, table_name: str, system_id: str) -> None:
        self._api, self._table, self._system_id = api, table_name, system_id

    def desired_state(self) -> DesiredState:
        response = self._api.get_item(
            TableName=self._table,
            Key={"system_id": {"S": self._system_id}},
            ProjectionExpression="desired_state",
            ConsistentRead=True,
        )
        if not isinstance(response, dict) or response.get("Item") is None:
            return DesiredState.STOPPED
        item = response.get("Item")
        if not isinstance(item, dict):
            raise ValueError("malformed SystemState item")
        raw = item.get("desired_state")
        if not isinstance(raw, dict) or not isinstance(raw.get("S"), str):
            raise ValueError("malformed desired state")
        return DesiredState(raw["S"])

    def save(self, state: SystemState) -> None:
        if state.system_id != self._system_id:
            raise ValueError("SystemState repository identity mismatch")
        item = state.to_item()
        initialize_only = ("schema_version", "environment", "game_id", "desired_state")
        observed_fields = (
            "target_instance_id",
            "observation",
            "discrepancies",
            "health",
            "observation_errors",
            "observed_at",
        )
        fields = initialize_only + observed_fields
        names = {f"#{key}": key for key in fields}
        values = {f":{key}": _to_attribute(item[key]) for key in fields}
        initializers = [f"#{key} = if_not_exists(#{key}, :{key})" for key in initialize_only]
        observations = [f"#{key} = :{key}" for key in observed_fields]
        assignments = ", ".join(initializers + observations)
        self._api.update_item(
            TableName=self._table,
            Key={"system_id": {"S": state.system_id}},
            UpdateExpression=f"SET {assignments}",
            ConditionExpression=(
                "attribute_not_exists(#observed_at) OR #observed_at < :observed_at"
            ),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )


def _to_attribute(value: object) -> dict[str, object]:
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, list):
        return {"L": [_to_attribute(item) for item in value]}
    if isinstance(value, dict):
        return {"M": _to_attribute_map(value)}
    raise TypeError("unsupported SystemState value")


def _to_attribute_map(value: dict[str, object]) -> dict[str, object]:
    return {key: _to_attribute(item) for key, item in value.items()}


def _validate_safe_value(value: object) -> None:
    forbidden = {"secret", "password", "credential", "token", "stderr", "motd", "players"}
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_safe_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("invalid SystemState observation field")
            lowered = key.lower()
            if any(part in lowered for part in forbidden):
                raise ValueError("unsafe raw observation field")
            _validate_safe_value(item)
        return
    raise ValueError("unsupported SystemState observation value")
