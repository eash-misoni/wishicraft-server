from __future__ import annotations

import hashlib
from pathlib import Path

from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "infrastructure" / "host_runtime"


def test_stop_artifact_saves_before_systemd_and_never_calls_ec2() -> None:
    script = (HOST / "stop-v1.sh").read_text(encoding="utf-8")
    save = "rcon-cli save-all flush"
    availability = "rcon-cli list"
    runtime_stop = 'systemctl stop "$HOST_RUNTIME_UNIT"'
    assert script.index(availability) < script.index(save)
    assert script.index(save) < script.index(runtime_stop)
    assert "stop-instances" not in script.lower()
    assert "MINECRAFT_SAVE_FAILED" in script
    assert "MINECRAFT_STOP_TIMEOUT" in script


def test_stop_artifact_does_not_accept_command_path_or_container_input() -> None:
    script = (HOST / "stop-v1.sh").read_text(encoding="utf-8")
    assert '[[ "$#" -eq 0 ]]' in script
    assert "docker compose" in script
    assert "--quiet minecraft" in script
    assert "RCON_PASSWORD" not in script


def test_secret_artifact_uses_ephemeral_file_and_fixed_parameter_allowlist() -> None:
    script = (HOST / "rcon-secret-v1.sh").read_text(encoding="utf-8")
    assert "RUNTIME_DIR=/run/wishicraft" in script
    assert "--with-decryption" in script
    assert "/wishicraft/(dev|prod)/secret/rcon-password" in script
    assert "chmod 0400" in script
    assert "RCON_PASSWORD=" not in script
    assert 'rm -f -- "$SECRET_PATH" "$CLI_ENV_PATH" "$CLI_YAML_PATH"' in script


def test_phase6_fixed_compose_and_runtime_env_match_canonical_renderer() -> None:
    configuration = load_configuration(ROOT, "dev")
    rendered = render_boot_time_artifacts(
        configuration.project,
        configuration.stage,
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name="/wishicraft/dev/secret/rcon-password",
    )
    assert (HOST / "phase6-compose.yaml").read_text(encoding="utf-8") == rendered.compose_yaml
    assert (HOST / "phase6-runtime.env").read_text(encoding="utf-8") == rendered.runtime_env


def test_upgrade_requires_approved_predecessors_and_installs_entrypoint_last() -> None:
    script = (HOST / "phase6_runtime_contract_upgrade.sh").read_text(encoding="utf-8")
    assert "COMPOSE_PREDECESSOR=c92fbb" in script
    assert "RUNTIME_ENV_PREDECESSOR=723b6e" in script
    assert "BROKEN_HOST_ENV_PREDECESSOR=62c9bd" in script
    assert "CONTAINER_ENV_PREDECESSOR=271ce8" in script
    assert "RUNTIME_ENV_PATH=/etc/wishicraft/host-runtime/runtime.env" in script
    assert 'replace_existing "$SOURCE_ROOT/phase2-real-data.env" "$HOST_ENV_PATH"' in script
    assert 'replace_existing "$SOURCE_ROOT/phase6-runtime.env" "$RUNTIME_ENV_PATH"' in script
    assert "OPERATION_PREDECESSOR=eb8ce7" in script
    assert "UNAPPROVED_PREDECESSOR" in script
    operation_install = 'replace_existing "$SOURCE_ROOT/operation-v1.sh"'
    assert script.index(operation_install) > script.index("phase6-runtime.env")
    assert "HOST_RUNTIME_ACTIVE" in script
    assert "CONTAINER_RUNNING" in script
    for filename in (
        "stop-v1.sh",
        "rcon-secret-v1.sh",
        "phase6-rcon.env",
        "phase6-compose.yaml",
        "phase6-runtime.env",
        "phase2-real-data.env",
        "operation-v1.sh",
    ):
        digest = hashlib.sha256((HOST / filename).read_bytes()).hexdigest()
        assert digest in script
