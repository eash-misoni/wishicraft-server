from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from infrastructure.constructs.minecraft_artifact import resolve_minecraft_artifact
from wishicraft.config import StageConfig, load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_resolves_only_the_fixed_minecraft_26_2_artifact() -> None:
    stage = load_configuration(REPOSITORY_ROOT, "dev").stage

    artifact = resolve_minecraft_artifact(stage)

    assert artifact.version == "26.2"
    assert artifact.size == 60894273
    assert artifact.url.endswith("823e2250d24b3ddac457a60c92a6a941943fcd6a/server.jar")


@pytest.mark.parametrize("path,value", (("compute.minecraft_version", "latest"),))
def test_rejects_unsupported_minecraft_versions(path: str, value: str) -> None:
    stage = load_configuration(REPOSITORY_ROOT, "dev").stage
    values = dict(stage.values)
    raw_compute = values["compute"]
    assert isinstance(raw_compute, dict)
    compute = dict(raw_compute)
    compute[path.split(".")[-1]] = value
    values["compute"] = compute

    with pytest.raises(ValueError, match="Unsupported Minecraft version"):
        resolve_minecraft_artifact(replace(stage, values=values))


def test_rejects_stage_artifact_drift() -> None:
    stage = load_configuration(REPOSITORY_ROOT, "dev").stage
    values = dict(stage.values)
    raw_distribution = values["minecraft_distribution"]
    assert isinstance(raw_distribution, dict)
    distribution = dict(raw_distribution)
    distribution["server_jar_sha256"] = "0" * 64
    values["minecraft_distribution"] = distribution

    with pytest.raises(ValueError, match="does not match"):
        resolve_minecraft_artifact(StageConfig(stage="dev", values=values))
