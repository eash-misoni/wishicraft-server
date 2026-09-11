"""Offline preparation only. Produces an exact predecessor bundle and registration document."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_catalog import RuntimeCatalog

BASELINE = "bb78deacc4daf1ad195887f337b3d4fa6a53c30f"


def prepare(root: Path, output: Path, declaration: dict[str, object]) -> dict[str, object]:
    configuration = load_configuration(root, "dev")
    catalog = RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text())
    evidence = json.loads(
        (root / "docs/evidence/2026-09-11-targeted-runtime-production.json").read_text()
    )["limited_stop_forward_continuation"]
    observed = evidence["host_forward"]["plan"]["forward_bundle_hashes"]
    receipt = evidence["rounds"][-1]["stopped_host"]["proof"]["receipt"]
    rendered = render_boot_time_artifacts(
        configuration.project,
        configuration.stage,
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name=configuration.secrets.rcon_password_parameter_name("dev"),
        targeted=True,
        games=catalog.game_ids,
    )
    # This mapping is the deployed D-096 bundle, not a predecessor rerender with new code.
    replacements = [
        ("/etc/wishicraft/host-runtime/compose.yaml", rendered.compose_yaml, "1.artifact", 0o600),
        ("/etc/wishicraft/host-runtime/runtime.env", rendered.runtime_env, "2.artifact", 0o600),
        ("/etc/wishicraft/host-runtime/manifest.json", rendered.manifest_json, "3.artifact", 0o600),
        (
            "/usr/local/libexec/wishicraft/runtime_heartbeat_producer.py",
            (root / "src/wishicraft/runtime_heartbeat_producer.py").read_text(),
            "7.artifact",
            0o644,
        ),
        (
            "/usr/local/libexec/wishicraft/operation-v2",
            "#!/usr/bin/env python3\n"
            + (root / "src/wishicraft/artifacts/targeted_runtime.py").read_text(),
            "9.artifact",
            0o755,
        ),
        (
            "/usr/local/libexec/wishicraft/rcon-secret-v2",
            (root / "infrastructure/host_runtime/rcon-secret-v2.sh").read_text(),
            None,
            0o755,
        ),
    ]
    old_config = {
        "schema_version": 2,
        "instance_id": receipt["target"]["instance_id"],
        "game_id": configuration.project.initial_game_id,
        "data_source": receipt["target"]["data_source"],
        "config_digest": receipt["target"]["config_digest"],
        "region": configuration.stage.aws_region,
        "system_id": configuration.project.system_id,
        "lock_name": configuration.stage.global_lock_name,
        "operations_table": "wc-dev-operations",
        "locks_table": "wc-dev-locks",
    }
    if (
        hashlib.sha256(json.dumps(old_config, sort_keys=True).encode()).hexdigest()
        != observed["8.artifact"]
    ):
        raise ValueError("deployed host configuration provenance mismatch")
    replacements.append(
        (
            "/etc/wishicraft/runtime-contract.json",
            json.dumps(
                {**old_config, "games": list(catalog.game_ids), "config_digest": rendered.digest},
                sort_keys=True,
            ),
            "8.artifact",
            0o600,
        )
    )
    # Verify historical source bytes for the artifacts that were actually delivered.
    for path, index in [
        ("src/wishicraft/artifacts/targeted_runtime.py", "9.artifact"),
        ("src/wishicraft/runtime_heartbeat_producer.py", "7.artifact"),
    ]:
        historical = subprocess.run(
            ["git", "show", BASELINE + ":" + path], cwd=root, check=True, capture_output=True
        ).stdout
        if index == "9.artifact":
            historical = b"#!/usr/bin/env python3\n" + historical
        if hashlib.sha256(historical).hexdigest() != observed[index]:
            raise ValueError("deployed artifact differs from historical source")
    output.mkdir(mode=0o700, exist_ok=False)
    files = []
    for bundle_index, (destination, content, prior, mode) in enumerate(replacements):
        name = f"{bundle_index}.artifact"
        (output / name).write_text(content)
        files.append(
            dict(
                destination=destination,
                source=name,
                mode=mode,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                predecessor=observed[prior] if prior else None,
            )
        )
    plan = dict(
        instance_id=old_config["instance_id"],
        files=files,
        receipt_predecessor=receipt,
        backup_namespace="two-game-v1",
    )
    (output / "install.json").write_text(json.dumps(plan, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-two-game-v1")
    )
    (output / "install.py").write_text(installer)
    materializer = (root / "src/wishicraft/artifacts/prepare_second_game.py").read_text()
    operation_hash = next(
        e["sha256"] for e in files if str(e["destination"]).endswith("/operation-v2")
    )
    materializer = materializer.replace(
        "from wishicraft.artifacts import targeted_runtime as host",
        "import importlib.machinery\nimport importlib.util\n"
        "_path = '/usr/local/libexec/wishicraft/operation-v2'\n"
        f"if hashlib.sha256(Path(_path).read_bytes()).hexdigest() != {operation_hash!r}:\n"
        "    raise ValueError('HOST_ARTIFACT_MISMATCH')\n"
        "_loader = importlib.machinery.SourceFileLoader('approved_host', _path)\n"
        "_spec = importlib.util.spec_from_loader(_loader.name, _loader)\n"
        "host = importlib.util.module_from_spec(_spec)\n_loader.exec_module(host)",
    )
    materializer += (
        "\nif __name__ == '__main__':\n"
        "    path = Path('/var/tmp/wishicraft-two-game-v1/second-game.json')\n"
        "    document = json.loads(path.read_text())\n"
        "    print(json.dumps(prepare(document['materialization']), sort_keys=True))\n"
    )
    (output / "prepare-game.py").write_text(materializer)
    (output / "second-game.json").write_text(json.dumps(declaration, sort_keys=True, indent=2))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    (output / "SHA256.json").write_text(json.dumps(hashes, sort_keys=True, indent=2))
    return {
        "baseline": BASELINE,
        "config_digest": rendered.digest,
        "files": files,
        "hashes": hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                Path(__file__).resolve().parents[2],
                args.output,
                json.loads(args.declaration.read_text()),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
