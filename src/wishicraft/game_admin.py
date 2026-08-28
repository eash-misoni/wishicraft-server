"""Explicit admin path for conditionally registering the canonical initial Game."""

from __future__ import annotations

import argparse
import importlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from wishicraft.config import load_configuration
from wishicraft.game import (
    DynamoApi,
    Game,
    GameLifecycle,
    GameRepository,
    MaterializationState,
)
from wishicraft.naming import resource_name


class AwsSession(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


def initial_game(repository_root: Path, stage: str, *, now: datetime) -> Game:
    configuration = load_configuration(repository_root, stage)
    normalized_name = configuration.project.initial_game_display_name.lower().replace(" ", "-")
    return Game(
        game_id=configuration.project.initial_game_id,
        display_name=configuration.project.initial_game_display_name,
        normalized_display_name=normalized_name,
        lifecycle_state=GameLifecycle.ACTIVE,
        materialization_state=MaterializationState.MATERIALIZED,
        package_id="vanilla",
        package_version="initial-fixed-version",
        runtime_class="default",
        idle_shutdown_minutes=configuration.stage.idle_shutdown_minutes,
        world_generation=1,
        created_at=now,
        updated_at=now,
    )


def register_initial_game(repository_root: Path, stage: str, *, now: datetime) -> None:
    configuration = load_configuration(repository_root, stage)
    boto3 = importlib.import_module("boto3")
    session = cast(AwsSession, boto3)
    dynamodb = cast(
        DynamoApi,
        session.client("dynamodb", region_name=configuration.stage.aws_region),
    )
    table_name = resource_name(configuration.project.resource_prefix, stage, "games")
    GameRepository(dynamodb, table_name=table_name).register(
        initial_game(repository_root, stage, now=now)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("dev", "prod"))
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    register_initial_game(repository_root, cast(str, args.stage), now=datetime.now(UTC))


if __name__ == "__main__":
    main()
