from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/host_runtime/operation-v1.sh"


def test_operation_wrapper_rejects_missing_or_arbitrary_operation() -> None:
    for arguments in ([], ["SAVE"], ["SHELL"], ["START", "extra"], ["STOP", "extra"]):
        result = subprocess.run(
            ["bash", str(SCRIPT), *arguments], capture_output=True, text=True, check=False
        )
        assert result.returncode == 64
        assert '"error_code":"INVALID_OPERATION"' in result.stdout


def test_operation_wrapper_exposes_only_fixed_start_and_stop_paths() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert '"$1" != "START" && "$1" != "STOP"' in script
    assert "/usr/local/libexec/wishicraft/stop-v1" in script
    assert "rcon-cli" not in script
    assert script.index('systemctl is-active --quiet "$HOST_RUNTIME_UNIT"') < script.index(
        "rcon-secret-v1 prepare"
    )
