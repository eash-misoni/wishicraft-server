"""Offline Reset bundle. Derives predecessors from applied D-097 evidence, not new code."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.reset_policy import policies
from wishicraft.runtime_catalog import RuntimeCatalog

BASELINE = "1267ed5912e027ca2e0b1e1a419df62865f6bfcd"


def prepare(root: Path, output: Path, policy: str) -> dict[str, Any]:
    evidence = json.loads((root / "docs/evidence/2026-09-12-two-game-production.json").read_text())
    old = evidence["local_artifacts"]["bundle_plan"]
    prior = {entry["destination"]: entry["sha256"] for entry in old["files"]}
    receipt = evidence["e2e"]["A-final-stop_receipt"]["receipt"]
    cfg = load_configuration(root, "dev")
    catalog = RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text())
    selected = policies(policy, catalog)
    old_config = {
        "schema_version": 2,
        "instance_id": receipt["target"]["instance_id"],
        "game_id": cfg.project.initial_game_id,
        "data_source": receipt["target"]["data_source"],
        "config_digest": old["config_digest"],
        "region": cfg.stage.aws_region,
        "system_id": cfg.project.system_id,
        "lock_name": cfg.stage.global_lock_name,
        "operations_table": "wc-dev-operations",
        "locks_table": "wc-dev-locks",
        "games": list(catalog.game_ids),
    }
    if (
        hashlib.sha256(json.dumps(old_config, sort_keys=True).encode()).hexdigest()
        != prior["/etc/wishicraft/runtime-contract.json"]
    ):
        raise ValueError("D-097 host configuration does not reproduce applied evidence")
    for source, destination, prefix in [
        (
            "src/wishicraft/artifacts/targeted_runtime.py",
            "/usr/local/libexec/wishicraft/operation-v2",
            b"#!/usr/bin/env python3\n",
        ),
        (
            "infrastructure/host_runtime/rcon-secret-v2.sh",
            "/usr/local/libexec/wishicraft/rcon-secret-v2",
            b"",
        ),
    ]:
        historical = subprocess.run(
            ["git", "show", BASELINE + ":" + source], cwd=root, check=True, capture_output=True
        ).stdout
        if hashlib.sha256(prefix + historical).hexdigest() != prior[destination]:
            raise ValueError("D-097 predecessor source does not reproduce applied evidence")
    rendered = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        targeted=True,
        games=catalog.game_ids,
        reset_policies=selected,
    )
    replacements = [
        ("/etc/wishicraft/host-runtime/compose.yaml", rendered.compose_yaml, 0o600),
        ("/etc/wishicraft/host-runtime/runtime.env", rendered.runtime_env, 0o600),
        ("/etc/wishicraft/host-runtime/manifest.json", rendered.manifest_json, 0o600),
        (
            "/etc/wishicraft/runtime-contract.json",
            json.dumps(
                {**old_config, "config_digest": rendered.digest, "reset_policies": selected},
                sort_keys=True,
            ),
            0o600,
        ),
        (
            "/usr/local/libexec/wishicraft/operation-v2",
            "#!/usr/bin/env python3\n"
            + (root / "src/wishicraft/artifacts/targeted_runtime.py").read_text(),
            0o755,
        ),
        (
            "/usr/local/libexec/wishicraft/rcon-secret-v2",
            (root / "infrastructure/host_runtime/rcon-secret-v2.sh").read_text(),
            0o755,
        ),
        (
            "/usr/local/libexec/wishicraft/reset_worlds.py",
            (root / "src/wishicraft/artifacts/reset_worlds.py").read_text(),
            0o644,
        ),
    ]
    output.mkdir(mode=0o700, exist_ok=False)
    entries = []
    for index, (destination, content, mode) in enumerate(replacements):
        name = f"{index}.artifact"
        (output / name).write_text(content)
        entries.append(
            {
                "destination": destination,
                "source": name,
                "mode": mode,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": prior.get(destination),
            }
        )
    plan = {
        "instance_id": old_config["instance_id"],
        "files": entries,
        "receipt_predecessor": receipt,
        "backup_namespace": "reset-v1",
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-reset-v1")
    )
    (output / "install.py").write_text(installer)
    (output / "reset-policies.json").write_text(json.dumps(selected, sort_keys=True))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    (output / "SHA256.json").write_text(json.dumps(hashes, sort_keys=True, indent=2))
    return {"baseline": BASELINE, "config_digest": rendered.digest, "plan": plan, "hashes": hashes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--policies", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(Path(__file__).resolve().parents[2], args.output, args.policies.read_text()),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
