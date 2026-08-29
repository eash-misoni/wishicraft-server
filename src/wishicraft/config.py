"""Loading and validation for Git-managed Wishicraft configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

import yaml

type ConfigValue = str | int | bool | None | list[ConfigValue] | dict[str, ConfigValue]
type ConfigMapping = dict[str, ConfigValue]

PROJECT_REQUIRED_MAPPINGS: Final = (
    "project",
    "branding",
    "initial_game",
    "domain",
    "toolchain",
    "resource_tags",
)
STAGE_REQUIRED_MAPPINGS: Final = (
    "aws",
    "network",
    "compute",
    "storage",
    "route53",
    "discord",
    "timeouts_seconds",
    "operation",
    "runtime",
    "host_runtime",
    "billing",
    "monitoring",
)
OPTIONAL_STAGE_MAPPINGS: Final = ("minecraft_distribution",)


class ConfigValidationError(ValueError):
    """Raised when a source-of-truth YAML file is malformed or incomplete."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(
            "Configuration validation failed:\n" + "\n".join(f"- {error}" for error in errors)
        )


@dataclass(frozen=True)
class ProjectConfig:
    """Validated project-wide public configuration."""

    values: ConfigMapping

    @property
    def resource_prefix(self) -> str:
        return _require_string(self.values, "project.resource_prefix")

    @property
    def system_id(self) -> str:
        return _require_string(self.values, "project.system_id")

    @property
    def project_slug(self) -> str:
        return _require_string(self.values, "project.slug")

    @property
    def stack_name(self) -> str:
        return _require_string(self.values, "toolchain.initial_stack_name")

    @property
    def initial_game_id(self) -> str:
        return _require_string(self.values, "initial_game.game_id")

    @property
    def initial_game_display_name(self) -> str:
        return _require_string(self.values, "initial_game.display_name")

    @property
    def initial_minecraft_profile_name(self) -> str:
        profiles = _lookup_path(self.values, "initial_game.minecraft_profile_names")
        assert isinstance(profiles, list) and len(profiles) == 1 and isinstance(profiles[0], str)
        return profiles[0]

    @property
    def initial_minecraft_profile_uuid(self) -> str:
        profiles = _lookup_path(self.values, "initial_game.minecraft_profile_uuids")
        assert isinstance(profiles, list) and len(profiles) == 1 and isinstance(profiles[0], str)
        return profiles[0]

    @property
    def initial_minecraft_profile_uuid_hyphenated(self) -> str:
        value = self.initial_minecraft_profile_uuid
        return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"

    @property
    def route53_record_type(self) -> str:
        return _require_string(self.values, "domain.record_type")

    @property
    def route53_ttl_seconds(self) -> int:
        return _require_positive_int(self.values, "domain.dns_ttl_seconds")


