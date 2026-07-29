from __future__ import annotations

from pathlib import Path

import pytest

from wishicraft.config import (
    ConfigValidationError,
    StageConfig,
    load_configuration,
    load_project_config,
    load_secrets_example_config,
    load_stage_config,
    validate_stage_for_action,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_project_dev_prod_and_secrets_load() -> None:
    dev = load_configuration(REPOSITORY_ROOT, "dev")
    prod = load_configuration(REPOSITORY_ROOT, "prod")

    assert dev.project.resource_prefix == "wc"
    assert dev.stage.stage == "dev"
    assert prod.stage.stage == "prod"
    assert "secure_parameters" in dev.secrets.values


def test_dev_phase_zero_synth_allows_known_nulls() -> None:
    config = load_configuration(REPOSITORY_ROOT, "dev")

    validate_stage_for_action(config.stage, phase=0, action="synth")


@pytest.mark.parametrize("action", ("synth", "deploy"))
def test_dev_phase_one_validation_accepts_confirmed_settings(action: str) -> None:
    config = load_configuration(REPOSITORY_ROOT, "dev")

    validate_stage_for_action(config.stage, phase=1, action=action)


def test_data_volume_filesystem_settings_are_loaded_from_stage_configuration() -> None:
    config = load_configuration(REPOSITORY_ROOT, "dev")

    assert config.stage.data_volume_filesystem_type == "xfs"
    assert config.stage.data_volume_mount_path == "/srv/minecraft"


def test_dev_minecraft_artifact_and_initial_profile_are_fully_fixed() -> None:
    config = load_configuration(REPOSITORY_ROOT, "dev")

    assert config.stage.minecraft_version == "26.2"
    assert config.stage.java_runtime == "corretto-25-headless"
    assert (config.stage.java_xms, config.stage.java_xmx, config.stage.minecraft_port) == (
        "1G",
        "3G",
        25565,
    )
    assert config.stage.minecraft_server_jar_size == 60894273
    assert config.stage.minecraft_server_jar_sha1 == "823e2250d24b3ddac457a60c92a6a941943fcd6a"
    assert config.stage.minecraft_server_jar_sha256 == (
        "cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5"
    )
    assert config.project.initial_minecraft_profile_name == "NEWISHIN_"
    assert config.project.initial_minecraft_profile_uuid == "e912ab95758e4b7fb32e292eda293104"


def test_rejects_non_string_data_volume_filesystem_type(tmp_path: Path) -> None:
    source = (REPOSITORY_ROOT / "config" / "stages" / "dev.yaml").read_text(encoding="utf-8")
    path = tmp_path / "dev.yaml"
    path.write_text(source.replace("filesystem_type: xfs", "filesystem_type: 1"), encoding="utf-8")

    with pytest.raises(
        ConfigValidationError, match="storage.data.filesystem_type must be a string"
    ):
        load_stage_config(path, "dev")


def test_dev_phase_one_validation_rejects_missing_server_checksum() -> None:
    config = load_configuration(REPOSITORY_ROOT, "dev")
    values = {**config.stage.values}
    raw_distribution = values["minecraft_distribution"]
    assert isinstance(raw_distribution, dict)
    distribution = dict(raw_distribution)
    distribution["server_jar_sha1"] = None
    values["minecraft_distribution"] = distribution
    incomplete_stage = StageConfig(stage="dev", values=values)

    with pytest.raises(ConfigValidationError, match="minecraft_distribution.server_jar_sha1"):
        validate_stage_for_action(incomplete_stage, phase=1, action="synth")


def test_prod_phase_zero_synth_rejects_each_current_null() -> None:
    config = load_configuration(REPOSITORY_ROOT, "prod")

    with pytest.raises(ConfigValidationError) as error:
        validate_stage_for_action(config.stage, phase=0, action="synth")

    assert error.value.errors == [
        f"stage 'prod' is not ready for Phase 0 synth: {path} is null"
        for path in config.stage.null_paths()
    ]
    assert "aws.account_id" in str(error.value)
    assert "discord.public_key" in str(error.value)


def test_rejects_wrong_type_without_coercion(tmp_path: Path) -> None:
    path = tmp_path / "dev.yaml"
    path.write_text("schema_version: 1\nstage: dev\naws: not-a-mapping\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="aws must be a mapping"):
        load_stage_config(path, "dev")


def test_rejects_missing_required_project_structure(tmp_path: Path) -> None:
    path = tmp_path / "project.yaml"
    path.write_text("schema_version: 1\nproject: {}\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="branding must be a mapping"):
        load_project_config(path)


def test_rejects_secret_values_in_the_secrets_example(tmp_path: Path) -> None:
    path = tmp_path / "secrets.example.yaml"
    path.write_text(
        """schema_version: 1
secure_parameters:
  discord_bot_token:
    dev_parameter_name: /wishicraft/dev/secret/discord-bot-token
    prod_parameter_name: /wishicraft/prod/secret/discord-bot-token
    value: should-not-be-stored-here
future_secure_parameters: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="must contain only"):
        load_secrets_example_config(path)
