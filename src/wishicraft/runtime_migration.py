"""Offline, invocation-specific bundle for the proposed inactive-only cutover."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.naming import resource_name

BASELINE = "30b029295c3cd94d00fbfe1aacd0f60094d2f011"


def prepare(root: Path, output: Path, instance_id: str) -> None:
    if re.fullmatch(r"i-[0-9a-f]{17}", instance_id) is None:
        raise ValueError("invalid instance identity")
    for name in ("config/project.yaml", "config/stages/dev.yaml"):
        baseline = subprocess.run(
            ["git", "show", BASELINE + ":" + name],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if (root / name).read_text() != baseline:
            raise ValueError("configuration changed; predecessor review required")
    config = load_configuration(root, "dev")
    project, stage = config.project, config.stage

    # Installed hashes come from the Phase 6 upgrade evidence, not today's renderer.
    installed = {
        "compose.yaml": "df4db90566e6dc743414de2a680f647d5463eee3280e62d7c940e94d37e6e339",
        "runtime.env": "62c9bda48163ed1089e88f2d0bb52692372b003e225145a36512589ec6230dce",
    }
    new = render_boot_time_artifacts(
        project,
        stage,
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name="/wishicraft/dev/secret/rcon-password",
        targeted=True,
    )
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries: list[dict[str, object]] = []

    def add(
        destination: str,
        content: str,
        previous: str | None,
        mode: int,
        predecessor_digest: str | None = None,
    ) -> None:
        name = str(len(entries)) + ".artifact"
        (output / name).write_text(content)
        entries.append(
            {
                "destination": destination,
                "source": name,
                "mode": mode,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": predecessor_digest
                or (
                    hashlib.sha256(previous.encode()).hexdigest() if previous is not None else None
                ),
            }
        )

    def historic(path: str) -> str:
        return subprocess.run(
            ["git", "show", BASELINE + ":" + path],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def current(path: str) -> str:
        return (root / path).read_text()

    # First disable the public legacy write entrypoint. It is never called by v2.
    add(
        "/usr/local/libexec/wishicraft/operation-v1",
        "#!/bin/sh\necho 'TARGETED_RUNTIME_REQUIRED' >&2\nexit 64\n",
        historic("infrastructure/host_runtime/operation-v1.sh"),
        0o755,
    )
    for name, body, previous in [
        ("compose.yaml", new.compose_yaml, installed["compose.yaml"]),
        ("runtime.env", new.runtime_env, installed["runtime.env"]),
        ("manifest.json", new.manifest_json, None),
    ]:
        add("/etc/wishicraft/host-runtime/" + name, body, None, 0o600, previous)
    add(
        "/etc/systemd/system/wishicraft-host-runtime.service",
        current("infrastructure/host_runtime/wishicraft-targeted-runtime.service"),
        historic("infrastructure/host_runtime/wishicraft-host-runtime.service"),
        0o644,
    )
    for name, source, destination in [
        ("probe", "src/wishicraft/artifacts/host_runtime_probe.py", "host-runtime-probe.py"),
        ("heartbeat", "src/wishicraft/runtime_heartbeat.py", "runtime_heartbeat.py"),
        (
            "producer",
            "src/wishicraft/runtime_heartbeat_producer.py",
            "runtime_heartbeat_producer.py",
        ),
    ]:
        del name
        add(
            "/usr/local/libexec/wishicraft/" + destination,
            current(source),
            historic(source),
            0o755 if destination == "host-runtime-probe.py" else 0o644,
            # D-094 kept the installed Phase 8.1 v1.3 probe; v1.4 was CP-delivered only.
            "2d431e562cc2770bc33c8efc509fbb94414824a0e3967d5362a542b48fba69d8"
            if destination == "host-runtime-probe.py"
            else None,
        )
    settings = {
        "schema_version": 2,
        "instance_id": instance_id,
        "game_id": project.initial_game_id,
        "data_source": f"{stage.data_volume_mount_path}/games/{project.initial_game_id}/server",
        "config_digest": new.digest,
        "region": stage.aws_region,
        "system_id": project.system_id,
        "lock_name": stage.global_lock_name,
        "operations_table": resource_name(project.resource_prefix, stage.stage, "operations"),
        "locks_table": resource_name(project.resource_prefix, stage.stage, "locks"),
    }
    add("/etc/wishicraft/runtime-contract.json", json.dumps(settings, sort_keys=True), None, 0o600)
    add(
        "/usr/local/libexec/wishicraft/operation-v2",
        "#!/usr/bin/env python3\n" + current("src/wishicraft/artifacts/targeted_runtime.py"),
        None,
        0o755,
    )
    (output / "install.json").write_text(
        json.dumps({"instance_id": instance_id, "files": entries}, indent=2)
    )
    (output / "install.py").write_text(current("src/wishicraft/artifacts/runtime_install.py"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(Path.cwd(), args.output, args.instance_id)


if __name__ == "__main__":
    main()
