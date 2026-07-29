"""CDK entry point for the stage-specific Wishicraft stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import App

from infrastructure.stacks.minecraft_stack import MinecraftStack
from wishicraft.config import load_configuration, validate_stage_for_action


def build_app(repository_root: Path, stage: str) -> App:
    """Build a Phase 0 environment-agnostic CDK app for one configured stage."""
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=0, action="synth")

    app = App()
    MinecraftStack(
        app,
        f"{configuration.project.stack_name}-{stage}",
        project=configuration.project,
        stage=configuration.stage,
    )
    return app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    app = App()
    stage = app.node.try_get_context("stage") or "dev"
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=0, action="synth")
    MinecraftStack(
        app,
        f"{configuration.project.stack_name}-{stage}",
        project=configuration.project,
        stage=configuration.stage,
    )
    app.synth()


if __name__ == "__main__":
    main()
