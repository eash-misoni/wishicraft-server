"""Offline memory-only cutover for the deployed legacy A/B registry (D-108)."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from wishicraft.config import StageConfig, load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.whitelist_migration import host_bundle

BASELINE = "03cde07"


def validate_registry(inventory: dict[str, Any], games: tuple[str, ...]) -> None:
    """No record writes: dynamic creation/owner provenance requires a separate migration."""
    if inventory.get("LastEvaluatedKey"):
        raise ValueError("incomplete registry inventory")
    expected = set(games)
    allowed = (
        expected
        | {"policy-whitelist-common-v1"}
        | {"policy-whitelist-game-v1:" + game for game in games}
    )
    seen = set()
    for record in inventory["Items"]:
        key = record["game_id"]["S"]
        if key in seen or key not in allowed or "creation" in record:
            raise ValueError("D-105 or unknown registry requires separate migration review")
        seen.add(key)
        if key in expected and (
            record.get("lifecycle_state") != {"S": "ACTIVE"}
            or record.get("materialization_state") != {"S": "MATERIALIZED"}
        ):
            raise ValueError("legacy Game must be active and materialized")
    if seen != allowed:
        raise ValueError("incomplete legacy Game/whitelist inventory")


def prepare(
    root: Path, output: Path, receipt: dict[str, Any], inventory: dict[str, Any]
) -> dict[str, Any]:
    cfg = load_configuration(root, "dev")
    games = tuple(json.loads((root / "config/two-game-dev.json").read_text()))
    validate_registry(inventory, games)
    baseline = yaml.safe_load(
        subprocess.check_output(["git", "show", BASELINE + ":config/stages/dev.yaml"], cwd=root)
    )
    candidate = copy.deepcopy(cfg.stage.values)
    runtime = candidate["host_runtime"]
    assert isinstance(runtime, dict)
    runtime["memory"] = baseline["host_runtime"]["memory"]
    if candidate != baseline:
        raise ValueError("memory-only release requires unchanged stage configuration")
    for name in ("project.yaml", "two-game-dev.json", "reset-dev.json", "secrets.example.yaml"):
        if (root / "config" / name).read_bytes() != subprocess.check_output(
            ["git", "show", BASELINE + ":config/" + name], cwd=root
        ):
            raise ValueError("memory-only release requires unchanged runtime identity/policy")
    policies = json.loads((root / "config/reset-dev.json").read_text())

    def render(stage: StageConfig) -> Any:
        return render_boot_time_artifacts(
            cfg.project,
            stage,
            observed_uid=993,
            observed_gid=993,
            targeted=True,
            enable_rcon=True,
            rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
            games=games,
            reset_policies=policies,
        )

    old, new = render(StageConfig("dev", baseline)), render(cfg.stage)
    if old.digest == new.digest:
        raise ValueError("memory configuration is unchanged")
    if receipt["target"]["config_digest"] != old.digest:
        raise ValueError("stopped receipt must reference the applied predecessor digest")
    output.mkdir(mode=0o700, exist_ok=False)
    reference = host_bundle(root, output / "whitelist-reference", receipt)
    previous_config = (output / "whitelist-reference/0.artifact").read_text()
    config = json.loads(previous_config)
    evidence = json.loads(
        (root / "docs/evidence/whitelist_management_production_2026-09-14.json").read_text()
    )
    expected = {e["destination"]: e["sha256"] for e in evidence["host"]["files"]}
    reset_evidence = json.loads(
        (root / "docs/evidence/2026-09-12-reset-production.json").read_text()
    )
    expected.update(
        {
            e["destination"]: e["sha256"]
            for e in reset_evidence["bundle"]["plan"]["files"]
            if e["destination"].startswith("/etc/wishicraft/host-runtime/")
        }
    )
    config["config_digest"] = new.digest
    changes = [
        ("/etc/wishicraft/host-runtime/compose.yaml", old.compose_yaml, new.compose_yaml),
        ("/etc/wishicraft/host-runtime/runtime.env", old.runtime_env, new.runtime_env),
        ("/etc/wishicraft/host-runtime/manifest.json", old.manifest_json, new.manifest_json),
        (
            "/etc/wishicraft/runtime-contract.json",
            previous_config,
            json.dumps(config, sort_keys=True),
        ),
    ]
    entries = []
    for index, (destination, previous, content) in enumerate(changes):
        predecessor = hashlib.sha256(previous.encode()).hexdigest()
        if expected[destination] != predecessor:
            raise ValueError("applied artifact does not reproduce production evidence")
        source = f"{index}.artifact"
        (output / source).write_text(content)
        (output / f"{index}.predecessor").write_text(previous)
        entries.append(
            {
                "destination": destination,
                "source": source,
                "mode": 0o600,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": predecessor,
            }
        )
    plan = {**reference, "files": entries, "backup_namespace": "memory-v1"}
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-memory-v1")
        .replace('namespace != "two-game-v1"', 'namespace != "memory-v1"')
    )
    (output / "install.py").write_text(installer)
    result = {
        "old_digest": old.digest,
        "new_digest": new.digest,
        "plan": plan,
        "registry_sha256": hashlib.sha256(
            json.dumps(inventory["Items"], sort_keys=True).encode()
        ).hexdigest(),
        "durable_record_updates": [],
    }
    (output / "review.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(
        Path.cwd(),
        args.output,
        json.loads(args.receipt.read_text()),
        json.loads(args.inventory.read_text()),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
