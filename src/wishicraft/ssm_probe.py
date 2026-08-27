"""Fixed SSM Run Command transport for the canonical Host Runtime probe."""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from typing import Protocol, cast

INSTANCE_ID_PATTERN = re.compile(r"^i-[0-9a-f]{17}$")
COMMAND_ID_PATTERN = re.compile(r"^[0-9a-f-]{36}$")
PENDING_STATUSES = {"Pending", "InProgress", "Delayed"}
FAILURE_STATUSES = {"Cancelled", "Cancelling", "TimedOut", "Failed"}


class SsmCommandApi(Protocol):
    """Narrow AWS SDK boundary for one fixed SSM operation."""

    def send_command(self, **kwargs: object) -> object: ...

    def get_command_invocation(self, **kwargs: object) -> object: ...


class ProbeRunError(RuntimeError):
    """Normalized SSM transport failure without AWS diagnostic detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProbeRunResult:
    command_id: str
    exit_code: int
    stdout: str
    stderr: str


class CanonicalHostRuntimeProbeRunner:
    """Run only the repository-packaged read-only Host Runtime probe."""

    def __init__(
        self,
        *,
        ssm: SsmCommandApi,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("probe timeout must be between 1 and 120 seconds")
        if poll_interval_seconds <= 0:
            raise ValueError("probe poll interval must be positive")
        self._ssm = ssm
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._monotonic = monotonic
        self._sleep = sleep

    def run_probe(self, *, instance_id: str) -> ProbeRunResult:
        """Send, poll, and return the fixed probe result for one validated target."""
        if INSTANCE_ID_PATTERN.fullmatch(instance_id) is None:
            raise ValueError("invalid target EC2 instance ID")
        command = _canonical_probe_command()
        try:
            response = self._ssm.send_command(
                DocumentName="AWS-RunShellScript",
                InstanceIds=[instance_id],
                Comment="Wishicraft canonical Host Runtime read-only probe v1",
                TimeoutSeconds=self._timeout_seconds,
                MaxConcurrency="1",
                MaxErrors="0",
                Parameters={
                    "commands": [command],
                    "executionTimeout": [str(min(45, self._timeout_seconds))],
                },
            )
        except Exception as exc:  # noqa: BLE001 - normalize the AWS boundary.
            raise ProbeRunError("SSM_SEND_COMMAND_FAILED") from exc
        command_id = _command_id(response)
        if command_id is None:
            raise ProbeRunError("SSM_SEND_COMMAND_SCHEMA_INVALID")

        deadline = self._monotonic() + self._timeout_seconds
        while self._monotonic() < deadline:
            try:
                invocation = self._ssm.get_command_invocation(
                    CommandId=command_id, InstanceId=instance_id
                )
            except Exception as exc:  # noqa: BLE001 - transient absence is identified by code.
                if _aws_error_code(exc) == "InvocationDoesNotExist":
                    self._sleep(self._poll_interval_seconds)
                    continue
                raise ProbeRunError("SSM_GET_INVOCATION_FAILED") from exc
            terminal = _parse_invocation(invocation)
            if terminal is None:
                self._sleep(self._poll_interval_seconds)
                continue
            status, exit_code, stdout, stderr = terminal
            if status != "Success" or exit_code != 0:
                raise ProbeRunError("SSM_PROBE_COMMAND_FAILED")
            return ProbeRunResult(
                command_id=command_id,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        raise ProbeRunError("SSM_PROBE_TIMEOUT")


def _canonical_probe_command() -> str:
    source = (
        files("wishicraft")
        .joinpath("artifacts", "host_runtime_probe.py")
        .read_text(encoding="utf-8")
    )
    encoded = base64.b64encode(source.encode()).decode("ascii")
    return f"printf '%s' '{encoded}' | base64 --decode | python3 -"


def _command_id(response: object) -> str | None:
    if not isinstance(response, dict):
        return None
    command = response.get("Command")
    if not isinstance(command, dict):
        return None
    command_id = command.get("CommandId")
    if not isinstance(command_id, str) or COMMAND_ID_PATTERN.fullmatch(command_id) is None:
        return None
    return command_id


def _parse_invocation(response: object) -> tuple[str, int, str, str] | None:
    if not isinstance(response, dict):
        raise ProbeRunError("SSM_INVOCATION_SCHEMA_INVALID")
    status = response.get("Status")
    if not isinstance(status, str):
        raise ProbeRunError("SSM_INVOCATION_SCHEMA_INVALID")
    if status in PENDING_STATUSES:
        return None
    if status not in FAILURE_STATUSES | {"Success"}:
        raise ProbeRunError("SSM_INVOCATION_SCHEMA_INVALID")
    exit_code = response.get("ResponseCode")
    stdout = response.get("StandardOutputContent")
    stderr = response.get("StandardErrorContent")
    if (
        not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        raise ProbeRunError("SSM_INVOCATION_SCHEMA_INVALID")
    return status, exit_code, stdout, stderr


def _aws_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    raw_error = response.get("Error")
    if not isinstance(raw_error, dict):
        return None
    code = cast(dict[object, object], raw_error).get("Code")
    return code if isinstance(code, str) else None
