"""Structured, secret-safe logging primitives for future components."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_SENSITIVE_MARKERS = ("secret", "token", "password", "credential")


def structured_log(
    *,
    operation_id: str | None,
    game_id: str | None,
    component: str,
    step: str,
    result: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Serialize a required structured event while redacting sensitive fields."""
    event: dict[str, Any] = {
        "operation_id": operation_id,
        "game_id": game_id,
        "component": component,
        "step": step,
        "result": result,
    }
    if extra:
        event["extra"] = _redact(extra)
    return json.dumps(event, ensure_ascii=False, sort_keys=True)


def _redact(value: Any, key: str = "") -> Any:
    if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            nested_key: _redact(nested_value, nested_key)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