@dataclass(frozen=True)
class StageConfig:
    """Validated stage public configuration; nulls are intentionally preserved."""

    stage: str
    values: ConfigMapping

    def null_paths(self) -> tuple[str, ...]:
        return tuple(_find_null_paths(self.values))

    @property
    def availability_zone(self) -> str:
        """Return the configured Availability Zone after phase validation."""
        return _require_string(self.values, "aws.availability_zone")

    @property
    def aws_account_id(self) -> str:
        """Return the configured AWS account ID after phase validation."""
        return _require_string(self.values, "aws.account_id")

    @property
    def aws_region(self) -> str:
        """Return the configured AWS Region after phase validation."""
        return _require_string(self.values, "aws.region")

    @property
    def minecraft_port(self) -> int:
        """Return the configured public Minecraft TCP port after phase validation."""
        return _require_positive_int(self.values, "network.minecraft_port")

    @property
    def rcon_port(self) -> int:
        """Return the explicitly configured host-local RCON port."""
        port = _require_positive_int(self.values, "network.rcon_port")
        if port > 65535 or port == self.minecraft_port:
            raise ConfigValidationError(
                ["network.rcon_port must differ from minecraft_port and be <= 65535"]
            )
        return port

    @property
    def route53_hosted_zone_id(self) -> str:
        return _require_string(self.values, "route53.hosted_zone_id")

    @property
    def route53_record_name(self) -> str:
        return _require_string(self.values, "route53.record_name")

    @property
    def route53_insync_timeout_seconds(self) -> int:
        return _require_positive_int(self.values, "timeouts_seconds.route53_insync")

    @property
    def ssm_probe_timeout_seconds(self) -> int:
        return _require_positive_int(self.values, "timeouts_seconds.ssm_probe")

    @property
    def global_lock_name(self) -> str:
        return _require_string(self.values, "operation.global_lock_name")

    @property
    def lock_lease_seconds(self) -> int:
        return _require_positive_int(self.values, "operation.lock_lease_seconds")

    @property
    def lock_renew_interval_seconds(self) -> int:
        return _require_positive_int(self.values, "operation.lock_renew_interval_seconds")

    def host_runtime_timeout_seconds(self, name: str) -> int:
        if name not in {"wrapper", "ssm", "control_plane_wait"}:
            raise ConfigValidationError([f"unsupported Host Runtime timeout: {name}"])
        key = "host_runtime_wrapper" if name == "wrapper" else name
        return _require_positive_int(self.values, f"host_runtime.timeouts.{key}")

    def operation_timeout_seconds(self, operation_type: str) -> int:
        key = {
            "STATUS": "status",
            "START": "start_workflow",
            "STOP": "stop_workflow",
            "BACKUP": "backup",
        }.get(operation_type)
        if key is None:
            raise ConfigValidationError([f"unsupported Phase 4 operation type: {operation_type}"])
        return _require_positive_int(self.values, f"timeouts_seconds.{key}")

    @property
    def idle_shutdown_minutes(self) -> int:
        return _require_positive_int(self.values, "runtime.idle_shutdown_minutes")

    @property
    def instance_type(self) -> str:
        """Return the configured EC2 instance type after phase validation."""
        return _require_string(self.values, "compute.instance_type")

    @property
    def architecture(self) -> str:
        """Return the configured CPU architecture after phase validation."""
        return _require_string(self.values, "compute.architecture")

    @property
    def operating_system(self) -> str:
        """Return the configured operating system after phase validation."""
        return _require_string(self.values, "compute.operating_system")

    @property
    def java_runtime(self) -> str:
        """Return the configured Java runtime after phase validation."""
        return _require_string(self.values, "compute.java_runtime")

    @property
    def minecraft_version(self) -> str:
        return _require_string(self.values, "compute.minecraft_version")

    @property
    def java_xms(self) -> str:
        return _require_string(self.values, "compute.java_xms")

    @property
    def java_xmx(self) -> str:
        return _require_string(self.values, "compute.java_xmx")

    @property
    def minecraft_server_jar_url(self) -> str:
        return _require_string(self.values, "minecraft_distribution.server_jar_url")

    @property
    def minecraft_server_jar_sha1(self) -> str:
        return _require_string(self.values, "minecraft_distribution.server_jar_sha1")

    @property
    def minecraft_server_jar_sha256(self) -> str:
        return _require_string(self.values, "minecraft_distribution.server_jar_sha256")

    @property
    def minecraft_server_jar_size(self) -> int:
        return _require_positive_int(self.values, "minecraft_distribution.server_jar_size")

    @property
    def minecraft_normal_stop_timeout_seconds(self) -> int:
        return _require_positive_int(self.values, "timeouts_seconds.minecraft_normal_stop")

    @property
    def root_volume_type(self) -> str:
        """Return the configured root EBS volume type after phase validation."""
        return _require_string(self.values, "storage.root.volume_type")

    @property
    def root_volume_size_gib(self) -> int:
        """Return the configured root EBS size after phase validation."""
        return _require_positive_int(self.values, "storage.root.size_gib")

    @property
    def root_volume_encrypted(self) -> bool:
        """Return the configured root EBS encryption setting after phase validation."""
        value = _lookup_path(self.values, "storage.root.encrypted")
        assert isinstance(value, bool)
        return value

    @property
    def data_volume_type(self) -> str:
        """Return the configured data EBS volume type after phase validation."""
        return _require_string(self.values, "storage.data.volume_type")

    @property
    def data_volume_size_gib(self) -> int:
        """Return the configured data EBS size after phase validation."""
        return _require_positive_int(self.values, "storage.data.size_gib")

    @property
    def data_volume_encrypted(self) -> bool:
        """Return the configured data EBS encryption setting after phase validation."""
        value = _lookup_path(self.values, "storage.data.encrypted")
        assert isinstance(value, bool)
        return value

    @property
    def data_volume_retain_on_delete(self) -> bool:
        """Require the configured data EBS retention policy to remain enabled."""
        value = _lookup_path(self.values, "storage.data.retain_on_delete")
        if value is not True:
            raise ConfigValidationError(["storage.data.retain_on_delete must be true for Phase 1"])
        return value

    @property
    def data_volume_filesystem_type(self) -> str:
        """Return the configured filesystem type for the retained data EBS volume."""
        return _require_string(self.values, "storage.data.filesystem_type")

    @property
    def data_volume_mount_path(self) -> str:
        """Return the configured mount path for the retained data EBS volume."""
        return _require_string(self.values, "storage.data.mount_path")

    def host_runtime_value(self, path: str) -> ConfigValue:
        """Return one validated public Host Runtime value."""
        return _lookup_path(self.values, f"host_runtime.{path}")


