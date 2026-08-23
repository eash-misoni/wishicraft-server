"""Isolated Phase 2 target host stack with no data-volume dependency."""

from __future__ import annotations

from aws_cdk import CfnOutput, Environment, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from constructs import Construct

from wishicraft.config import ConfigValidationError, ProjectConfig, StageConfig
from wishicraft.naming import resource_tags


class MinecraftTargetStack(Stack):
    """Create one disposable root-only target host for Phase 2 validation."""

    def __init__(
        self,
        scope: Construct,
        *,
        stage: StageConfig,
        project: ProjectConfig,
    ) -> None:
        values = {
            key: stage.host_runtime_value(key)
            for key in (
                "target_host.stack_name",
                "target_host.vpc_id",
                "target_host.subnet_id",
                "target_host.instance_type",
                "target_host.root_volume_type",
                "target_host.root_volume_size_gib",
                "target_host.root_volume_encrypted",
                "platform.ami_id",
                "platform.architecture",
            )
        }
        expected = {
            "target_host.stack_name": f"MinecraftTargetStack-{stage.stage}",
            "target_host.instance_type": "t3a.medium",
            "target_host.root_volume_type": "gp3",
            "target_host.root_volume_size_gib": 16,
            "target_host.root_volume_encrypted": True,
            "platform.architecture": "x86_64",
        }
        errors = [
            f"host_runtime.{key} must equal {value!r}"
            for key, value in expected.items()
            if values[key] != value
        ]
        for key in ("target_host.vpc_id", "target_host.subnet_id", "platform.ami_id"):
            if not isinstance(values[key], str) or not values[key]:
                errors.append(f"host_runtime.{key} must be a non-empty explicit ID")
        if errors:
            raise ConfigValidationError(errors)

        super().__init__(
            scope,
            str(values["target_host.stack_name"]),
            env=Environment(account=stage.aws_account_id, region=stage.aws_region),
            description="Isolated root-only Phase 2 target host; no Minecraft data EBS",
        )
        raw_tags = project.values["resource_tags"]
        assert isinstance(raw_tags, dict)
        tags = resource_tags(
            {key: value for key, value in raw_tags.items() if isinstance(value, str)},
            stage.stage,
        )
        for key, value in tags.items():
            Tags.of(self).add(key, value)
        Tags.of(self).add("Purpose", "phase2-target-validation")

        role = iam.Role(
            self,
            "TargetManagedNodeRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Phase 2 target SSM managed node only",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ],
        )
        profile = iam.CfnInstanceProfile(self, "TargetInstanceProfile", roles=[role.role_name])
        security_group = ec2.CfnSecurityGroup(
            self,
            "TargetSecurityGroup",
            group_description="Phase 2 target host with zero ingress",
            vpc_id=str(values["target_host.vpc_id"]),
            security_group_egress=[
                ec2.CfnSecurityGroup.EgressProperty(
                    ip_protocol="tcp",
                    from_port=443,
                    to_port=443,
                    cidr_ip="0.0.0.0/0",
                    description="HTTPS for SSM, AL2023 repositories, GitHub, and GHCR",
                )
            ],
        )
        instance = ec2.CfnInstance(
            self,
            "TargetInstance",
            image_id=str(values["platform.ami_id"]),
            instance_type=str(values["target_host.instance_type"]),
            iam_instance_profile=profile.ref,
            availability_zone=stage.availability_zone,
            network_interfaces=[
                ec2.CfnInstance.NetworkInterfaceProperty(
                    associate_public_ip_address=True,
                    device_index="0",
                    group_set=[security_group.attr_group_id],
                    subnet_id=str(values["target_host.subnet_id"]),
                )
            ],
            block_device_mappings=[
                ec2.CfnInstance.BlockDeviceMappingProperty(
                    device_name="/dev/xvda",
                    ebs=ec2.CfnInstance.EbsProperty(
                        delete_on_termination=True,
                        encrypted=True,
                        volume_size=16,
                        volume_type="gp3",
                    ),
                )
            ],
            instance_initiated_shutdown_behavior="stop",
            metadata_options=ec2.CfnInstance.MetadataOptionsProperty(
                http_tokens="required", instance_metadata_tags="disabled"
            ),
            monitoring=False,
        )
        CfnOutput(self, "TargetInstanceId", value=instance.ref)
        CfnOutput(self, "TargetSecurityGroupId", value=security_group.attr_group_id)
        CfnOutput(self, "TargetRoleName", value=role.role_name)
