"""Fail-closed RuntimeHeartbeat derivation and DynamoDB persistence contract."""
# ruff: noqa: UP045 -- this module is deployed to Target AL2023 Python 3.9.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

HEARTBEAT_CADENCE_SECONDS = 60
HEARTBEAT_STALE_SECONDS = 300
HEARTBEAT_TTL_SECONDS = 86_400
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


class ProtocolState(str, Enum):  # noqa: UP042 - Target AL2023 Python 3.9 compatibility.
    READY = "ready"
    NOT_READY = "not-ready"
    UNKNOWN = "unknown"


class HeartbeatError(ValueError):
    """Heartbeat input cannot be trusted."""


@dataclass(frozen=True)
class RuntimeObservation:
    instance_id: str
    runtime_id: str
    boot_id: str
    active_game_id: Optional[str]
    protocol_state: ProtocolState
    player_count: Optional[int]
    observed_at: datetime
    run_id: Optional[str] = None
    process_id: Optional[str] = None


@dataclass(frozen=True)
class RuntimeHeartbeat:
    system_id: str
    schema_version: int
    instance_id: str
    runtime_id: str
    boot_id: str
    active_game_id: Optional[str]
    protocol_state: ProtocolState
    player_count: Optional[int]
    empty_since: Optional[datetime]
    observed_at: datetime
    expires_at: int
    run_id: Optional[str] = None
    process_id: Optional[str] = None

    def is_fresh(self, now: datetime) -> bool:
        return _utc(now) - self.observed_at <= timedelta(seconds=HEARTBEAT_STALE_SECONDS)


def derive_heartbeat(
    *,
    system_id: str,
    canonical_game_id: str,
    observation: RuntimeObservation,
    previous: Optional[RuntimeHeartbeat],
) -> RuntimeHeartbeat:
    """Derive one whole record; unknown identity/readiness clears zero continuity."""
    observed_at = _utc(observation.observed_at)
    _validate_identity(system_id, "system_id")
    _validate_identity(canonical_game_id, "canonical_game_id")
    _validate_identity(observation.runtime_id, "runtime_id")
    if not re.fullmatch(r"i-[0-9a-f]{17}", observation.instance_id):
        raise HeartbeatError("invalid instance_id")
    if not re.fullmatch(r"[0-9a-f-]{36}", observation.boot_id):
        raise HeartbeatError("invalid boot_id")
    if observation.active_game_id is not None:
        _validate_identity(observation.active_game_id, "active_game_id")
    count = observation.player_count
    if count is not None and (isinstance(count, bool) or count < 0):
        raise HeartbeatError("invalid player_count")
    trusted_ready = (
        observation.protocol_state is ProtocolState.READY
        and observation.active_game_id == canonical_game_id
    )
    if not trusted_ready:
        count = None
    empty_since: Optional[datetime] = None
    if trusted_ready and count == 0:
        if _continuous_zero(previous, observation, observed_at, canonical_game_id):
            assert previous is not None and previous.empty_since is not None
            empty_since = previous.empty_since
        else:
            empty_since = observed_at
    return RuntimeHeartbeat(
        system_id=system_id,
        schema_version=1,
        instance_id=observation.instance_id,
        runtime_id=observation.runtime_id,
        run_id=observation.run_id,
        process_id=observation.process_id,
        boot_id=observation.boot_id,
        active_game_id=observation.active_game_id,
        protocol_state=observation.protocol_state,
        player_count=count,
        empty_since=empty_since,
        observed_at=observed_at,
        expires_at=int(observed_at.timestamp()) + HEARTBEAT_TTL_SECONDS,
    )


def _continuous_zero(
    previous: Optional[RuntimeHeartbeat],
    observation: RuntimeObservation,
    observed_at: datetime,
    canonical_game_id: str,
) -> bool:
    if previous is None or observed_at <= previous.observed_at:
        return False
    gap = observed_at - previous.observed_at
    return (
        previous.instance_id == observation.instance_id
        and previous.runtime_id == observation.runtime_id
        and previous.run_id == observation.run_id
        and previous.process_id == observation.process_id
        and previous.boot_id == observation.boot_id
        and previous.active_game_id == canonical_game_id
        and previous.protocol_state is ProtocolState.READY
        and previous.player_count == 0
        and previous.empty_since is not None
        and gap <= timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    )


def assert_newer(heartbeat: RuntimeHeartbeat, previous: Optional[RuntimeHeartbeat]) -> None:
    if previous is not None and heartbeat.observed_at <= previous.observed_at:
        raise HeartbeatError("heartbeat is not newer")


def format_timestamp(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HeartbeatError("invalid timestamp") from error
    return _utc(parsed)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HeartbeatError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)  # noqa: UP017 - Target Python 3.9.


def _validate_identity(value: str, name: str) -> None:
    if _ID.fullmatch(value) is None:
        raise HeartbeatError(f"invalid {name}")
