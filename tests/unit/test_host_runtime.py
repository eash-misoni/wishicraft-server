from __future__ import annotations

import copy
import hashlib
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from wishicraft.config import ConfigValidationError, StageConfig, load_configuration
from wishicraft.host_runtime import RenderedHostRuntime, render_boot_time_artifacts

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HOST_RUNTIME = REPOSITORY_ROOT / "infrastructure" / "host_runtime"
INTEGRATION_TEST = REPOSITORY_ROOT / "tests" / "integration" / "test_itzg_ownership.sh"
TARGET_VALIDATION = HOST_RUNTIME / "target_host_validation.sh"


def _render() -> RenderedHostRuntime:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    return render_boot_time_artifacts(
        configuration.project,
        configuration.stage,
        observed_uid=991,
        observed_gid=991,
    )


def _changed_stage(path: str, value: object) -> StageConfig:
    original = load_configuration(REPOSITORY_ROOT, "dev").stage
    values = copy.deepcopy(original.values)
    current: object = values
    parts = path.split(".")
    for part in parts[:-1]:
        assert isinstance(current, dict)
        current = current[part]
    assert isinstance(current, dict)
    current[parts[-1]] = value
    return StageConfig(stage="dev", values=values)


def test_renderer_is_deterministic_and_secret_free() -> None:
    first = _render()
    second = _render()

    assert first == second
    assert first.digest == hashlib.sha256(first.manifest_json.encode()).hexdigest()
    combined = first.compose_yaml + first.runtime_env + first.manifest_json
    assert "rcon-password" not in combined
    assert "RCON_PASSWORD" not in combined
    assert '"secret_material_included":false' in first.manifest_json


def test_renderer_writes_once_to_a_new_artifact_root(tmp_path: Path) -> None:
    rendered = _render()
    output = tmp_path / "render-v1"

    rendered.write_new(output)

    assert (output / "compose.yaml").read_text(encoding="utf-8") == rendered.compose_yaml
    assert (output / "render.sha256").read_text(encoding="utf-8") == f"{rendered.digest}\n"
    with pytest.raises(FileExistsError):
        rendered.write_new(output)


def test_rendered_compose_has_only_the_minecraft_public_port_and_safe_lifecycle() -> None:
    rendered = _render()
    compose = yaml.safe_load(rendered.compose_yaml)
    service = compose["services"]["minecraft"]

    assert service["image"].startswith("ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:")
    assert service["pull_policy"] == "never"
    assert service["restart"] == "no"
    assert service["mem_limit"] == "2816MiB"
    assert service["stop_grace_period"] == "150s"
    assert service["ports"] == ["25565:25565/tcp"]
    assert service["volumes"] == [
        {
            "type": "bind",
            "source": "/srv/minecraft/games/game-vanilla-main/server",
            "target": "/data",
        }
    ]
    assert service["env_file"] == ["runtime.env"]
    assert {
        "VERSION=26.2",
        "TYPE=VANILLA",
        "INIT_MEMORY=1G",
        "MAX_MEMORY=2G",
        "SKIP_CHOWN_DATA=true",
        "STOP_DURATION=120",
        "ENABLE_RCON=false",
    } <= set(rendered.runtime_env.splitlines())


def test_real_data_validation_renderer_can_omit_all_published_ports() -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    rendered = render_boot_time_artifacts(
        configuration.project,
        configuration.stage,
        observed_uid=993,
        observed_gid=993,
        publish_minecraft_port=False,
    )
    service = yaml.safe_load(rendered.compose_yaml)["services"]["minecraft"]

    assert "ports" not in service
    assert service["restart"] == "no"
    assert service["volumes"][0]["source"] == ("/srv/minecraft/games/game-vanilla-main/server")


@pytest.mark.parametrize("version", ("LATEST", "SNAPSHOT", "snapshot"))
def test_renderer_rejects_floating_minecraft_versions(version: str) -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    stage = _changed_stage("host_runtime.minecraft.version", version)

    with pytest.raises(ConfigValidationError, match="explicit non-floating"):
        render_boot_time_artifacts(configuration.project, stage, observed_uid=991, observed_gid=991)


