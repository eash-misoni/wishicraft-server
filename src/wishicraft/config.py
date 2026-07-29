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
    def stack_name(self) -> str:
        return _require_string(self.values, "toolchain.initial_stack_name")


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
        value = _lookup_path(self.values, "network.minecraft_port")
        assert isinstance(value, int) and not isinstance(value, bool)
        return value


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
        "compute.architecture",
        "compute.instance_type",
        "compute.operating_system",
        "compute.java_runtime",
        "compute.minecraft_version",
        "compute.java_xms",
        "compute.java_xmx",
        "minecraft_distribution.server_jar_url",
        "minecraft_distribution.server_jar_sha1",
        "storage.root.volume_type",
        "storage.root.size_gib",
        "storage.root.encrypted",
        "storage.data.volume_type",
        "storage.data.size_gib",
        "storage.data.encrypted",
        "storage.data.retain_on_delete",
        "storage.data.mount_path",
        "route53.hosted_zone_id",
        "route53.record_name",
    ),
    (1, "dev", "deploy"): (
        "aws.account_id",
        "aws.region",
        "aws.availability_zone",
        "network.minecraft_port",
        "compute.architecture",
        "compute.instance_type",
        "compute.operating_system",
        "compute.java_runtime",
        "compute.minecraft_version",
        "compute.java_xms",
        "compute.java_xmx",
        "minecraft_distribution.server_jar_url",
        "minecraft_distribution.server_jar_sha1",
        "storage.root.volume_type",
        "storage.root.size_gib",
        "storage.root.encrypted",
        "storage.data.volume_type",
        "storage.data.size_gib",
        "storage.data.encrypted",
        "storage.data.retain_on_delete",
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
    "storage.data.mount_path",
    "billing.dynamodb_mode",
)
_POSITIVE_STAGE_INTS: Final = (
    "network.minecraft_port",
    "storage.root.size_gib",
    "storage.data.size_gib",
    "timeouts_seconds.ec2_running",
    "timeouts_seconds.ssm_online",
    "timeouts_seconds.minecraft_ready",
    "operation.lock_lease_seconds",
    "operation.lock_renew_interval_seconds",
    "runtime.idle_shutdown_minutes",
    "monitoring.log_retention_days",
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
