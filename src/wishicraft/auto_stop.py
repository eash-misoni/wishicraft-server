"""D-093 unattended automatic STOP policy and durable intent model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from wishicraft.runtime_heartbeat import ProtocolState, RuntimeHeartbeat
from wishicraft.system_state import utc_timestamp

WARNING_LEAD = timedelta(minutes=5)
EVALUATOR_INTERVAL = timedelta(minutes=1)


class AutoStopIntentStatus(StrEnum):
    WARNING_PENDING = "WARNING_PENDING"
    WARNING_DELIVERED = "WARNING_DELIVERED"
    WARNING_FAILED = "WARNING_FAILED"
    CANCELLED = "CANCELLED"
    ADMISSION_ATTEMPTED = "ADMISSION_ATTEMPTED"
    STOP_REQUESTED = "STOP_REQUESTED"


@dataclass(frozen=True)
class AutoStopIntent:
    intent_id: str
    game_id: str
    boot_id: str
    empty_since: datetime
    idle_timeout_minutes: int
    warning_lead_minutes: int
    warning_delivery_id: str
    warning_delivery_state: str
    warning_delivered_at: datetime | None
    status: AutoStopIntentStatus
    created_at: datetime
    updated_at: datetime
    block_reason: str | None = None

    @property
    def warning_at(self) -> datetime:
        return self.empty_since + timedelta(
            minutes=self.idle_timeout_minutes - self.warning_lead_minutes
        )

    def stop_eligible_at(self) -> datetime | None:
        if self.warning_delivered_at is None:
            return None
        return max(
            self.empty_since + timedelta(minutes=self.idle_timeout_minutes),
            self.warning_delivered_at + timedelta(minutes=self.warning_lead_minutes),
        )


@dataclass(frozen=True)
class AutoStopCandidate:
    eligible: bool
    reason: str
    intent_id: str | None = None


def deterministic_intent_id(*, game_id: str, boot_id: str, empty_since: datetime) -> str:
    identity = f"{game_id}\n{boot_id}\n{utc_timestamp(empty_since)}"
    return "asi-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def deterministic_stop_idempotency_key(intent_id: str) -> str:
    return f"auto-stop:{intent_id}"


def evaluate_candidate(
    *,
    heartbeat: RuntimeHeartbeat | None,
    game_id: str,
    runtime_id: str,
    idle_timeout_minutes: int,
    desired_state: str,
    now: datetime,
) -> AutoStopCandidate:
    now = _utc(now)
    if desired_state != "RUNNING":
        return AutoStopCandidate(False, "DESIRED_NOT_RUNNING")
    if heartbeat is None or heartbeat.observed_at > now or not heartbeat.is_fresh(now):
        return AutoStopCandidate(False, "HEARTBEAT_STALE_OR_MISSING")
    if (
        heartbeat.active_game_id != game_id
        or heartbeat.runtime_id != runtime_id
        or heartbeat.protocol_state is not ProtocolState.READY
        or heartbeat.player_count != 0
        or heartbeat.empty_since is None
    ):
        return AutoStopCandidate(False, "HEARTBEAT_NOT_TRUSTED_EMPTY")
    if idle_timeout_minutes <= int(WARNING_LEAD.total_seconds() // 60):
        return AutoStopCandidate(False, "INVALID_IDLE_POLICY")
    warning_at = heartbeat.empty_since + timedelta(minutes=idle_timeout_minutes) - WARNING_LEAD
    if now < warning_at:
        return AutoStopCandidate(False, "BEFORE_WARNING_WINDOW")
    return AutoStopCandidate(
        True,
        "WARNING_ELIGIBLE",
        deterministic_intent_id(
            game_id=game_id, boot_id=heartbeat.boot_id, empty_since=heartbeat.empty_since
        ),
    )


def intent_matches_heartbeat(
    intent: AutoStopIntent,
    heartbeat: RuntimeHeartbeat | None,
    *,
    runtime_id: str,
    now: datetime,
) -> bool:
    return bool(
        heartbeat is not None
        and heartbeat.observed_at <= _utc(now)
        and heartbeat.is_fresh(_utc(now))
        and heartbeat.active_game_id == intent.game_id
        and heartbeat.runtime_id == runtime_id
        and heartbeat.boot_id == intent.boot_id
        and heartbeat.protocol_state is ProtocolState.READY
        and heartbeat.player_count == 0
        and heartbeat.empty_since == intent.empty_since
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
