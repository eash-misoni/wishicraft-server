"""Retained data EBS volume for the future Minecraft filesystem setup."""

from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from infrastructure.constructs.minecraft_instance import MinecraftInstance
from wishicraft.config import StageConfig


class MinecraftDataVolume(Construct):
    """Create and attach the retained Minecraft data volume without mounting it."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance: MinecraftInstance,
        stage: StageConfig,
    ) -> None:
        super().__init__(scope, construct_id)
        if stage.data_volume_type != "gp3":
            raise ValueError(f"Unsupported Phase 1 data volume type: {stage.data_volume_type}")
        if not stage.data_volume_retain_on_delete:
            raise ValueError("Phase 1 data volume retention must remain enabled")

        self.volume = ec2.CfnVolume(
            self,
            "Volume",
            availability_zone=stage.availability_zone,
            encrypted=stage.data_volume_encrypted,
            size=stage.data_volume_size_gib,
            volume_type=stage.data_volume_type,
        )
        self.volume.apply_removal_policy(RemovalPolicy.RETAIN)
        self.attachment = ec2.CfnVolumeAttachment(
            self,
            "Attachment",
            device="/dev/sdf",
            instance_id=instance.instance.ref,
            volume_id=self.volume.ref,
        )