@dataclass(frozen=True)
class SecretsExampleConfig:
    """Validated secret parameter-name configuration, never secret values."""

    values: ConfigMapping

    def rcon_password_parameter_name(self, stage: str) -> str:
        """Return the configured RCON SecureString name for one stage."""
        return _require_string(
            self.values, f"secure_parameters.rcon_password.{stage}_parameter_name"
        )


@dataclass(frozen=True)
class Configuration:
    """All canonical Phase 0 configuration inputs."""

    project: ProjectConfig
    stage: StageConfig
    secrets: SecretsExampleConfig


def load_configuration(repository_root: Path, stage: str) -> Configuration:
    """Load the three canonical YAML inputs without resolving any null values."""
    project = load_project_config(repository_root / "config" / "project.yaml")
    stage_config = load_stage_config(repository_root / "config" / "stages" / f"{stage}.yaml", stage)
    secrets = load_secrets_example_config(repository_root / "config" / "secrets.example.yaml")
    return Configuration(project=project, stage=stage_config, secrets=secrets)


def load_project_config(path: Path) -> ProjectConfig:
    values = _load_mapping(path)
    errors = _schema_errors(values, "project.yaml", PROJECT_REQUIRED_MAPPINGS)
    errors.extend(_expect_schema_version(values, "project.yaml"))
    errors.extend(
        _expect_string_paths(values, "project.yaml", ("project.slug", "project.resource_prefix"))
    )
    errors.extend(_expect_list_of_strings(values, "project.yaml", "project.stages"))
    errors.extend(
        _expect_list_of_strings(values, "project.yaml", "initial_game.minecraft_profile_names")
    )
    errors.extend(
        _expect_list_of_strings(values, "project.yaml", "initial_game.minecraft_profile_uuids")
    )
    profile_uuids = _lookup_path(values, "initial_game.minecraft_profile_uuids")
    if isinstance(profile_uuids, list):
        errors.extend(
            "project.yaml: initial_game.minecraft_profile_uuids["
            f"{index}] must be a lowercase UUID hex string"
            for index, value in enumerate(profile_uuids)
            if not isinstance(value, str)
            or len(value) != 32
            or any(character not in "0123456789abcdef" for character in value)
        )
    if errors:
        raise ConfigValidationError(errors)
    return ProjectConfig(values)


