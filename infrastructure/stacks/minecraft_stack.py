"""The single per-stage CDK stack used during the initial delivery phases."""

from __future__ import annotations

from aws_cdk import Stack, Tags
from constructs import Construct

from infrastructure.constructs.data_volume_bootstrap import DataVolumeBootstrap
from infrastructure.constructs.minecraft_data_volume import MinecraftDataVolume
from infrastructure.constructs.minecraft_instance import MinecraftInstance
from infrastructure.constructs.minecraft_instance_role import MinecraftInstanceRole
from infrastructure.constructs.network import Network
from wishicraft.config import ProjectConfig, SecretsExampleConfig, StageConfig
from wishicraft.naming import resource_tags


class MinecraftStack(Stack):
    """The single per-stage stack, composed from phase-specific constructs."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project: ProjectConfig,
        stage: StageConfig,
        secrets: SecretsExampleConfig,
        phase: int = 0,
    ) -> None:
        super().__init__(scope, construct_id)
        raw_tags = project.values["resource_tags"]
        assert isinstance(raw_tags, dict)
        project_tags = {key: value for key, value in raw_tags.items() if isinstance(value, str)}
        tags = resource_tags(project_tags, stage.stage)
        for key, value in tags.items():
            Tags.of(self).add(key, value)

        if phase >= 1:
            self.network = Network(self, "Network", stage=stage)
            self.minecraft_instance_role = MinecraftInstanceRole(
                self,
                "MinecraftInstanceRole",
                stage=stage,
                rcon_parameter_name=secrets.rcon_password_parameter_name(stage.stage),
            )
            self.minecraft_instance = MinecraftInstance(
                self,
                "MinecraftInstance",
                network=self.network,
                instance_role=self.minecraft_instance_role,
                stage=stage,
            )
            self.minecraft_data_volume = MinecraftDataVolume(
                self,
                "MinecraftDataVolume",
                instance=self.minecraft_instance,
                stage=stage,
            )
            self.data_volume_bootstrap = DataVolumeBootstrap(
                self,
                "DataVolumeBootstrap",
                instance=self.minecraft_instance,
                data_volume=self.minecraft_data_volume,
                project=project,
                stage=stage,
            )
