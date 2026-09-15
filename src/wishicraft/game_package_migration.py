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


def prepare_reader_fix(
    root: Path, output: Path, receipt: dict[str, Any], inventory: dict[str, Any]
) -> dict[str, Any]:
    """Same-manifest helper patch only; never lift the D-108 runtime cutover guard."""
    from wishicraft.artifacts import whitelist_policy
    from wishicraft.artifacts.game_package import registered
    from wishicraft.game_creation import REGISTRY_KEY
    from wishicraft.operation import _decode_attribute

    baseline = "0889609b0d398ee55cf8b752708ae03a80443f59"
    source = "src/wishicraft/artifacts/targeted_runtime.py"
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            baseline,
            "--",
            "config",
            "infrastructure/host_runtime",
            "src/wishicraft/artifacts",
            "src/wishicraft/host_runtime.py",
        ],
        cwd=root,
        text=True,
    ).splitlines()
    if changed != [source]:
        raise ValueError("reader-only release requires unchanged manifest/platform/package sources")
    cfg = load_configuration(root, "dev")
    games = tuple(json.loads((root / "config/two-game-dev.json").read_text()))
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
        packages=load(),
    )
    evidence = json.loads(
        (root / "docs/evidence/neoforge_package_production_2026-09-14.json").read_text()
    )["migration"]
    if rendered.digest != evidence["after_digest"] or inventory.get("LastEvaluatedKey"):
        raise ValueError("same runtime digest and complete registry required")
    records = {v["game_id"]["S"]: v for v in inventory["Items"]}
    if len(records) != len(inventory["Items"]):
        raise ValueError("duplicate registry item")
    registry = records[REGISTRY_KEY]
    if set(registry) != {"game_id", "registered_ids"} or set(registry["registered_ids"]) != {"SS"}:
        raise ValueError("invalid registry")
    dynamic = registry["registered_ids"]["SS"]
    if len(dynamic) != 1 or dynamic[0] in games:
        raise ValueError("reader patch requires one registered unmaterialized Game")
    all_games = {*games, *dynamic}
    allowed = (
        all_games
        | {REGISTRY_KEY, whitelist_policy.COMMON}
        | {whitelist_policy.policy_key(g) for g in all_games}
    )
    if set(records) - allowed or not all_games <= set(records):
        raise ValueError("unknown or missing Game record")
    whitelist_policy.from_item(records.get(whitelist_policy.COMMON, {}), None)
    for identity in all_games:
        game: dict[str, Any] = {k: _decode_attribute(v) for k, v in records[identity].items()}
        package = registered(game, json.loads(rendered.manifest_json), rendered.digest)
        if game["schema_version"] != 1 or game["lifecycle_state"] != "ACTIVE":
            raise ValueError("Game schema/lifecycle incompatible")
        if identity in dynamic:
            if (
                game["materialization_state"] != "UNMATERIALIZED"
                or game["world"]["generation"] != 1
                or package["loader"]["type"] != "neoforge"
            ):
                raise ValueError("registered Game must remain initial and unmaterialized")
        elif "creation" in game or game["materialization_state"] != "MATERIALIZED":
            raise ValueError("legacy Game incompatible")
        whitelist_policy.from_item(records.get(whitelist_policy.policy_key(identity), {}), identity)
    if (
        receipt.get("phase") != "stopped"
        or receipt["target"]["game_id"] not in games
        or receipt.get("stop", {}).get("save_confirmed") is not True
        or receipt["stop"].get("removal_ready") is not True
    ):
        raise ValueError("saved stopped predecessor required")
    previous = b"#!/usr/bin/env python3\n" + subprocess.check_output(
        ["git", "show", baseline + ":" + source], cwd=root
    )
    content = b"#!/usr/bin/env python3\n" + (root / source).read_bytes()
    destination = "/usr/local/libexec/wishicraft/operation-v2"
    entry = next(e for e in evidence["files"] if e["destination"] == destination)
    if hashlib.sha256(previous).hexdigest() != entry["sha256"]:
        raise ValueError("installed helper predecessor does not reproduce evidence")
    output.mkdir(mode=0o700, exist_ok=False)
    (output / "reader.artifact").write_bytes(content)
    plan = {
        "instance_id": receipt["target"]["instance_id"],
        "receipt_predecessor": receipt,
        "package_environment": projection(receipt["target"]["game_id"], load()[0]),
        "files": [
            {
                "destination": destination,
                "source": "reader.artifact",
                "mode": 0o755,
                "predecessor": entry["sha256"],
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    # Use the exact existing installer with a fresh caller-supplied BUNDLE path on the host.
    (output / "install.py").write_bytes(
        (root / "src/wishicraft/artifacts/runtime_install.py").read_bytes()
    )
    review = {
        "old_digest": rendered.digest,
        "new_digest": rendered.digest,
        "plan": plan,
        "durable_record_updates": [],
        "package_catalog_changed": False,
        "registry_sha256": hashlib.sha256(
            json.dumps(inventory["Items"], sort_keys=True).encode()
        ).hexdigest(),
    }
    (output / "review.json").write_text(json.dumps(review, sort_keys=True, indent=2))
    return review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--reader-fix", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            (prepare_reader_fix if args.reader_fix else prepare)(
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