def test_renderer_rejects_unpinned_image_and_insufficient_memory() -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    unpinned = _changed_stage("host_runtime.image.reference", "itzg/minecraft-server:latest")
    with pytest.raises(ConfigValidationError, match="release tag and sha256"):
        render_boot_time_artifacts(
            configuration.project, unpinned, observed_uid=991, observed_gid=991
        )

    unsafe_memory = _changed_stage("host_runtime.memory.container_limit", "2G")
    with pytest.raises(ConfigValidationError, match="greater than JVM"):
        render_boot_time_artifacts(
            configuration.project, unsafe_memory, observed_uid=991, observed_gid=991
        )


def test_renderer_rejects_timeout_scope_that_does_not_include_serial_work() -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    stage = _changed_stage("host_runtime.timeouts.host_runtime_wrapper", 269)

    with pytest.raises(ConfigValidationError, match="include save, systemd stop"):
        render_boot_time_artifacts(configuration.project, stage, observed_uid=991, observed_gid=991)


def test_host_runtime_artifacts_never_recursive_chown_or_enable_restart() -> None:
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(HOST_RUNTIME.iterdir())
    )

    assert "chown -R" not in artifact_text
    assert "restart: always" not in artifact_text
    assert "Restart=no" in artifact_text
    assert "systemctl enable wishicraft" not in artifact_text
    assert "systemctl enable minecraft" not in artifact_text
    assert "docker compose" in artifact_text


