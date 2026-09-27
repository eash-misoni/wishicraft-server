"""Local release evidence boundary; never deployed with Lambda source assets.

Call save_evidence before persisting API responses, including ChangeSet contexts.
Compare original responses only in memory. Never log their repr or exceptions.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TextIO

REDACTED = "<environment value removed>"


def _variables(value: object) -> object:
    if not isinstance(value, Mapping):
        return REDACTED
    return {
        str(key): item
        if key == "DAILY_BACKUP_ENABLED" and isinstance(item, str) and item in ("0", "1")
        else REDACTED
        for key, item in value.items()
    }


def sanitize(value: object) -> object:
    """Return a value-removed copy, including recursively encoded JSON strings."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            if value.lstrip().startswith(("{", "[", '"')) and (
                "environment" in value.lower() or "variables" in value.lower()
            ):
                return REDACTED
            return value
        if isinstance(parsed, (dict, list, str)):
            cleaned = sanitize(parsed)
            # Immutable provenance JSON and policy strings must retain their bytes
            # when no environment value was removed.
            return value if cleaned == parsed else json.dumps(cleaned, ensure_ascii=False)
        return value
    if isinstance(value, Mapping):
        target = value.get("Target", value)
        path = str(target.get("Path", "")) if isinstance(target, Mapping) else ""
        environment_path = "/environment" in path.lower() or (
            isinstance(target, Mapping) and target.get("Name") == "Environment"
        )
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name in ("runtime_env", "runtime_env_sha256", "compose_yaml"):
                # Recovery provenance is verified in memory; its host environment
                # and Compose environment projection are not release evidence.
                result[name] = REDACTED
            elif name.lower() == "variables":
                result[name] = _variables(item)
            elif name == "Environment" or (
                name.lower() == "environment" and isinstance(item, Mapping) and "Variables" in item
            ):
                result[name] = (
                    {"Variables": _variables(item.get("Variables", {}))}
                    if isinstance(item, Mapping)
                    else REDACTED
                )
            elif environment_path and name in ("BeforeValue", "AfterValue"):
                result[name] = (
                    item
                    if path.endswith("/Variables/DAILY_BACKUP_ENABLED")
                    and isinstance(item, str)
                    and item in ("0", "1")
                    else REDACTED
                )
            else:
                result[name] = sanitize(item)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    # AWS datetimes/Decimals are handled without arbitrary object repr fallbacks.
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    raise TypeError("unsupported evidence type")


def save_evidence(path: Path, value: object) -> None:
    """Sanitize fully before opening a new file; do not overwrite prior evidence."""
    encoded = json.dumps(sanitize(value), ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def run_safely(action: Callable[[], None], errors: TextIO) -> int:
    """Collector entrypoint: exception messages/tracebacks can contain raw values."""
    try:
        action()
    except Exception as error:
        errors.write(f"Evidence collection stopped: {type(error).__name__}\n")
        return 1
    return 0
