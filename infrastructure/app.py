"""CDK entry point for the stage-specific Wishicraft stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import App

from infrastructure.stacks.minecraft_stack import MinecraftStack
from wishicraft.config import load_configuration, validate_stage_for_action


def build_app(repository_root: Path, stage: str, *, phase: int = 0, action: str = "synth") -> App:
    """Build an environment-agnostic CDK app after phase-specific validation."""
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=phase, action=action)

    app = App()
    MinecraftStack(
        app,
        f"{configuration.project.stack_name}-{stage}",
        project=configuration.project,
        stage=configuration.stage,
        secrets=configuration.secrets,
        phase=phase,
    )
    return app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    app = App()
    stage = app.node.try_get_context("stage") or "dev"
    phase_context = app.node.try_get_context("phase") or "0"
    validation_action = app.node.try_get_context("validation_action") or "synth"
    try:
        phase = int(phase_context)
    except (TypeError, ValueError) as error:
        raise ValueError("CDK context phase must be an integer") from error
    if validation_action not in {"synth", "deploy"}:
        raise ValueError("CDK context validation_action must be synth or deploy")
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=phase, action=validation_action)
    MinecraftStack(
        app,
        f"{configuration.project.stack_name}-{stage}",
        project=configuration.project,
        stage=configuration.stage,
        secrets=configuration.secrets,
        phase=phase,
    )
    app.synth()


if __name__ == "__main__":
    main()