def test_mount_guard_failure_prevents_compose_operation(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "docker-called"
    mount_guard = bin_dir / "mount-guard"
    preflight = bin_dir / "preflight"
    systemctl = bin_dir / "systemctl"
    docker = bin_dir / "docker"
    mount_guard.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
    preflight.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    systemctl.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    for path in (mount_guard, preflight, systemctl, docker):
        path.chmod(0o755)

    result = subprocess.run(
        [str(HOST_RUNTIME / "start.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MOUNT_GUARD": str(mount_guard),
            "PREFLIGHT": str(preflight),
            "COMPOSE_FILE": str(tmp_path / "compose.yaml"),
            "MINECRAFT_PORT": "25565",
        },
        check=False,
    )

    assert result.returncode == 23
    assert not marker.exists()


def test_filesystem_preflight_rejects_symlink_without_modifying_it(tmp_path: Path) -> None:
    mount_path = tmp_path / "mount"
    game_directory = mount_path / "games" / "game-test" / "server"
    game_directory.mkdir(parents=True)
    target = game_directory / "world"
    target.mkdir()
    link = game_directory / "unexpected-link"
    link.symlink_to(target)
    mount_guard = tmp_path / "mount-guard"
    mount_guard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mount_guard.chmod(0o755)

    result = subprocess.run(
        [str(HOST_RUNTIME / "filesystem_preflight.sh")],
        env={
            **os.environ,
            "MOUNT_GUARD": str(mount_guard),
            "MOUNT_PATH": str(mount_path),
            "GAME_DIRECTORY": str(game_directory),
            "EXPECTED_UID": str(os.getuid()),
            "EXPECTED_GID": str(os.getgid()),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "symlink is not allowed" in result.stderr
    assert link.is_symlink()


def test_filesystem_preflight_accepts_empty_regular_files_without_stat_wording() -> None:
    script = (HOST_RUNTIME / "filesystem_preflight.sh").read_text(encoding="utf-8")

    assert '[[ -d "$path" || -f "$path" ]]' in script
    assert "file_type=" not in script


def test_real_data_service_environment_is_secret_free_and_fixed() -> None:
    environment = (HOST_RUNTIME / "phase2-real-data.env").read_text(encoding="utf-8")

    assert "phase2-real-data-migration.sh" in environment
    assert "GAME_DIRECTORY=/srv/minecraft/games/game-vanilla-main/server" in environment
    assert "EXPECTED_UID=993" in environment
    assert "EXPECTED_GID=993" in environment
    assert "PASSWORD" not in environment


def test_phase_one_interlock_precedes_compose_start() -> None:
    start = (HOST_RUNTIME / "start.sh").read_text(encoding="utf-8")
    assert start.index("systemctl is-active --quiet minecraft.service") < start.index(
        "docker compose"
    )
    assert start.index('ss -H -ltn "sport = :$MINECRAFT_PORT"') < start.index("docker compose")


def test_installer_uses_locked_al2023_repository_and_records_docker_version() -> None:
    installer = (HOST_RUNTIME / "docker_compose_install.sh").read_text(encoding="utf-8")

    assert 'dnf --releasever="$AL2023_RELEASE" install -y docker' in installer
    assert 'dnf --releasever="$AL2023_RELEASE" repoquery --arch=x86_64' in installer
    assert "EXPECTED_DOCKER_NEVRA" in installer
    assert "dnf upgrade" not in installer
    assert "docker_nevra=" in installer
    assert '"docker_nevra"' in installer
    assert "COMPOSE_SHA256" in installer


def test_target_platform_lock_is_complete_and_internally_consistent() -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    runtime = configuration.stage.values["host_runtime"]
    assert isinstance(runtime, dict)
    platform = runtime["platform"]

    assert platform == {
        "operating_system": "amazon-linux-2023",
        "al2023_release": "2023.12.20260803",
        "kernel_variant": "6.18",
        "ami_name": "al2023-ami-2023.12.20260803.3-kernel-6.18-x86_64",
        "ami_id": "ami-0b4d2909a55ed2c78",
        "architecture": "x86_64",
        "ami_owner_id": "137112412989",
        "ami_creation_date": "2026-08-03T17:39:23.000Z",
    }


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        ("host_runtime.platform.kernel_variant", "6.1", "AMI name must match"),
        ("host_runtime.platform.ami_id", "ami-unknown", "fixed AMI ID"),
        ("host_runtime.platform.ami_owner_id", "000000000000", "Amazon AL2023 owner"),
    ),
)
def test_renderer_rejects_inconsistent_target_platform_lock(
    path: str, value: str, message: str
) -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    stage = _changed_stage(path, value)

    with pytest.raises(ConfigValidationError, match=message):
        render_boot_time_artifacts(configuration.project, stage, observed_uid=991, observed_gid=991)


def test_static_shutdown_artifacts_match_provisional_timeout_contract() -> None:
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    timeouts = configuration.stage.values["host_runtime"]
    assert isinstance(timeouts, dict)
    timeouts = timeouts["timeouts"]
    assert timeouts == {
        "explicit_save": 60,
        "itzg_stop_duration": 120,
        "compose_stop_grace_period": 150,
        "systemd_stop": 180,
        "host_runtime_wrapper": 300,
        "ssm": 360,
        "control_plane_wait": 420,
    }
    assert "--timeout 150" in (HOST_RUNTIME / "stop.sh").read_text(encoding="utf-8")
    assert "TimeoutStopSec=180" in (HOST_RUNTIME / "wishicraft-host-runtime.service").read_text(
        encoding="utf-8"
    )


def test_docker_integration_contract_is_fixed_and_synthetic() -> None:
    script = INTEGRATION_TEST.read_text(encoding="utf-8")

    assert "2026.7.2-java25@sha256:6ec1110e" in script
    assert "--platform linux/amd64" in script
    assert "SKIP_CHOWN_DATA=true" in script
    assert "SETUP_ONLY=true" in script
    assert "ENABLE_RCON=false" in script
    assert "--entrypoint mc-monitor" in script
    assert 'mc_monitor_help_rc" == 0 || "$mc_monitor_help_rc" == 2' in script
    assert "PASS:mc-monitor-fixed-status-contract" in script
    assert "/srv/minecraft" not in script
    assert "RCON_PASSWORD" not in script
    assert "chown -R" not in script


def test_target_host_validation_is_root_only_synthetic_and_fail_closed() -> None:
    script = TARGET_VALIDATION.read_text(encoding="utf-8")

    assert "EXPECTED_DOCKER_NEVRA" in script
    assert "uid-993-already-used" in script
    assert "gid-993-already-used" in script
    assert "--uid 993 --gid 993" in script
    assert "SETUP_ONLY=true" in script
    assert 'restart: "no"' in script
    assert "mem_limit: 2816MiB" in script
    assert 'ENABLE_RCON: "false"' in script
    assert "systemctl restart docker" in script
    assert "docker compose" in script
    assert "/srv/minecraft" not in script
    assert "/dev/sdf" not in script
    assert "RCON_PASSWORD" not in script
    assert "chown -R" not in script
