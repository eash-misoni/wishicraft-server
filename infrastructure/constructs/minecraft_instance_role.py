"""Least-privilege IAM role for the future Minecraft EC2 instance."""

from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

from wishicraft.config import StageConfig


class MinecraftInstanceRole(Construct):
    """Create the EC2 role without creating or attaching an instance profile."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: StageConfig,
        rcon_parameter_name: str,
    ) -> None:
        super().__init__(scope, construct_id)

        self.role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Minecraft EC2 managed node role",
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:DescribeAssociation",
                    "ssm:DescribeDocument",
                    "ssm:GetDeployablePatchSnapshotForInstance",
                    "ssm:GetDocument",
                    "ssm:GetManifest",
                    "ssm:ListAssociations",
                    "ssm:ListInstanceAssociations",
                    "ssm:PutComplianceItems",
                    "ssm:PutConfigurePackageResult",
                    "ssm:PutInventory",
                    "ssm:UpdateAssociationStatus",
                    "ssm:UpdateInstanceAssociationStatus",
                    "ssm:UpdateInstanceInformation",
                ],
                resources=["*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ec2messages:AcknowledgeMessage",
                    "ec2messages:DeleteMessage",
                    "ec2messages:FailMessage",
                    "ec2messages:GetEndpoint",
                    "ec2messages:GetMessages",
                    "ec2messages:SendReply",
                ],
                resources=["*"],
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    Stack.of(self).format_arn(
                        service="ssm",
                        region=stage.aws_region,
                        account=stage.aws_account_id,
                        resource="parameter",
                        resource_name=rcon_parameter_name.removeprefix("/"),
                    )
                ],
            )
        )