def load_stage_config(path: Path, expected_stage: str) -> StageConfig:
    values = _load_mapping(path)
    errors = _schema_errors(values, f"stages/{expected_stage}.yaml", STAGE_REQUIRED_MAPPINGS)
    errors.extend(_expect_schema_version(values, f"stages/{expected_stage}.yaml"))
    errors.extend(_expect_optional_mappings(values, f"stages/{expected_stage}.yaml"))
    stage = values.get("stage")
    if not isinstance(stage, str):
        errors.append(f"stages/{expected_stage}.yaml: stage must be a string")
    elif stage != expected_stage:
        errors.append(f"stages/{expected_stage}.yaml: stage must equal {expected_stage!r}")
    errors.extend(
        _expect_optional_string_paths(
            values, f"stages/{expected_stage}.yaml", _OPTIONAL_STAGE_STRINGS
        )
    )
    errors.extend(
        _expect_positive_int_paths(values, f"stages/{expected_stage}.yaml", _POSITIVE_STAGE_INTS)
    )
    errors.extend(_expect_sha1_paths(values, f"stages/{expected_stage}.yaml"))
    errors.extend(_expect_sha256_paths(values, f"stages/{expected_stage}.yaml"))
    if errors:
        raise ConfigValidationError(errors)
    return StageConfig(stage=expected_stage, values=values)


def load_secrets_example_config(path: Path) -> SecretsExampleConfig:
    values = _load_mapping(path)
    errors = _expect_schema_version(values, "secrets.example.yaml")
    for section in ("secure_parameters", "future_secure_parameters"):
        nested = values.get(section)
        if not isinstance(nested, dict):
            errors.append(f"secrets.example.yaml: {section} must be a mapping")
            continue
        for secret_name, parameter_names in nested.items():
            if not isinstance(parameter_names, dict):
                errors.append(f"secrets.example.yaml: {section}.{secret_name} must be a mapping")
                continue
            expected_keys = {"dev_parameter_name", "prod_parameter_name"}
            if set(parameter_names) != expected_keys:
                errors.append(
                    f"secrets.example.yaml: {section}.{secret_name} must contain only "
                    "dev_parameter_name and prod_parameter_name"
                )
            for key, value in parameter_names.items():
                if not isinstance(value, str) or not value.startswith("/"):
                    errors.append(
                        "secrets.example.yaml: "
                        f"{section}.{secret_name}.{key} must be a Parameter Store name"
                    )
    if errors:
        raise ConfigValidationError(errors)
    return SecretsExampleConfig(values)


# This registry is intentionally scoped by phase and action. Phase 1 can add explicit
# requirements without treating today's complete set of null placeholders as permanent.
REQUIRED_PATHS: Final[dict[tuple[int, str, str], tuple[str, ...]]] = {
    (0, "dev", "synth"): (),
    (1, "dev", "synth"): (
        "aws.account_id",
        "aws.region",
        "aws.availability_zone",
        "network.minecraft_port",
        "network.rcon_port",
        "compute.architecture",
        "compute.instance_type",
        "compute.operating_system",
        "compute.java_runtime",
        "compute.minecraft_version",
        "compute.java_xms",
        "compute.java_xmx",
        "minecraft_distribution.server_jar_url",
        "minecraft_distribution.server_jar_sha1",
        "minecraft_distribution.server_jar_sha256",
        "minecraft_distribution.server_jar_size",
        "storage.root.volume_type",
        "storage.root.size_gib",
        "storage.root.encrypted",
        "storage.data.volume_type",
        "storage.data.size_gib",
        "storage.data.encrypted",
        "storage.data.retain_on_delete",
        "storage.data.filesystem_type",
        "storage.data.mount_path",
        "route53.hosted_zone_id",
        "route53.record_name",
    ),
    (1, "dev", "deploy"): (
        "aws.account_id",
        "aws.region",
        "aws.availability_zone",
        "network.minecraft_port",
        "network.rcon_port",
        "compute.architecture",
        "compute.instance_type",
        "compute.operating_system",
        "compute.java_runtime",
        "compute.minecraft_version",
        "compute.java_xms",
        "compute.java_xmx",
        "minecraft_distribution.server_jar_url",
        "minecraft_distribution.server_jar_sha1",
        "minecraft_distribution.server_jar_sha256",
        "minecraft_distribution.server_jar_size",
        "storage.root.volume_type",
        "storage.root.size_gib",
        "storage.root.encrypted",
        "storage.data.volume_type",
        "storage.data.size_gib",
        "storage.data.encrypted",
        "storage.data.retain_on_delete",
        "storage.data.filesystem_type",
        "storage.data.mount_path",
        "route53.hosted_zone_id",
        "route53.record_name",
    ),
}


