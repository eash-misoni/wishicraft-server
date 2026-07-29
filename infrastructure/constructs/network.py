"""Phase 1 public network resources for the Minecraft EC2 instance."""

from __future__ import annotations

from aws_cdk import aws_ec2 as ec2
from constructs import Construct

from wishicraft.config import StageConfig


class Network(Construct):
    """Provide the configured public subnet and Minecraft-only ingress rule."""

    def __init__(self, scope: Construct, construct_id: str, *, stage: StageConfig) -> None:
        super().__init__(scope, construct_id)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            availability_zones=[stage.availability_zone],
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )
        self.minecraft_security_group = ec2.SecurityGroup(
            self,
            "MinecraftSecurityGroup",
            vpc=self.vpc,
            description="Minecraft client ingress only",
            allow_all_outbound=True,
        )
        self.minecraft_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(stage.minecraft_port),
            "Minecraft client connections",
        )
