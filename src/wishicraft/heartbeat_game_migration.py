"""Prepare the exact stopped-host heartbeat producer replacement offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wishicraft.artifacts.game_package import digest as package_digest
from wishicraft.artifacts.game_package import load as load_packages
from wishicraft.artifacts.game_package import projection, registered
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.operation import _decode_attribute
from wishicraft.world_reference import data_source

BASELINE = "57b1ecf6ecfa56a3ba5e879153a50054521d5aa5"
SOURCE = "src/wishicraft/runtime_heartbeat_producer.py"
DESTINATION = "/usr/local/libexec/wishicraft/runtime_heartbeat_producer.py"
RUNTIME_DIGEST = "64bbfff50b03dd0411ca496ada7060d93d015ecd81aab02ca14963dcb9f8073c"
PREDECESSOR = "831645ac04e0f8f0affe44dc51e071ec77ca0a2bdb2ddb251796c64b4bce229a"
BUNDLE_PATH = "/var/tmp/wishicraft-heartbeat-game-v2"


def _runtime(root: Path) -> tuple[dict[str, Any], str]:
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
        packages=load_packages(),
    )
    if rendered.digest != RUNTIME_DIGEST:
        raise ValueError("deployed runtime digest required")
    return json.loads(rendered.manifest_json), rendered.digest


def _game(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {"Item"}:
        raise ValueError("exact DynamoDB Game GetItem document required")
    item = document["Item"]
    if not isinstance(item, dict):
        raise ValueError("exact DynamoDB Game GetItem document required")
    return {key: _decode_attribute(value) for key, value in item.items()}


def _selected_data_source(game: dict[str, Any]) -> str:
    world = game.get("world")
    if not isinstance(world, dict) or type(world.get("generation")) is not int:
        raise ValueError("materialized Game world identity required")
    current = world.get("current_id")
    if current is not None and not isinstance(current, str):
        raise ValueError("materialized Game world identity required")
    return data_source(game["game_id"], current)


def _package_context(game: dict[str, Any], package: dict[str, Any], source: str) -> dict[str, Any]:
    artifacts = list(package["mods"])
    if package["loader"]["type"] == "neoforge":
        artifacts.append(package["loader"]["installer"])
    return {
        "game_id": game["game_id"],
        "data_source": source,
        "generation": game["world"]["generation"],
        "package": package,
        "package_digest": package_digest(package),
        "package_directory": projection(game["game_id"], package)["GAME_PACKAGE_DIRECTORY"],
        "artifacts": [
            {key: artifact[key] for key in ("filename", "size", "sha256")} for artifact in artifacts
        ],
    }


def prepare(
    root: Path,
    output: Path,
    receipt: dict[str, Any],
    game_document: dict[str, Any],
) -> dict[str, Any]:
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
    manifest, runtime_digest = _runtime(root)
    game = _game(game_document)
    if (
        game.get("game_id") != target["game_id"]
        or game.get("schema_version") != 1
        or game.get("lifecycle_state") != "ACTIVE"
        or game.get("materialization_state") != "MATERIALIZED"
    ):
        raise ValueError("exact active materialized Game required")
    source = _selected_data_source(game)
    if target["data_source"] != source:
        raise ValueError("stopped receipt Game path mismatch")
    package = registered(game, manifest, runtime_digest)
    package_env = projection(game["game_id"], package)
    context = _package_context(game, package, source)
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
        "backup_namespace": "heartbeat-game-v2",
        "package_environment": package_env,
        "package_context": context,
    }
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (root / "src/wishicraft/artifacts/runtime_install.py").read_text()
    if installer.count('namespace != "two-game-v1"') != 1:
        raise ValueError("inactive installer namespace boundary changed")
    installer = installer.replace("/var/tmp/wishicraft-targeted-runtime-v1", BUNDLE_PATH).replace(
        'namespace != "two-game-v1"', 'namespace != "heartbeat-game-v2"'
    )
    (output / "install.py").write_text(installer)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--game-record", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                Path(__file__).resolve().parents[2],
                args.output,
                json.loads(args.receipt.read_text()),
                json.loads(args.game_record.read_text()),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
