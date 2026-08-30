"""Deterministic Lambda asset bundling for the PyNaCl Discord verifier."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsii
from aws_cdk import (
    BundlingFileAccess,
    BundlingOptions,
    BundlingOutput,
    DockerImage,
    DockerVolume,
    ILocalBundling,
)
from aws_cdk import aws_lambda as lambda_


@jsii.implements(ILocalBundling)
class UvDiscordCommandBundling:
    def __init__(self, repository_root: Path) -> None:
        self._root = repository_root

    def try_bundle(
        self,
        output_dir: str,
        *,
        image: DockerImage,
        bundling_file_access: BundlingFileAccess | None = None,
        command: Sequence[str] | None = None,
        entrypoint: Sequence[str] | None = None,
        environment: Mapping[str, str] | None = None,
        local: ILocalBundling | None = None,
        network: str | None = None,
        output_type: BundlingOutput | None = None,
        platform: str | None = None,
        security_opt: str | None = None,
        user: str | None = None,
        volumes: Sequence[DockerVolume | dict[str, Any]] | None = None,
        volumes_from: Sequence[str] | None = None,
        working_directory: str | None = None,
    ) -> bool:
        del (
            image,
            bundling_file_access,
            command,
            entrypoint,
            environment,
            local,
            network,
            output_type,
            platform,
            security_opt,
            user,
            volumes,
            volumes_from,
            working_directory,
        )
        uv = shutil.which("uv")
        if uv is None:
            return False
        output = Path(output_dir)
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--target",
                str(output),
                "--python-platform",
                "x86_64-manylinux2014",
                "--python-version",
                "3.12",
                "--only-binary",
                ":all:",
                "--require-hashes",
                "--requirements",
                str(self._root / "infrastructure" / "lambda" / "discord-command-requirements.lock"),
            ],
            check=True,
        )
        shutil.copytree(self._root / "src" / "wishicraft", output / "wishicraft")
        schema_target = output / "config" / "discord"
        schema_target.mkdir(parents=True)
        shutil.copy2(
            self._root / "config" / "discord" / "commands.v1.json",
            schema_target / "commands.v1.json",
        )
        return True


def discord_command_bundling(repository_root: Path) -> BundlingOptions:
    return BundlingOptions(
        image=lambda_.Runtime.PYTHON_3_12.bundling_image,
        local=UvDiscordCommandBundling(repository_root),
        command=[
            "bash",
            "-c",
            (
                "python -m pip install --require-hashes --only-binary=:all: "
                "-r /asset-input/infrastructure/lambda/discord-command-requirements.lock "
                "-t /asset-output && "
                "cp -R /asset-input/src/wishicraft /asset-output/wishicraft && "
                "mkdir -p /asset-output/config/discord && "
                "cp /asset-input/config/discord/commands.v1.json "
                "/asset-output/config/discord/commands.v1.json"
            ),
        ],
    )
