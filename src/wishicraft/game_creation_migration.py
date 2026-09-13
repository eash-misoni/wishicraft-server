"""Build a reviewed inactive-host upgrade; never connects to AWS or changes Game data."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wishicraft.config import load_configuration

BASELINE = "c124525"


def prepare(root: Path, output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    evidence = json.loads((root / "docs/evidence/2026-09-12-reset-production.json").read_text())
    prior = {entry["destination"]: entry["sha256"] for entry in evidence["bundle"]["plan"]["files"]}
    cfg = load_configuration(root, "dev")
    target = receipt["target"]
    if (
        receipt.get("phase") != "stopped"
        or receipt.get("stop", {}).get("save_confirmed") is not True
        or receipt.get("stop", {}).get("removal_ready") is not True
        or target["instance_id"] != evidence["bundle"]["plan"]["instance_id"]
        or target["config_digest"] != evidence["bundle"]["config_digest"]
    ):
        raise ValueError("verified current stopped receipt required")
    legacy = json.loads((root / "config/two-game-dev.json").read_text())
    policies = json.loads((root / "config/reset-dev.json").read_text())
    config = {
        "schema_version": 2,
        "instance_id": target["instance_id"],
        "game_id": cfg.project.initial_game_id,
        "data_source": f"/srv/minecraft/games/{cfg.project.initial_game_id}/server",
        "config_digest": target["config_digest"],
        "region": cfg.stage.aws_region,
        "system_id": cfg.project.system_id,
        "lock_name": cfg.stage.global_lock_name,
        "operations_table": "wc-dev-operations",
        "locks_table": "wc-dev-locks",
        "games": legacy,
        "reset_policies": policies,
    }
    destination = "/etc/wishicraft/runtime-contract.json"
    if (
        hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        != prior[destination]
    ):
        raise ValueError("applied runtime configuration does not reproduce evidence")
    predecessor = subprocess.run(
        ["git", "show", BASELINE + ":src/wishicraft/artifacts/targeted_runtime.py"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    if (
        hashlib.sha256(b"#!/usr/bin/env python3\n" + predecessor).hexdigest()
        != prior["/usr/local/libexec/wishicraft/operation-v2"]
    ):
        raise ValueError("applied wrapper differs from source predecessor")
    config.update(
        game_creation=True,
        games_table="wc-dev-games",
        initial_whitelist=[
            {
                "uuid": cfg.project.initial_minecraft_profile_uuid_hyphenated,
                "name": cfg.project.initial_minecraft_profile_name,
            }
        ],
    )
    changes = [
        (destination, json.dumps(config, sort_keys=True), 0o600),
        (
            "/usr/local/libexec/wishicraft/operation-v2",
            "#!/usr/bin/env python3\n"
            + (root / "src/wishicraft/artifacts/targeted_runtime.py").read_text(),
            0o755,
        ),
        (
            "/usr/local/libexec/wishicraft/initial_game.py",
            (root / "src/wishicraft/artifacts/initial_game.py").read_text(),
            0o644,
        ),
    ]
    output.mkdir(mode=0o700, exist_ok=False)
    entries = []
    for index, (path, content, mode) in enumerate(changes):
        source = f"{index}.artifact"
        (output / source).write_text(content)
        entries.append(
            {
                "destination": path,
                "source": source,
                "mode": mode,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": prior.get(path),
            }
        )
    plan = {
        "instance_id": target["instance_id"],
        "files": entries,
        "receipt_predecessor": receipt,
        "backup_namespace": "game-creation-v1",
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-game-creation-v1")
        .replace('namespace != "two-game-v1"', 'namespace != "game-creation-v1"')
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