def validate_stage_for_action(stage_config: StageConfig, *, phase: int, action: str) -> None:
    """Apply action-specific required-value checks after schema validation.

    The Phase 0 prod gate reports every current null placeholder. It is a temporary
    safety gate, not the registry for future resource requirements.
    """
    if phase == 0 and action == "synth" and stage_config.stage == "prod":
        missing = list(stage_config.null_paths())
    else:
        missing = [
            path
            for path in REQUIRED_PATHS.get((phase, stage_config.stage, action), ())
            if _lookup_path(stage_config.values, path) is None
        ]
    if missing:
        raise ConfigValidationError(
            [
                f"stage {stage_config.stage!r} is not ready for Phase {phase} "
                f"{action}: {path} is null"
                for path in missing
            ]
        )


_OPTIONAL_STAGE_STRINGS: Final = (
    "aws.account_id",
    "aws.region",
    "aws.availability_zone",
    "compute.architecture",
    "compute.instance_type",
    "compute.operating_system",
    "compute.java_runtime",
    "compute.minecraft_version",
    "compute.java_xms",
    "compute.java_xmx",
    "minecraft_distribution.server_jar_url",
    "minecraft_distribution.server_jar_sha1",
    "minecraft_distribution.server_jar_sha256",
    "route53.hosted_zone_id",
    "route53.record_name",
    "discord.environment_label",
    "discord.bot_display_name",
    "discord.command_scope",
    "discord.guild_id",
    "discord.operation_channel_id",
    "discord.admin_channel_id",
    "discord.player_role_id",
    "discord.admin_role_id",
    "discord.application_id",
    "discord.public_key",
    "operation.global_lock_name",
    "storage.root.volume_type",
    "storage.data.volume_type",
    "storage.data.filesystem_type",
    "storage.data.mount_path",
    "billing.dynamodb_mode",
    "host_runtime.platform.operating_system",
    "host_runtime.target_host.stack_name",
    "host_runtime.target_host.vpc_id",
    "host_runtime.target_host.subnet_id",
    "host_runtime.target_host.instance_type",
    "host_runtime.target_host.root_volume_type",
    "host_runtime.target_host.existing_data_volume_id",
    "host_runtime.target_host.existing_data_volume_device",
    "host_runtime.platform.al2023_release",
    "host_runtime.platform.kernel_variant",
    "host_runtime.platform.ami_name",
    "host_runtime.platform.ami_id",
    "host_runtime.platform.architecture",
    "host_runtime.platform.ami_owner_id",
    "host_runtime.platform.ami_creation_date",
    "host_runtime.compose.version",
    "host_runtime.compose.url",
    "host_runtime.compose.sha256",
    "host_runtime.image.reference",
    "host_runtime.image.release",
    "host_runtime.image.java_variant",
    "host_runtime.minecraft.version",
    "host_runtime.minecraft.type",
    "host_runtime.memory.container_limit",
    "host_runtime.memory.jvm_initial",
    "host_runtime.memory.jvm_maximum",
)
_POSITIVE_STAGE_INTS: Final = (
    "network.minecraft_port",
    "network.rcon_port",
    "storage.root.size_gib",
    "storage.data.size_gib",
    "minecraft_distribution.server_jar_size",
    "timeouts_seconds.ec2_running",
    "timeouts_seconds.ssm_online",
    "timeouts_seconds.minecraft_ready",
    "operation.lock_lease_seconds",
    "operation.lock_renew_interval_seconds",
    "runtime.idle_shutdown_minutes",
    "monitoring.log_retention_days",
    "host_runtime.identity.uid",
    "host_runtime.identity.gid",
    "host_runtime.target_host.root_volume_size_gib",
    "host_runtime.timeouts.explicit_save",
    "host_runtime.timeouts.itzg_stop_duration",
    "host_runtime.timeouts.compose_stop_grace_period",
    "host_runtime.timeouts.systemd_stop",
    "host_runtime.timeouts.host_runtime_wrapper",
    "host_runtime.timeouts.ssm",
    "host_runtime.timeouts.control_plane_wait",
)


