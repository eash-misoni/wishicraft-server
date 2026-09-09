"""One-shot Target Runtime heartbeat producer using the fixed host probe and AWS CLI."""
# ruff: noqa: UP045 -- this module is deployed to Target AL2023 Python 3.9.

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from wishicraft.runtime_heartbeat import (
    HeartbeatError,
    ProtocolState,
    RuntimeHeartbeat,
    RuntimeObservation,
    assert_newer,
    derive_heartbeat,
    format_timestamp,
    parse_timestamp,
)

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
PROBE_PATH = "/usr/local/libexec/wishicraft/host-runtime-probe.py"


class ProducerError(RuntimeError):
    pass


def run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "AWS_MAX_ATTEMPTS": "3", "AWS_RETRY_MODE": "standard"}
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProducerError("COMMAND_FAILED") from error


def observe(*, now: datetime) -> RuntimeObservation:
    boot_id = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    probe = run(["python3", PROBE_PATH])
    if probe.returncode != 0:
        raise ProducerError("PROBE_FAILED")
    try:
        document = json.loads(probe.stdout)
        identity = document["identity"]
        active_game = document["active_game"]
        minecraft = document["minecraft"]
        protocol = minecraft["protocol"]
        instance_id = identity["instance_id"]
        runtime_id = identity["runtime_id"]
        active_game_id = (
            active_game["game_id"]
            if active_game.get("state") == "observed"
            and active_game.get("binding_consistency") == "consistent"
            else None
        )
        raw_state = minecraft["protocol_state"]
        try:
            protocol_state = ProtocolState(raw_state)
        except ValueError:
            protocol_state = ProtocolState.UNKNOWN
        player_count = (
            protocol.get("player_count") if protocol_state is ProtocolState.READY else None
        )
        errors = document["errors"]
        if not isinstance(errors, list) or errors:
            protocol_state = ProtocolState.UNKNOWN
            player_count = None
        if not isinstance(instance_id, str) or not isinstance(runtime_id, str):
            raise ValueError
        if active_game_id is not None and not isinstance(active_game_id, str):
            raise ValueError
        if player_count is not None and (
            not isinstance(player_count, int) or isinstance(player_count, bool)
        ):
            player_count = None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProducerError("PROBE_SCHEMA_INVALID") from error
    return RuntimeObservation(
        instance_id=instance_id,
        runtime_id=runtime_id,
        boot_id=boot_id,
        active_game_id=active_game_id,
        protocol_state=protocol_state,
        player_count=player_count,
        observed_at=now,
    )


def load_previous(*, table: str, system_id: str, region: str) -> Optional[RuntimeHeartbeat]:
    response = run(
        [
            "aws",
            "dynamodb",
            "get-item",
            "--consistent-read",
            "--table-name",
            table,
            "--key",
            json.dumps({"system_id": {"S": system_id}}),
            "--region",
            region,
            "--output",
            "json",
        ]
    )
    if response.returncode != 0:
        raise ProducerError("HEARTBEAT_READ_FAILED")
    try:
        item = json.loads(response.stdout).get("Item")
        if item is None:
            return None
        return _decode(item)
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        HeartbeatError,
    ) as error:
        raise ProducerError("HEARTBEAT_READ_INVALID") from error


def save(
    heartbeat: RuntimeHeartbeat,
    *,
    table: str,
    region: str,
    previous: Optional[RuntimeHeartbeat],
) -> bool:
    assert_newer(heartbeat, previous)
    expression = (
        "attribute_not_exists(system_id)" if previous is None else "observed_at = :previous"
    )
    values: dict[str, dict[str, str]] = {":new": {"S": format_timestamp(heartbeat.observed_at)}}
    if previous is not None:
        values[":previous"] = {"S": format_timestamp(previous.observed_at)}
    response = run(
        [
            "aws",
            "dynamodb",
            "put-item",
            "--table-name",
            table,
            "--item",
            json.dumps(_encode(heartbeat), separators=(",", ":")),
            "--condition-expression",
            f"({expression}) AND (attribute_not_exists(observed_at) OR observed_at < :new)",
            "--expression-attribute-values",
            json.dumps(values, separators=(",", ":")),
            "--region",
            region,
            "--output",
            "json",
        ]
    )
    if response.returncode == 0:
        return True
    if "ConditionalCheckFailedException" in response.stderr:
        return False
    raise ProducerError("HEARTBEAT_WRITE_FAILED")


def produce_once(*, now: Optional[datetime] = None) -> bool:
    table = _required("RUNTIME_HEARTBEATS_TABLE")
    system_id = _required("SYSTEM_ID")
    game_id = _required("GAME_ID")
    region = _required("AWS_REGION")
    previous = load_previous(table=table, system_id=system_id, region=region)
    current = derive_heartbeat(
        system_id=system_id,
        canonical_game_id=game_id,
        observation=observe(now=now or datetime.now(timezone.utc)),  # noqa: UP017
        previous=previous,
    )
    return save(current, table=table, region=region, previous=previous)


def _encode(value: RuntimeHeartbeat) -> dict[str, Any]:
    item: dict[str, Any] = {
        "system_id": {"S": value.system_id},
        "schema_version": {"N": "1"},
        "instance_id": {"S": value.instance_id},
        "runtime_id": {"S": value.runtime_id},
        "boot_id": {"S": value.boot_id},
        "protocol_state": {"S": value.protocol_state.value},
        "observed_at": {"S": format_timestamp(value.observed_at)},
        "expires_at": {"N": str(value.expires_at)},
    }
    item["active_game_id"] = {"S": value.active_game_id} if value.active_game_id else {"NULL": True}
    item["player_count"] = (
        {"N": str(value.player_count)} if value.player_count is not None else {"NULL": True}
    )
    item["empty_since"] = (
        {"S": format_timestamp(value.empty_since)} if value.empty_since else {"NULL": True}
    )
    return item


def _decode(item: dict[str, Any]) -> RuntimeHeartbeat:
    def text(name: str) -> str:
        value = item[name]["S"]
        if not isinstance(value, str):
            raise ValueError
        return value

    def optional_text(name: str) -> Optional[str]:
        return None if item[name].get("NULL") is True else text(name)

    def optional_count() -> Optional[int]:
        if item["player_count"].get("NULL") is True:
            return None
        return int(item["player_count"]["N"])

    empty = optional_text("empty_since")
    return RuntimeHeartbeat(
        system_id=text("system_id"),
        schema_version=int(item["schema_version"]["N"]),
        instance_id=text("instance_id"),
        runtime_id=text("runtime_id"),
        boot_id=text("boot_id"),
        active_game_id=optional_text("active_game_id"),
        protocol_state=ProtocolState(text("protocol_state")),
        player_count=optional_count(),
        empty_since=parse_timestamp(empty) if empty else None,
        observed_at=parse_timestamp(text("observed_at")),
        expires_at=int(item["expires_at"]["N"]),
    )


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ProducerError("CONFIG_MISSING")
    return value


def main() -> int:
    try:
        written = produce_once()
    except (HeartbeatError, ProducerError, OSError):
        print("heartbeat result=failed", flush=True)
        return 1
    print(f"heartbeat result={'written' if written else 'stale-conflict'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
