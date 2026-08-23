"""Deterministic, secret-free Phase 2a Host Runtime artifact rendering."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from wishicraft.config import ConfigMapping, ConfigValidationError, ProjectConfig, StageConfig

_IMAGE_PATTERN: Final = re.compile(
    r"^(?P<repository>[a-z0-9./_-]+):"
    r"(?P<release>[0-9]{4}\.[0-9]+\.[0-9]+)-(?P<java>java[0-9]+)@"
    r"sha256:(?P<digest>[0-9a-f]{64})$"
)
_FLOATING_MINECRAFT_VERSIONS: Final = {"LATEST", "SNAPSHOT"}


@dataclass(frozen=True)
class RenderedHostRuntime:
    """Canonical non-secret artifacts and their shared digest."""

    compose_yaml: str
    runtime_env: str
    manifest_json: str
    digest: str

    def write_new(self, output_directory: Path) -> None:
        """Write into a new invocation-specific directory without replacing prior evidence."""
        output_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        artifacts = {
            "compose.yaml": self.compose_yaml,
            "runtime.env": self.runtime_env,
            "manifest.json": self.manifest_json,
            "render.sha256": f"{self.digest}\n",
        }
        for name, content in artifacts.items():
            path = output_directory / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)


def render_boot_time_artifacts(
    project: ProjectConfig,
    stage: StageConfig,
    *,
    observed_uid: int,
    observed_gid: int,
) -> RenderedHostRuntime:
    """Render one canonical boot-time configuration from validated sources of truth."""
    runtime = _runtime_mapping(stage.values)
    _validate_runtime_lock(runtime, observed_uid=observed_uid, observed_gid=observed_gid)

    image = _string(runtime, "image.reference")
    version = _string(runtime, "minecraft.version")
    server_type = _string(runtime, "minecraft.type")
    xms = _string(runtime, "memory.jvm_initial")
    xmx = _string(runtime, "memory.jvm_maximum")
    container_memory = _string(runtime, "memory.container_limit")
    stop_duration = _positive_int(runtime, "timeouts.itzg_stop_duration")
    compose_stop = _positive_int(runtime, "timeouts.compose_stop_grace_period")
    game_directory = f"{stage.data_volume_mount_path}/games/{project.initial_game_id}/server"

    environment = {
        "ENABLE_RCON": "false",
        "EULA": "TRUE",
        "GID": str(observed_gid),
        "INIT_MEMORY": xms,
        "MAX_MEMORY": xmx,
        "SKIP_CHOWN_DATA": "true",
        "STOP_DURATION": str(stop_duration),
        "TYPE": server_type,
        "UID": str(observed_uid),
        "VERSION": version,
    }
    compose = {
        "name": "wishicraft-host-runtime",
        "services": {
            "minecraft": {
                "image": image,
                "pull_policy": "never",
                "restart": "no",
                "mem_limit": container_memory,
                "stop_grace_period": f"{compose_stop}s",
                "env_file": ["runtime.env"],
                "ports": [f"{stage.minecraft_port}:25565/tcp"],
                "volumes": [
                    {
                        "type": "bind",
                        "source": game_directory,
                        "target": "/data",
                    }
                ],
            }
        },
    }
    compose_yaml = yaml.safe_dump(compose, sort_keys=True, default_flow_style=False)
    runtime_env = "".join(f"{key}={environment[key]}\n" for key in sorted(environment))
    manifest = {
        "schema_version": 1,
        "apply_class": "boot-time",
        "game_id": project.initial_game_id,
        "image": image,
        "minecraft_version": version,
        "server_type": server_type,
        "compose_sha256": hashlib.sha256(compose_yaml.encode()).hexdigest(),
        "runtime_env_sha256": hashlib.sha256(runtime_env.encode()).hexdigest(),
        "secret_material_included": False,
    }
    canonical_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    digest = hashlib.sha256(canonical_manifest.encode()).hexdigest()
    return RenderedHostRuntime(compose_yaml, runtime_env, canonical_manifest, digest)


def _runtime_mapping(values: ConfigMapping) -> ConfigMapping:
    value = values.get("host_runtime")
    if not isinstance(value, dict):
        raise ConfigValidationError(["host_runtime must be a mapping"])
    return value


def _validate_runtime_lock(runtime: ConfigMapping, *, observed_uid: int, observed_gid: int) -> None:
    errors: list[str] = []
    release = _optional_string(runtime, "platform.al2023_release")
    kernel = _optional_string(runtime, "platform.kernel_variant")
    architecture = _optional_string(runtime, "platform.architecture")
    ami_name = _optional_string(runtime, "platform.ami_name")
    ami_id = _optional_string(runtime, "platform.ami_id")
    owner_id = _optional_string(runtime, "platform.ami_owner_id")
    creation_date = _optional_string(runtime, "platform.ami_creation_date")
    expected_ami_name = (
        f"al2023-ami-{release}.3-kernel-{kernel}-{architecture}"
        if release and kernel and architecture
        else None
    )
    if expected_ami_name is None or ami_name != expected_ami_name:
        errors.append("host_runtime platform AMI name must match release, kernel, and architecture")
    if ami_id is None or re.fullmatch(r"ami-[0-9a-f]{17}", ami_id) is None:
        errors.append("host_runtime.platform.ami_id must be a fixed AMI ID")
    if owner_id != "137112412989":
        errors.append("host_runtime.platform.ami_owner_id must be the Amazon AL2023 owner")
    if (
        creation_date is None
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.000Z",
            creation_date,
        )
        is None
    ):
        errors.append("host_runtime.platform.ami_creation_date must be fixed in UTC")
    image = _optional_string(runtime, "image.reference")
    match = _IMAGE_PATTERN.fullmatch(image or "")
    if match is None:
        errors.append("host_runtime.image.reference must use a release tag and sha256 digest")
    elif match.group("java") != "java25":
        errors.append("host_runtime.image.reference must select the Java 25 variant")
    version = _optional_string(runtime, "minecraft.version")
    if version is None or version.upper() in _FLOATING_MINECRAFT_VERSIONS:
        errors.append("host_runtime.minecraft.version must be an explicit non-floating version")
    if runtime.get("minecraft") and _lookup(runtime, "minecraft.eula_accepted") is not True:
        errors.append("host_runtime.minecraft.eula_accepted must be true before rendering")
    if observed_uid <= 0 or observed_gid <= 0:
        errors.append("observed numeric UID and GID must be positive")
    container_mib = _memory_mib(_optional_string(runtime, "memory.container_limit"))
    maximum_mib = _memory_mib(_optional_string(runtime, "memory.jvm_maximum"))
    if container_mib is None or maximum_mib is None or container_mib <= maximum_mib:
        errors.append("container memory must be greater than JVM maximum heap")
    save = _optional_positive_int(runtime, "timeouts.explicit_save")
    itzg = _optional_positive_int(runtime, "timeouts.itzg_stop_duration")
    compose = _optional_positive_int(runtime, "timeouts.compose_stop_grace_period")
    systemd = _optional_positive_int(runtime, "timeouts.systemd_stop")
    wrapper = _optional_positive_int(runtime, "timeouts.host_runtime_wrapper")
    ssm = _optional_positive_int(runtime, "timeouts.ssm")
    control = _optional_positive_int(runtime, "timeouts.control_plane_wait")
    if None in (save, itzg, compose, systemd, wrapper, ssm, control):
        errors.append("all Host Runtime timeout values must be positive integers")
    else:
        assert save and itzg and compose and systemd and wrapper and ssm and control
        if not (itzg < compose < systemd):
            errors.append("itzg stop duration must be below Compose and systemd stop timeouts")
        if wrapper < save + systemd + 30:
            errors.append("Host Runtime wrapper must include save, systemd stop, and verification")
        if not (wrapper < ssm < control):
            errors.append("wrapper, SSM, and Control Plane timeout ordering is invalid")
    if errors:
        raise ConfigValidationError(errors)


def _lookup(values: ConfigMapping, path: str) -> object:
    current: object = values
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _optional_string(values: ConfigMapping, path: str) -> str | None:
    value = _lookup(values, path)
    return value if isinstance(value, str) and value else None


def _string(values: ConfigMapping, path: str) -> str:
    value = _optional_string(values, path)
    assert value is not None
    return value


def _optional_positive_int(values: ConfigMapping, path: str) -> int | None:
    value = _lookup(values, path)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _positive_int(values: ConfigMapping, path: str) -> int:
    value = _optional_positive_int(values, path)
    assert value is not None
    return value


def _memory_mib(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"([1-9][0-9]*)(MiB|GiB|M|G)", value)
    if match is None:
        return None
    amount = int(match.group(1))
    return amount * 1024 if match.group(2) in {"GiB", "G"} else amount
