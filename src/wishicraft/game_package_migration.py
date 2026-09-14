"""Offline package runtime bundle, reusing the inactive installer and D-108 predecessor."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wishicraft.artifacts.game_package import load, projection
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_memory_migration import prepare as memory_prepare

BASELINE = "25c3bcc5c5dc28c6b128a26702ed9f78e9ba7137"


def prepare(
    root: Path, output: Path, receipt: dict[str, Any], inventory: dict[str, Any]
) -> dict[str, Any]:
    for name in (
        "project.yaml",
        "stages/dev.yaml",
        "two-game-dev.json",
        "reset-dev.json",
        "secrets.example.yaml",
    ):
        previous_bytes = subprocess.check_output(
            ["git", "show", BASELINE + ":config/" + name], cwd=root
        )
        if (root / "config" / name).read_bytes() != previous_bytes:
            raise ValueError("package release requires unchanged stage/identity/memory/policy")
    output.mkdir(mode=0o700, exist_ok=False)
    reference = memory_prepare(root, output / "memory-reference", receipt, inventory)
    evidence = json.loads(
        (root / "docs/evidence/runtime_memory_capacity_production_2026-09-14.json").read_text()
    )
    if reference["new_digest"] != evidence["config_digest_after"]:
        raise ValueError("D-108 predecessor mismatch")
    cfg = load_configuration(root, "dev")
    games = tuple(json.loads((root / "config/two-game-dev.json").read_text()))
    packages = load()
    rendered = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=games,
        reset_policies=json.loads((root / "config/reset-dev.json").read_text()),
        packages=packages,
    )
    config = json.loads((output / "memory-reference/3.artifact").read_text())
    config["config_digest"] = rendered.digest
    new_text = [
        rendered.compose_yaml,
        rendered.runtime_env,
        rendered.manifest_json,
        json.dumps(config, sort_keys=True),
    ]
    changes: list[tuple[str, str, str | None, int]] = []
    for index, entry in enumerate(reference["plan"]["files"]):
        changes.append(
            (
                entry["destination"],
                new_text[index],
                (output / "memory-reference" / entry["source"]).read_text(),
                entry["mode"],
            )
        )
    for source, destination, prefix, mode in [
        ("targeted_runtime.py", "operation-v2", "#!/usr/bin/env python3\n", 0o755),
        ("reset_worlds.py", "reset_worlds.py", "", 0o644),
        ("host_runtime_probe.py", "host-runtime-probe.py", "", 0o755),
    ]:
        path = "src/wishicraft/artifacts/" + source
        previous_source = subprocess.check_output(
            ["git", "show", BASELINE + ":" + path], cwd=root
        ).decode()
        changes.append(
            (
                "/usr/local/libexec/wishicraft/" + destination,
                prefix + (root / path).read_text(),
                prefix + previous_source,
                mode,
            )
        )
    changes.append(
        (
            "/usr/local/libexec/wishicraft/game_package.py",
            (root / "src/wishicraft/artifacts/game_package.py").read_text(),
            None,
            0o644,
        )
    )
    entries = []
    for index, (destination, content, previous, mode) in enumerate(changes):
        source = str(index) + ".artifact"
        (output / source).write_text(content)
        if previous is not None:
            (output / (str(index) + ".predecessor")).write_text(previous)
        entries.append(
            {
                "destination": destination,
                "source": source,
                "mode": mode,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": None
                if previous is None
                else hashlib.sha256(previous.encode()).hexdigest(),
            }
        )
    plan = {
        **reference["plan"],
        "files": entries,
        "backup_namespace": "packages-v1",
        "package_environment": projection(receipt["target"]["game_id"], packages[0]),
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-packages-v1")
        .replace('namespace != "two-game-v1"', 'namespace != "packages-v1"')
    )
    (output / "install.py").write_text(installer)
    review = {
        "old_digest": reference["new_digest"],
        "new_digest": rendered.digest,
        "plan": plan,
        "durable_record_updates": [],
        "registry_sha256": reference["registry_sha256"],
    }
    (output / "review.json").write_text(json.dumps(review, sort_keys=True, indent=2))
    return review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                Path.cwd(),
                args.output,
                json.loads(args.receipt.read_text()),
                json.loads(args.inventory.read_text()),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
