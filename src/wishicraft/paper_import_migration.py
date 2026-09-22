"""Offline stopped-host Paper import support; no Game or source-world mutations."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import whitelist_policy
from wishicraft.config import load_configuration
from wishicraft.game_creation import REGISTRY_KEY
from wishicraft.heartbeat_game_migration import _package_context, _selected_data_source
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.operation import _decode_attribute

BASELINE = "e87994a35cd9e8d4463526b5dff7418510140142"
BUNDLE_PATH = "/var/tmp/wishicraft-paper-import-v1"


def prepare(
    root: Path,
    output: Path,
    *,
    receipt: dict[str, Any],
    inventory: dict[str, Any],
    host_config_bytes: bytes,
) -> dict[str, Any]:
    host_config = json.loads(host_config_bytes)
    deployed = json.loads(
        (root / "docs/evidence/create_terralith_production_2026-09-21.json").read_text()
    )
    expected_config_hash = next(
        e["sha256"]
        for e in deployed["migration"]["files"]
        if e["destination"] == "/etc/wishicraft/runtime-contract.json"
    )
    if hashlib.sha256(host_config_bytes).hexdigest() != expected_config_hash:
        raise ValueError("host config differs from recorded production predecessor")
    edge_path = root / "src/wishicraft/artifacts/paper-transition.json"
    edge = json.loads(edge_path.read_text())
    before, after = edge["predecessor"], edge["successor"]
    old_digest, new_digest = packages.digest(before), packages.digest(after)
    if packages.load() != after["packages"]:
        raise ValueError("catalog differs from reviewed complete successor")
    cfg = load_configuration(root, "dev")
    rendered = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(json.loads((root / "config/two-game-dev.json").read_text())),
        reset_policies=json.loads((root / "config/reset-dev.json").read_text()),
        packages=packages.load(),
    )
    if json.loads(rendered.manifest_json) != after or rendered.digest != new_digest:
        raise ValueError("configured runtime differs from reviewed complete successor")
    if not packages.compatible_config(old_digest, new_digest, before["packages"][1]):
        raise ValueError("unreviewed catalog transition")
    if inventory.get("LastEvaluatedKey") or set(inventory) != {"Items"}:
        raise ValueError("complete normalized registry inventory required")
    records: dict[str, dict[str, Any]] = {
        entry["game_id"]["S"]: {
            k: v["SS"] if k == "registered_ids" and set(v) == {"SS"} else _decode_attribute(v)
            for k, v in entry.items()
        }
        for entry in inventory["Items"]
    }
    if len(records) != len(inventory["Items"]):
        raise ValueError("duplicate registry record")
    registry = records[REGISTRY_KEY]
    if set(registry) != {"game_id", "registered_ids"}:
        raise ValueError("invalid registered Game index")
    dynamic = registry["registered_ids"]
    if not isinstance(dynamic, (set, list, tuple)) or not dynamic:
        raise ValueError("registered Games required")
    if len(set(dynamic)) != len(dynamic) or set(dynamic) & set(before["games"]):
        raise ValueError("duplicate registered Game identity")
    identities = set(before["games"]) | set(dynamic)
    allowed = (
        identities
        | {REGISTRY_KEY, whitelist_policy.COMMON}
        | {whitelist_policy.policy_key(g) for g in identities}
    )
    if not identities <= set(records) or set(records) - allowed:
        raise ValueError("unknown or missing registry record")
    whitelist_policy.from_item(
        next(i for i in inventory["Items"] if i["game_id"]["S"] == whitelist_policy.COMMON), None
    )
    for identity in identities:
        game = records[identity]
        if (
            game.get("schema_version") != 1
            or game.get("lifecycle_state") != "ACTIVE"
            or game.get("materialization_state") != "MATERIALIZED"
        ):
            raise ValueError("all existing Games must be active and materialized")
        selected = packages.registered(game, before, old_digest)
        if packages.registered(game, after, new_digest) != selected:
            raise ValueError("existing package identity changed")
        policy = next(
            (
                i
                for i in inventory["Items"]
                if i["game_id"]["S"] == whitelist_policy.policy_key(identity)
            ),
            None,
        )
        if policy is not None:
            whitelist_policy.from_item(policy, identity)
    target, stop = receipt.get("target", {}), receipt.get("stop", {})
    if (
        receipt.get("phase") != "stopped"
        or stop.get("save_confirmed") is not True
        or stop.get("removal_ready") is not True
        or target.get("config_digest") != old_digest
        or target.get("instance_id") != host_config.get("instance_id")
        or host_config.get("config_digest") != old_digest
        or list(host_config.get("games", [])) != before["games"]
        or host_config.get("game_creation") is not True
        or not isinstance(target.get("run_id"), str)
        or not target["run_id"]
    ):
        raise ValueError("exact completed stopped predecessor and host configuration required")
    game = records[target["game_id"]]
    source = _selected_data_source(game)
    if source != target["data_source"]:
        raise ValueError("stopped receipt path mismatch")
    package = packages.registered(game, before, old_digest)
    # Only this approved baseline supplies executable predecessors. Live hashes
    # are checked again by the unchanged installer before any replacement.
    changes: list[tuple[str, bytes, bytes | None, int]] = []
    for name, destination, prefix, mode in [
        ("game_package.py", "game_package.py", b"", 0o644),
        ("initial_game.py", "initial_game.py", b"", 0o644),
        ("targeted_runtime.py", "operation-v2", b"#!/usr/bin/env python3\n", 0o755),
    ]:
        path = "src/wishicraft/artifacts/" + name
        old = prefix + subprocess.check_output(["git", "show", BASELINE + ":" + path], cwd=root)
        new = prefix + (root / path).read_bytes()
        changes.append(("/usr/local/libexec/wishicraft/" + destination, new, old, mode))
    for name in ("world_import.py", "world_nbt.py"):
        changes.append(
            (
                "/usr/local/libexec/wishicraft/" + name,
                (root / "src/wishicraft/artifacts" / name).read_bytes(),
                None,
                0o644,
            )
        )
    previous_render = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(before["games"]),
        reset_policies=json.loads((root / "config/reset-dev.json").read_text()),
        packages=before["packages"],
    )
    if previous_render.digest != old_digest:
        raise ValueError("Paper predecessor renderer changed")
    changes.append(
        (
            "/etc/wishicraft/host-runtime/compose.yaml",
            rendered.compose_yaml.encode(),
            previous_render.compose_yaml.encode(),
            0o600,
        )
    )
    changes.append(
        (
            "/usr/local/libexec/wishicraft/paper-transition.json",
            edge_path.read_bytes(),
            None,
            0o644,
        )
    )
    changes.append(
        (
            "/etc/wishicraft/host-runtime/manifest.json",
            packages.canonical(after).encode(),
            packages.canonical(before).encode(),
            0o600,
        )
    )
    # Preserve every captured config field except the current runtime digest.
    new_config = {**host_config, "config_digest": new_digest}
    changes.append(
        (
            "/etc/wishicraft/runtime-contract.json",
            json.dumps(new_config, sort_keys=True).encode(),
            host_config_bytes,
            0o600,
        )
    )
    installer = (root / "src/wishicraft/artifacts/runtime_install.py").read_text()
    if installer.count('namespace != "two-game-v1"') != 1:
        raise ValueError("inactive installer namespace boundary changed")
    output.mkdir(mode=0o700, exist_ok=False)
    entries = []
    for index, (destination, new, predecessor, mode) in enumerate(changes):
        filename = f"{index}.artifact"
        (output / filename).write_bytes(new)
        entries.append(
            {
                "destination": destination,
                "source": filename,
                "mode": mode,
                "sha256": hashlib.sha256(new).hexdigest(),
                "predecessor": hashlib.sha256(predecessor).hexdigest()
                if predecessor is not None
                else None,
            }
        )
    plan = {
        "instance_id": target["instance_id"],
        "files": entries,
        "receipt_predecessor": receipt,
        "backup_namespace": "paper-import-v1",
        "package_environment": packages.projection(game["game_id"], package),
        "package_context": _package_context(game, package, source),
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = installer.replace("/var/tmp/wishicraft-targeted-runtime-v1", BUNDLE_PATH).replace(
        'namespace != "two-game-v1"', 'namespace != "paper-import-v1"'
    )
    (output / "install.py").write_text(installer)
    return {
        "old_digest": old_digest,
        "new_digest": new_digest,
        "plan": plan,
        "durable_record_updates": [],
        "registry_sha256": packages.digest(inventory),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "receipt", "inventory", "host-config"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                Path(__file__).resolve().parents[2],
                args.output,
                receipt=json.loads(args.receipt.read_text()),
                inventory=json.loads(args.inventory.read_text()),
                host_config_bytes=args.host_config.read_bytes(),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
