"""Phase 1 Minecraft EC2 instance and its disposable root volume."""

from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

from infrastructure.constructs.minecraft_instance_role import MinecraftInstanceRole
from infrastructure.constructs.network import Network
from wishicraft.config import StageConfig


class MinecraftInstance(Construct):
    """Create the Minecraft host without data storage or bootstrap configuration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        network: Network,
        instance_role: MinecraftInstanceRole,
        stage: StageConfig,
    ) -> None:
        super().__init__(scope, construct_id)
        if stage.architecture != "x86_64":
            raise ValueError(f"Unsupported Phase 1 architecture: {stage.architecture}")
        if stage.operating_system != "amazon-linux-2023":
            raise ValueError(f"Unsupported Phase 1 operating system: {stage.operating_system}")
        if stage.root_volume_type != "gp3":
            raise ValueError(f"Unsupported Phase 1 root volume type: {stage.root_volume_type}")

        machine_image = ec2.AmazonLinuxImage(
            generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2023,
            cpu_type=ec2.AmazonLinuxCpuType.X86_64,
        )
        self.instance_profile = iam.CfnInstanceProfile(
            self,
            "InstanceProfile",
            roles=[instance_role.role.role_name],
        )
        self.instance = ec2.CfnInstance(
            self,
            "Instance",
            image_id=machine_image.get_image(self).image_id,
            instance_type=stage.instance_type,
            iam_instance_profile=self.instance_profile.ref,
            availability_zone=stage.availability_zone,
            network_interfaces=[
                ec2.CfnInstance.NetworkInterfaceProperty(
                    associate_public_ip_address=True,
                    device_index="0",
                    group_set=[network.minecraft_security_group.security_group_id],
                    subnet_id=network.vpc.public_subnets[0].subnet_id,
                )
            ],
            block_device_mappings=[
                ec2.CfnInstance.BlockDeviceMappingProperty(
                    device_name="/dev/xvda",
                    ebs=ec2.CfnInstance.EbsProperty(
                        delete_on_termination=True,
                        encrypted=stage.root_volume_encrypted,
                        volume_size=stage.root_volume_size_gib,
                        volume_type=stage.root_volume_type,
                    ),
                )
            ],
            instance_initiated_shutdown_behavior="stop",
            metadata_options=ec2.CfnInstance.MetadataOptionsProperty(
                http_tokens="required",
                instance_metadata_tags="disabled",
            ),
            monitoring=False,
        )
