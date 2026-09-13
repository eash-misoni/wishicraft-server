"""Explicit read projection of saved Control Plane facts; no observation or repair calls."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

from wishicraft.operation import OperationStatus, OperationType
from wishicraft.progress_display import MILESTONE_STEPS
from wishicraft.runtime_heartbeat import HEARTBEAT_STALE_SECONDS, parse_timestamp
from wishicraft.status import Ec2State, HostRuntimeState
from wishicraft.system_state import DesiredState, Health, utc_timestamp


class Reader(Protocol):
    def get_item(self, **kwargs: Any) -> dict[str, Any]: ...


def decode(value: object) -> Any:
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("malformed DynamoDB attribute")
    kind, raw = next(iter(value.items()))
    if kind in {"S", "BOOL"}:
        return raw
    if kind == "NULL" and raw is True:
        return None
    if kind == "N":
        from decimal import Decimal

        number = Decimal(raw)
        return int(number) if number == number.to_integral_value() else float(number)
    if kind == "L" and isinstance(raw, list):
        return [decode(item) for item in raw]
    if kind == "M" and isinstance(raw, dict):
        return {key: decode(item) for key, item in raw.items()}
    raise ValueError("unsupported DynamoDB attribute")


def stamp(value: object) -> str | None:
    try:
        return utc_timestamp(parse_timestamp(str(value)))
    except ValueError:
        return None


def freshness(value: object, now: datetime, seconds: int) -> str:
    parsed = stamp(value)
    if parsed is None:
        return "unknown"
    age = (now - parse_timestamp(parsed)).total_seconds()
    return "fresh" if 0 <= age <= seconds else ("stale" if age > seconds else "unknown")


def enum_value(value: object, allowed: list[str], default: str = "unknown") -> str:
    return str(value) if value in allowed else default


def mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def display_name(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 100
        or re.search(r"arn:|\b\d{12,20}\b|\b(?:i|vol|snap|op|game)-|[/<>\x00-\x1f]", value)
    ):
        return None
    return value


class StatusReader:
    def __init__(
        self, api: Reader, tables: dict[str, str], system_id: str, observation_seconds: int
    ) -> None:
        self.api, self.tables, self.system_id = api, tables, system_id
        self.observation_seconds = observation_seconds

    def read(self, now: datetime) -> dict[str, Any]:
        failures: set[str] = set()

        def get(source: str, key: str, value: str) -> dict[str, Any]:
            try:
                response = self.api.get_item(
                    TableName=self.tables[source], Key={key: {"S": value}}, ConsistentRead=True
                )
                item = response.get("Item")
                if not isinstance(item, dict):
                    failures.add(source)
                    return {}
                return {k: decode(v) for k, v in item.items()}
            except Exception:
                failures.add(source)
                return {}

        state = get("system", "system_id", self.system_id)
        heartbeat = get("heartbeat", "system_id", self.system_id)
        observation = mapping(state.get("observation"))
        selected = state.get("desired_game_id")
        observed = observation.get("observed_active_game_id")
        games = {
            game_id: get("games", "game_id", game_id)
            for game_id in {selected, observed}
            if isinstance(game_id, str) and game_id
        }
        operation_id = state.get("current_operation_id")
        operation = (
            get("operation", "operation_id", operation_id)
            if isinstance(operation_id, str) and operation_id
            else None
        )
        # Independent consistent GetItem calls are not a snapshot. Detect a concurrent change.
        again = get("system", "system_id", self.system_id)
        if state != again:
            failures.add("concurrent_change")
        return project(state, heartbeat, games, operation, failures, now, self.observation_seconds)


def project(
    state: dict[str, Any],
    heartbeat: dict[str, Any],
    games: dict[str, dict[str, Any]],
    operation: dict[str, Any] | None,
    failures: set[str],
    now: datetime,
    observation_seconds: int = 600,
) -> dict[str, Any]:
    failures = set(failures)
    obs = mapping(state.get("observation"))
    execution = mapping(obs.get("execution"))
    target = mapping(execution.get("target"))
    selected, observed = state.get("desired_game_id"), obs.get("observed_active_game_id")
    observed_at = stamp(state.get("observed_at"))
    observation_freshness = freshness(observed_at, now, observation_seconds)
    fresh = observation_freshness == "fresh" and "concurrent_change" not in failures
    desired_at = stamp(state.get("desired_updated_at"))
    if desired_at is not None and observed_at is not None and desired_at > observed_at:
        fresh = False
        failures.add("observation_precedes_desired")
    host = enum_value(obs.get("ec2_state"), [v.value for v in Ec2State])
    desired = enum_value(state.get("desired_state"), [v.value for v in DesiredState])
    transitioning = bool(state.get("current_operation_id"))
    stopped = fresh and host in {"stopped", "terminated"} and not transitioning
    hb_freshness = freshness(heartbeat.get("observed_at"), now, HEARTBEAT_STALE_SECONDS)
    matching = all(
        isinstance(a, str) and a and a == b
        for a, b in (
            (heartbeat.get("instance_id"), state.get("target_instance_id")),
            (heartbeat.get("active_game_id"), observed),
            (heartbeat.get("run_id"), target.get("run_id")),
            (heartbeat.get("process_id"), execution.get("process_id")),
        )
    )
    hb_usable = (
        fresh
        and host == "running"
        and not transitioning
        and matching
        and hb_freshness == "fresh"
        and execution.get("phase") == "running"
    )
    protocol = (
        enum_value(heartbeat.get("protocol_state"), ["ready", "not-ready", "unknown"])
        if hb_usable
        else ("not_expected" if stopped else "unknown")
    )
    if protocol == "unknown" and not stopped:
        failures.add("protocol_unknown")
    if host == "unknown" or desired == "unknown":
        failures.add("state_unknown")
    count = heartbeat.get("player_count")
    known = hb_usable and protocol == "ready" and type(count) is int and count >= 0
    if not known and not stopped:
        failures.add("players_unknown")
    if stopped:
        failures.discard("heartbeat")  # An absent/old heartbeat is expected on a stopped host.
    elif not hb_usable:
        failures.add("heartbeat_unavailable")
    if not fresh:
        failures.add("observation_unavailable")
    if state.get("observation_errors") or not isinstance(state.get("observation_errors"), list):
        failures.add("observation_unknown")
    mismatch = (
        selected != observed if isinstance(selected, str) and isinstance(observed, str) else None
    )

    def game(value: object) -> dict[str, Any]:
        name = display_name(games.get(str(value), {}).get("display_name"))
        if isinstance(value, str) and name is None:
            failures.add("game_unavailable")
        return {"name": name, "state": "known" if name else "unknown"}

    selected_game, observed_game = game(selected), game(observed)
    current = None
    if transitioning:
        if not operation:
            failures.add("operation_unavailable")
        else:
            status = enum_value(operation.get("status"), [v.value for v in OperationStatus])
            step = operation.get("current_step")
            current = {
                "type": enum_value(
                    operation.get("operation_type"), [v.value for v in OperationType]
                ),
                "status": status,
                "progress": MILESTONE_STEPS.get(str(step), "Progress not recorded"),
                "updated_at": stamp(operation.get("updated_at")),
                "freshness": freshness(operation.get("updated_at"), now, observation_seconds),
                "terminal": status not in {"PENDING", "RUNNING", "unknown"},
                "milestones": [
                    {"label": label, "at": stamp(operation.get(f"progress_{key.lower()}_at"))}
                    for key, label in MILESTONE_STEPS.items()
                    if stamp(operation.get(f"progress_{key.lower()}_at")) is not None
                ],
            }
    discrepancy = state.get("discrepancies")
    health = enum_value(state.get("health"), [v.value for v in Health], "UNKNOWN")
    return {
        "schema_version": 1,
        "generated_at": utc_timestamp(now),
        "poll_after_seconds": 60,
        "quality": "partial" if failures else "complete",
        "issues": sorted(failures),
        "desired_state": desired,
        "selected_game": selected_game,
        "observed_game": observed_game,
        "observed_state": host,
        "runtime_state": enum_value(
            obs.get("host_runtime_state"), [v.value for v in HostRuntimeState]
        ),
        "health": health if not failures and not transitioning else "UNKNOWN",
        "last_observed_health": health,
        "game_mismatch": mismatch,
        "discrepancy": bool(discrepancy) if isinstance(discrepancy, list) else None,
        "observation": {"at": observed_at, "freshness": observation_freshness},
        "heartbeat": {
            "at": stamp(heartbeat.get("observed_at")),
            "freshness": hb_freshness,
            "expected": False if stopped else (True if fresh and host == "running" else None),
            "identity_matches": bool(matching),
        },
        "protocol": protocol,
        "players": {
            "state": "not_expected" if stopped else ("known" if known else "unknown"),
            "count": count if known else None,
            "at": stamp(heartbeat.get("observed_at")) if known else None,
        },
        "current_operation": current,
        "operation_pending": transitioning,
    }
