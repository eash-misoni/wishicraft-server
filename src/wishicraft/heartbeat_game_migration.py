"""Prepare the exact stopped-host heartbeat producer replacement offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

BASELINE = "57b1ecf6ecfa56a3ba5e879153a50054521d5aa5"
SOURCE = "src/wishicraft/runtime_heartbeat_producer.py"
DESTINATION = "/usr/local/libexec/wishicraft/runtime_heartbeat_producer.py"
RUNTIME_DIGEST = "64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c"
PREDECESSOR = "831645ac04e0f8f0affe44dc51e071ec77ca0a2bdb2ddb251796c64b4bce229a"
BUNDLE_PATH = "/var/tmp/wishicraft-heartbeat-game-v1"


def prepare(root: Path, output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    target = receipt.get("target")
    proof = receipt.get("stop")
    if (
        receipt.get("phase") != "stopped"
        or not isinstance(target, dict)
        or not isinstance(proof, dict)
        or proof.get("save_confirmed") is not True
        or proof.get("removal_ready") is not True
        or target.get("config_digest") != RUNTIME_DIGEST
        or not isinstance(target.get("instance_id"), str)
        or not isinstance(target.get("game_id"), str)
        or not isinstance(target.get("run_id"), str)
        or not isinstance(target.get("data_source"), str)
    ):
        raise ValueError("exact completed stopped receipt required")
    old = subprocess.check_output(["git", "show", BASELINE + ":" + SOURCE], cwd=root)
    if hashlib.sha256(old).hexdigest() != PREDECESSOR:
        raise ValueError("installed producer does not match reviewed predecessor")
    new = (root / SOURCE).read_bytes()
    output.mkdir(mode=0o700, exist_ok=False)
    (output / "0.artifact").write_bytes(new)
    plan = {
        "instance_id": target["instance_id"],
        "files": [
            {
                "destination": DESTINATION,
                "source": "0.artifact",
                "mode": 0o644,
                "sha256": hashlib.sha256(new).hexdigest(),
                "predecessor": PREDECESSOR,
            }
        ],
        "receipt_predecessor": receipt,
        "backup_namespace": "heartbeat-game-v1",
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (root / "src/wishicraft/artifacts/runtime_install.py").read_text()
    if installer.count('namespace != "two-game-v1"') != 1:
        raise ValueError("inactive installer namespace boundary changed")
    installer = installer.replace("/var/tmp/wishicraft-targeted-runtime-v1", BUNDLE_PATH).replace(
        'namespace != "two-game-v1"', 'namespace != "heartbeat-game-v1"'
    )
    (output / "install.py").write_text(installer)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                Path(__file__).resolve().parents[2],
                args.output,
                json.loads(args.receipt.read_text()),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
