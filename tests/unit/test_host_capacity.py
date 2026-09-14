"""Deployment capacity must change only the existing EC2 InstanceType property."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App
from aws_cdk.assertions import Template

from infrastructure.stacks.minecraft_target_stack import MinecraftTargetStack
from wishicraft.config import ConfigValidationError, StageConfig, load_configuration
from wishicraft.host_runtime import RenderedHostRuntime, render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]
TYPES = ("t3a.medium", "m8a.large", "r8a.large", "m8a.xlarge")


def stage_with(value: object) -> StageConfig:
    values = deepcopy(load_configuration(ROOT, "dev").stage.values)
    runtime = values["host_runtime"]
    assert isinstance(runtime, dict)
    host = runtime["target_host"]
    assert isinstance(host, dict)
    # Exercise malformed YAML values as well as supported strings.
    host["instance_type"] = value  # type: ignore[assignment]
    # D-107's type-only invariance uses the original budget, safe on every candidate.
    runtime["memory"] = {"jvm_initial": "1G", "jvm_maximum": "2G", "container_limit": "2816MiB"}
    return StageConfig("dev", values)


@pytest.mark.parametrize("instance_type", TYPES)
def test_only_instance_type_changes(instance_type: str, tmp_path: Path) -> None:
    project = load_configuration(ROOT, "dev").project

    def template(value: str, suffix: str) -> dict[str, Any]:
        app = App(outdir=str(tmp_path / suffix))
        stack = MinecraftTargetStack(app, stage=stage_with(value), project=project)
        return dict(Template.from_stack(stack).to_json())

    baseline = template("t3a.medium", "baseline")
    candidate = template(instance_type, "candidate")
    resources = candidate["Resources"]
    instances = [v for v in resources.values() if v["Type"] == "AWS::EC2::Instance"]
    assert len(instances) == 1
    assert instances[0]["Properties"]["InstanceType"] == instance_type
    assert "LaunchTemplate" not in instances[0]["Properties"]
    assert "CpuOptions" not in instances[0]["Properties"]
    instances[0]["Properties"]["InstanceType"] = "t3a.medium"
    # Includes logical IDs, root mapping, retained attachment, IAM, SG and outputs.
    assert candidate == baseline


@pytest.mark.parametrize("value", [None, "", "standard", "c8a.large", "m8a.2xlarge", 8, True, []])
def test_unsupported_capacity_fails_before_template(value: object, tmp_path: Path) -> None:
    app = App(outdir=str(tmp_path / "cdk"))
    with pytest.raises(ConfigValidationError, match="host_runtime.target_host.instance_type"):
        MinecraftTargetStack(
            app, stage=stage_with(value), project=load_configuration(ROOT, "dev").project
        )


@pytest.mark.parametrize("instance_type", TYPES)
def test_capacity_preserves_runtime_artifacts_and_digest(instance_type: str) -> None:
    configuration = load_configuration(ROOT, "dev")

    def render(value: str) -> RenderedHostRuntime:
        return render_boot_time_artifacts(
            configuration.project,
            stage_with(value),
            observed_uid=993,
            observed_gid=993,
            targeted=True,
            games=("game-vanilla-main", "game-vanilla-second"),
        )

    assert render(instance_type) == render("t3a.medium")
    assert "MAX_MEMORY=2G" in render(instance_type).runtime_env
    assert "mem_limit: 2816MiB" in render(instance_type).compose_yaml
    assert configuration.stage.instance_type == "t3a.medium"  # Frozen Phase 1.


def test_prod_placeholder_is_not_resolved() -> None:
    stage = load_configuration(ROOT, "prod").stage
    assert stage.host_runtime_value("target_host.instance_type") is None
    with pytest.raises(ConfigValidationError, match="host_runtime.target_host.instance_type"):
        _ = stage.target_instance_type
