"""Bounded display facts, not a workflow or a second execution history."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

# Each attribute is written at most once, atomically with its existing step/revision update.
# Flat optional attributes also work on historical records without a parent map migration.
MILESTONE_STEPS = {
    "RECONCILING": "State observation started",
    "DESIRED_RUNNING": "Running state requested",
    "EC2_STARTING": "Host start processing entered",
    "HOST_RUNTIME_STARTING": "Minecraft start processing entered",
    "ENDPOINT_CONVERGING": "Connection information processing entered",
    "DESIRED_STOPPED": "Stopped state requested",
    "HOST_RUNTIME_STOPPING": "Save and graceful stop processing entered",
    "EC2_STOPPING": "Host stop processing entered",
    "ENDPOINT_CLEANUP": "Connection cleanup processing entered",
    "SNAPSHOT_CREATING": "Backup creation and verification processing entered",
}


def safe_text(value: str, limit: int = 100) -> str:
    """Plain bounded text: no mentions, Markdown, links, controls or bidi overrides."""
    value = "".join(c if unicodedata.category(c)[0] != "C" else " " for c in value)
    value = " ".join(value.split())[:limit]
    return re.sub(r"([\\`*_{}\[\]()<>#+|~@:/])", r"\\\1", value)


def game_text(value: str | None) -> str:
    if value is None or re.fullmatch(r"game-[a-z0-9]+(?:-[a-z0-9]+)*", value) is None:
        return "not recorded"
    return safe_text(value, 100)


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("progress timestamp requires timezone")
    return parsed
