"""Execute the stdin transport outside the checkout; no inherited module path."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from wishicraft.ssm_probe import _canonical_probe_command

RUNTIME = "/usr/local/libexec/wishicraft"


def test_stdin_transport_resolves_installed_module_only(tmp_path: Path) -> None:
    runtime = tmp_path / "libexec"
    runtime.mkdir()
    source = Path("src/wishicraft/artifacts/game_package.py")
    (runtime / "game_package.py").write_bytes(source.read_bytes())
    (runtime / "game-packages.json").write_bytes(
        source.with_name("game-packages.json").read_bytes()
    )
    elsewhere = tmp_path / "ssm-working-directory"
    elsewhere.mkdir()
    (elsewhere / "game_package.py").write_text("raise RuntimeError('wrong cwd module')")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "PYTHONPATH": str(elsewhere),
        "PYTHONUSERBASE": str(elsewhere),
    }
    # Only the absolute installed directory and diagnostic stdin payload are fixtures.
    # Shell/pipeline/interpreter flags are the actual production command generator.
    original = _canonical_probe_command()
    payload = "import json,game_package; print(json.dumps(game_package.load()[1]))"
    encoded = shlex.split(original)[2]
    command = original.replace(encoded, base64.b64encode(payload.encode()).decode()).replace(
        RUNTIME, shlex.quote(str(runtime))
    )
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    package = json.loads(result.stdout)
    assert package["minecraft_version"] == "1.21.1"
    assert package["loader"]["version"] == "21.1.219"
    assert not list(runtime.glob("__pycache__"))
    (runtime / "game_package.py").unlink()
    missing = subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert missing.returncode != 0 and "ModuleNotFoundError" in missing.stderr
    absent = subprocess.run(
        ["/bin/sh", "-c", command.replace(str(runtime), str(tmp_path / "absent"))],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert absent.returncode != 0 and not absent.stdout


@pytest.mark.parametrize("stdout", ["", "not-json", "{}", '{"minecraft":{"ready":true}}'])
def test_health_or_malformed_output_cannot_be_ready(stdout: str) -> None:
    from wishicraft.probe import ProbeContractError, parse_host_runtime_probe

    with pytest.raises(ProbeContractError):
        parse_host_runtime_probe(stdout, expected_instance_id="i-0123456789abcdef0")
