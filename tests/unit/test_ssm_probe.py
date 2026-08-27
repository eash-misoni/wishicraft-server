"""Tests for the fixed SSM Run Command Host Runtime probe adapter."""

from __future__ import annotations

import ast
import base64
import inspect
from pathlib import Path

import pytest

from wishicraft.ssm_probe import (
    CanonicalHostRuntimeProbeRunner,
    ProbeRunError,
    _canonical_probe_command,
)

TARGET_INSTANCE_ID = "i-04fc0629dc4ea466e"
COMMAND_ID = "12345678-1234-1234-1234-123456789abc"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeSsmCommands:
    def __init__(self, invocations: list[object]) -> None:
        self.invocations = invocations
        self.send_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def send_command(self, **kwargs: object) -> object:
        self.send_calls.append(kwargs)
        return {"Command": {"CommandId": COMMAND_ID}}

    def get_command_invocation(self, **kwargs: object) -> object:
        self.get_calls.append(kwargs)
        if self.invocations:
            return self.invocations.pop(0)
        return {"Status": "InProgress"}


def runner(ssm: FakeSsmCommands, clock: FakeClock | None = None) -> CanonicalHostRuntimeProbeRunner:
    active_clock = clock or FakeClock()
    return CanonicalHostRuntimeProbeRunner(
        ssm=ssm,
        timeout_seconds=3,
        poll_interval_seconds=1,
        monotonic=active_clock.monotonic,
        sleep=active_clock.sleep,
    )


def test_fixed_probe_send_poll_and_success() -> None:
    ssm = FakeSsmCommands(
        [
            {"Status": "Pending"},
            {
                "Status": "Success",
                "ResponseCode": 0,
                "StandardOutputContent": '{"schema_version":1}',
                "StandardErrorContent": "",
            },
        ]
    )

    result = runner(ssm).run_probe(instance_id=TARGET_INSTANCE_ID)

    assert result.command_id == COMMAND_ID
    assert result.exit_code == 0
    assert result.stdout == '{"schema_version":1}'
    assert len(ssm.send_calls) == 1
    send = ssm.send_calls[0]
    assert send["DocumentName"] == "AWS-RunShellScript"
    assert send["InstanceIds"] == [TARGET_INSTANCE_ID]
    assert send["TimeoutSeconds"] == 3
    assert send["MaxConcurrency"] == "1"
    assert send["MaxErrors"] == "0"


def test_run_command_timeout_is_normalized() -> None:
    clock = FakeClock()
    ssm = FakeSsmCommands([])

    with pytest.raises(ProbeRunError, match="SSM_PROBE_TIMEOUT"):
        runner(ssm, clock).run_probe(instance_id=TARGET_INSTANCE_ID)

    assert clock.now == 3


@pytest.mark.parametrize(
    "invocation",
    [
        {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardOutputContent": "{}",
            "StandardErrorContent": "diagnostic",
        },
        {
            "Status": "Success",
            "ResponseCode": 1,
            "StandardOutputContent": "{}",
            "StandardErrorContent": "diagnostic",
        },
    ],
)
def test_command_failure_is_normalized_without_diagnostic(invocation: object) -> None:
    with pytest.raises(ProbeRunError, match="SSM_PROBE_COMMAND_FAILED") as error:
        runner(FakeSsmCommands([invocation])).run_probe(instance_id=TARGET_INSTANCE_ID)

    assert "diagnostic" not in str(error.value)


def test_probe_operation_has_no_arbitrary_command_parameter() -> None:
    signature = inspect.signature(CanonicalHostRuntimeProbeRunner.run_probe)

    assert list(signature.parameters) == ["self", "instance_id"]


def test_canonical_command_contains_exact_packaged_probe() -> None:
    command = _canonical_probe_command()
    encoded = command.split("'")[3]
    decoded = base64.b64decode(encoded).decode()
    source = Path("src/wishicraft/artifacts/host_runtime_probe.py").read_text(encoding="utf-8")

    assert decoded == source
    assert command.endswith("| base64 --decode | python3 -")


def test_probe_artifact_contains_no_mutation_or_minecraft_file_access() -> None:
    source = Path("src/wishicraft/artifacts/host_runtime_probe.py").read_text(encoding="utf-8")
    forbidden = (
        'run("systemctl", "start"',
        'run("systemctl", "stop"',
        'run("systemctl", "restart"',
        'run("docker", "start"',
        'run("docker", "stop"',
        'run("docker", "restart"',
        'run("docker", "pull"',
        'run("docker", "compose"',
        'run("mount"',
        'run("umount"',
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "server.properties",
        "/world",
        "rcon",
        "get-parameter",
    )

    assert all(token not in source.lower() for token in forbidden)
    assert '"docker",\n        "exec"' in source
    assert '"mc-monitor",\n        "status"' in source
    assert 'MINECRAFT_HOST = "localhost"' in source
    assert "MINECRAFT_PORT = 25565" in source


def test_probe_artifact_supports_target_python_3_9_syntax() -> None:
    source = Path("src/wishicraft/artifacts/host_runtime_probe.py").read_text(encoding="utf-8")

    ast.parse(source, feature_version=(3, 9))
