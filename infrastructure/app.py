"""CDK entry point for the stage-specific Wishicraft stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import App

from infrastructure.stacks.control_plane_stack import ControlPlaneStack
from infrastructure.stacks.minecraft_stack import MinecraftStack
from infrastructure.stacks.minecraft_target_stack import MinecraftTargetStack
from wishicraft.config import load_configuration, validate_stage_for_action
from wishicraft.runtime_catalog import RuntimeCatalog


def build_app(
    repository_root: Path,
    stage: str,
    *,
    phase: int = 0,
    action: str = "synth",
    deployment: str = "phase1",
    two_games: bool = False,
) -> App:
    """Build an environment-agnostic CDK app after phase-specific validation."""
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=phase, action=action)

    app = App()
    if deployment == "target":
        MinecraftTargetStack(app, stage=configuration.stage, project=configuration.project)
    elif deployment == "control-plane":
        ControlPlaneStack(
            app,
            stage=configuration.stage,
            project=configuration.project,
            secrets=configuration.secrets,
            phase=phase,
            games=_games(repository_root, stage) if two_games else None,
        )
    elif deployment == "phase1":
        MinecraftStack(
            app,
            f"{configuration.project.stack_name}-{stage}",
            project=configuration.project,
            stage=configuration.stage,
            secrets=configuration.secrets,
            phase=phase,
        )
    else:
        raise ValueError("deployment must be phase1, target, or control-plane")
    return app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    app = App()
    stage = app.node.try_get_context("stage") or "dev"
    phase_context = app.node.try_get_context("phase") or "0"
    validation_action = app.node.try_get_context("validation_action") or "synth"
    deployment = app.node.try_get_context("deployment") or "phase1"
    try:
        phase = int(phase_context)
    except (TypeError, ValueError) as error:
        raise ValueError("CDK context phase must be an integer") from error
    if validation_action not in {"synth", "deploy"}:
        raise ValueError("CDK context validation_action must be synth or deploy")
    configuration = load_configuration(repository_root, stage)
    validate_stage_for_action(configuration.stage, phase=phase, action=validation_action)
    if deployment == "target":
        MinecraftTargetStack(app, stage=configuration.stage, project=configuration.project)
    elif deployment == "control-plane":
        ControlPlaneStack(
            app,
            stage=configuration.stage,
            project=configuration.project,
            secrets=configuration.secrets,
            phase=phase,
            games=_games(repository_root, stage)
            if app.node.try_get_context("two_games") == "true"
            else None,
        )
    elif deployment == "phase1":
        MinecraftStack(
            app,
            f"{configuration.project.stack_name}-{stage}",
            project=configuration.project,
            stage=configuration.stage,
            secrets=configuration.secrets,
            phase=phase,
        )
    else:
        raise ValueError("CDK context deployment must be phase1, target, or control-plane")
    app.synth()


def _games(root: Path, stage: str) -> tuple[str, ...]:
    return RuntimeCatalog.parse((root / "config" / f"two-game-{stage}.json").read_text()).game_ids


if __name__ == "__main__":
    main()
