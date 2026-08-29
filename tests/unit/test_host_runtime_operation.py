from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/host_runtime/operation-v1.sh"


def test_operation_wrapper_rejects_missing_or_arbitrary_operation() -> None:
    for arguments in ([], ["SAVE"], ["START", "extra"]):
        result = subprocess.run(
            ["bash", str(SCRIPT), *arguments], capture_output=True, text=True, check=False
        )
        assert result.returncode == 64
        assert '"error_code":"INVALID_OPERATION"' in result.stdout