def _expect_optional_mappings(values: ConfigMapping, filename: str) -> list[str]:
    errors: list[str] = []
    for path in OPTIONAL_STAGE_MAPPINGS:
        value = _lookup_path(values, path)
        if value is not None and not isinstance(value, dict):
            errors.append(f"{filename}: {path} must be a mapping or null")
    return errors


def _load_mapping(path: Path) -> ConfigMapping:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigValidationError(
            [f"{path}: could not read configuration ({error.strerror})"]
        ) from error
    except yaml.YAMLError as error:
        raise ConfigValidationError([f"{path}: invalid YAML ({error})"]) from error
    if not isinstance(raw, dict):
        raise ConfigValidationError([f"{path}: top level must be a mapping"])
    return cast(ConfigMapping, raw)


def _schema_errors(values: ConfigMapping, filename: str, mappings: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for path in mappings:
        if not isinstance(values.get(path), dict):
            errors.append(f"{filename}: {path} must be a mapping")
    return errors


def _expect_schema_version(values: ConfigMapping, filename: str) -> list[str]:
    return (
        []
        if values.get("schema_version") == 1
        else [f"{filename}: schema_version must be integer 1"]
    )


def _expect_string_paths(values: ConfigMapping, filename: str, paths: tuple[str, ...]) -> list[str]:
    return [
        f"{filename}: {path} must be a non-empty string"
        for path in paths
        if not isinstance(_lookup_path(values, path), str) or not _lookup_path(values, path)
    ]


def _expect_list_of_strings(values: ConfigMapping, filename: str, path: str) -> list[str]:
    value = _lookup_path(values, path)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        return [f"{filename}: {path} must be a non-empty list of strings"]
    return []


def _expect_optional_string_paths(
    values: ConfigMapping, filename: str, paths: tuple[str, ...]
) -> list[str]:
    errors: list[str] = []
    for path in paths:
        value = _lookup_path(values, path)
        if value is not None and (not isinstance(value, str) or not value):
            errors.append(f"{filename}: {path} must be a string or null")
    return errors


def _expect_positive_int_paths(
    values: ConfigMapping, filename: str, paths: tuple[str, ...]
) -> list[str]:
    errors: list[str] = []
    for path in paths:
        value = _lookup_path(values, path)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
        ):
            errors.append(f"{filename}: {path} must be a positive integer or null")
    return errors


def _expect_sha1_paths(values: ConfigMapping, filename: str) -> list[str]:
    path = "minecraft_distribution.server_jar_sha1"
    value = _lookup_path(values, path)
    if value is None:
        return []
    is_lowercase_sha1 = (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value)
    )
    if not is_lowercase_sha1:
        return [f"{filename}: {path} must be a lowercase SHA-1 hex string or null"]
    return []


def _expect_sha256_paths(values: ConfigMapping, filename: str) -> list[str]:
    path = "minecraft_distribution.server_jar_sha256"
    value = _lookup_path(values, path)
    if value is None:
        return []
    if not (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return [f"{filename}: {path} must be a lowercase SHA-256 hex string or null"]
    return []


def _lookup_path(values: Mapping[str, ConfigValue], path: str) -> ConfigValue:
    current: ConfigValue | Mapping[str, ConfigValue] = values
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return cast(ConfigValue, current)


def _require_string(values: Mapping[str, ConfigValue], path: str) -> str:
    value = _lookup_path(values, path)
    assert isinstance(value, str)
    return value


def _require_positive_int(values: Mapping[str, ConfigValue], path: str) -> int:
    value = _lookup_path(values, path)
    assert isinstance(value, int) and not isinstance(value, bool) and value > 0
    return value


def _find_null_paths(value: ConfigValue, prefix: str = "") -> list[str]:
    if value is None:
        return [prefix]
    if isinstance(value, dict):
        return [
            path
            for key, nested in value.items()
            for path in _find_null_paths(nested, _join_path(prefix, key))
        ]
    if isinstance(value, list):
        return [
            path
            for index, nested in enumerate(value)
            for path in _find_null_paths(nested, f"{prefix}[{index}]")
        ]
    return []


def _join_path(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name
