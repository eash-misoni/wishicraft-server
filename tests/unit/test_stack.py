from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.config import ConfigValidationError, load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _action_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    assert isinstance(value, list)
    assert all(isinstance(action, str) for action in value)
    return cast(list[str], value)


def test_dev_stack_is_empty_and_environment_agnostic() -> None:
    app = build_app(REPOSITORY_ROOT, "dev")

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    assert template.find_resources("AWS::EC2::Instance") == {}
    assert stack.environment == "aws://unknown-account/unknown-region"


def test_phase_one_network_uses_configured_public_subnet_and_internet_gateway() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    assert stack.environment == "aws://unknown-account/unknown-region"
    template.resource_count_is("AWS::EC2::Subnet", 1)
    template.resource_count_is("AWS::EC2::InternetGateway", 1)

    subnet = next(iter(template.find_resources("AWS::EC2::Subnet").values()))
    assert subnet["Properties"]["AvailabilityZone"] == configuration.stage.availability_zone

    internet_gateway_ids = set(template.find_resources("AWS::EC2::InternetGateway"))
    routes = template.find_resources("AWS::EC2::Route")
    assert any(
        route["Properties"].get("GatewayId", {}).get("Ref") in internet_gateway_ids
        for route in routes.values()
    )


def test_phase_one_network_allows_only_configured_minecraft_tcp_ingress() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    security_groups = template.find_resources("AWS::EC2::SecurityGroup")
    minecraft_group = next(
        group
        for group in security_groups.values()
        if group["Properties"]["GroupDescription"] == "Minecraft client ingress only"
    )
    ingress_rules = minecraft_group["Properties"]["SecurityGroupIngress"]
    assert ingress_rules == [
        {
            "CidrIp": "0.0.0.0/0",
            "Description": "Minecraft client connections",
            "FromPort": configuration.stage.minecraft_port,
            "IpProtocol": "tcp",
            "ToPort": configuration.stage.minecraft_port,
        }
    ]
    assert template.find_resources("AWS::EC2::NatGateway") == {}
    assert template.find_resources("AWS::EC2::EIP") == {}


def test_phase_one_minecraft_instance_role_has_only_required_ssm_permissions() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    roles = template.find_resources("AWS::IAM::Role")
    minecraft_role = next(
        role
        for role in roles.values()
        if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
    )
    principal = minecraft_role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0][
        "Principal"
    ]
    assert principal == {"Service": "ec2.amazonaws.com"}
    assert "ManagedPolicyArns" not in minecraft_role["Properties"]

    policies = template.find_resources("AWS::IAM::Policy")
    policy = next(iter(policies.values()))["Properties"]["PolicyDocument"]
    statements = policy["Statement"]
    actions = {action for statement in statements for action in _action_list(statement["Action"])}

    assert {
        "ssm:DescribeAssociation",
        "ssm:GetDocument",
        "ssm:UpdateInstanceInformation",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:OpenDataChannel",
        "ec2messages:GetMessages",
        "ec2messages:SendReply",
    } <= actions
    assert "ssm:GetParameter" in actions
    assert (
        not {
            "ssm:GetParameters",
            "ssm:GetParametersByPath",
            "ssm:GetParameterHistory",
            "ssm:DescribeParameters",
        }
        & actions
    )
    assert not any(
        action.startswith(prefix)
        for action in actions
        for prefix in ("kms:", "ec2:", "iam:", "route53:", "s3:", "dynamodb:", "logs:")
    )

    parameter_statement = next(
        statement
        for statement in statements
        if _action_list(statement["Action"]) == ["ssm:GetParameter"]
    )
    parameter_resource = parameter_statement["Resource"]
    assert parameter_resource != "*"
    parameter_resource_text = str(parameter_resource)
    assert configuration.stage.aws_region in parameter_resource_text
    assert configuration.stage.aws_account_id in parameter_resource_text
    assert ":parameter/" in parameter_resource_text
    assert "parameter//" not in parameter_resource_text
    assert configuration.secrets.rcon_password_parameter_name("dev") in parameter_resource_text
    assert "rcon-password" in parameter_resource_text
    assert not any(
        "ssm:GetParameter" in _action_list(statement["Action"]) and statement["Resource"] == "*"
        for statement in statements
    )

    template_text = str(template.to_json())
    assert "AmazonSSMManagedInstanceCore" not in template_text
    assert "rcon-password" in template_text
    assert "RCON_PASSWORD" not in template_text


def test_phase_one_minecraft_instance_uses_existing_network_role_and_root_ebs() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    instances = template.find_resources("AWS::EC2::Instance")
    assert len(instances) == 1
    instance = next(iter(instances.values()))["Properties"]
    assert instance["InstanceType"] == configuration.stage.instance_type
    assert "ami-" not in str(instance["ImageId"])
    image_parameter_id = instance["ImageId"]["Ref"]
    image_parameter = template.to_json()["Parameters"][image_parameter_id]
    assert image_parameter["Default"] == (
        "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    )
    network_interface = instance["NetworkInterfaces"][0]
    assert network_interface["SubnetId"] in [
        {"Ref": subnet_id} for subnet_id in template.find_resources("AWS::EC2::Subnet")
    ]
    assert network_interface["AssociatePublicIpAddress"] is True
    assert "KeyName" not in instance
    assert "UserData" not in instance
    assert instance["InstanceInitiatedShutdownBehavior"] == "stop"
    assert instance["Monitoring"] is False
    assert instance["MetadataOptions"] == {
        "HttpTokens": "required",
        "InstanceMetadataTags": "disabled",
    }

    security_groups = template.find_resources("AWS::EC2::SecurityGroup")
    minecraft_security_group_id = next(
        logical_id
        for logical_id, group in security_groups.items()
        if group["Properties"]["GroupDescription"] == "Minecraft client ingress only"
    )
    assert network_interface["GroupSet"] == [
        {"Fn::GetAtt": [minecraft_security_group_id, "GroupId"]}
    ]
    assert template.find_resources("AWS::EC2::EIP") == {}

    instance_profiles = template.find_resources("AWS::IAM::InstanceProfile")
    assert len(instance_profiles) == 1
    profile_id, profile = next(iter(instance_profiles.items()))
    role_id = next(
        logical_id
        for logical_id, role in template.find_resources("AWS::IAM::Role").items()
        if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
    )
    assert profile["Properties"]["Roles"] == [{"Ref": role_id}]
    assert instance["IamInstanceProfile"] == {"Ref": profile_id}
    assert len(template.find_resources("AWS::IAM::Role")) == 1
    assert (
        "ManagedPolicyArns"
        not in next(
            role
            for role in template.find_resources("AWS::IAM::Role").values()
            if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
        )["Properties"]
    )

    root_volume = instance["BlockDeviceMappings"]
    assert len(root_volume) == 1
    assert root_volume[0]["DeviceName"] == "/dev/xvda"
    root_ebs = root_volume[0]["Ebs"]
    assert root_ebs == {
        "DeleteOnTermination": True,
        "Encrypted": configuration.stage.root_volume_encrypted,
        "VolumeSize": configuration.stage.root_volume_size_gib,
        "VolumeType": configuration.stage.root_volume_type,
    }
    assert "rcon-password" not in str(instance)


def test_phase_one_minecraft_data_volume_is_retained_and_attached_to_the_instance() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    volumes = template.find_resources("AWS::EC2::Volume")
    assert len(volumes) == 1
    volume_id, volume = next(iter(volumes.items()))
    volume_properties = volume["Properties"]
    assert volume_properties["AvailabilityZone"] == configuration.stage.availability_zone
    assert volume_properties["Encrypted"] is configuration.stage.data_volume_encrypted
    assert volume_properties["Size"] == configuration.stage.data_volume_size_gib
    assert volume_properties["VolumeType"] == configuration.stage.data_volume_type
    assert volume["DeletionPolicy"] == "Retain"
    assert volume["UpdateReplacePolicy"] == "Retain"
    assert not {
        "Iops",
        "KmsKeyId",
        "MultiAttachEnabled",
        "SnapshotId",
        "Throughput",
    } & set(volume_properties)

    instance = next(iter(template.find_resources("AWS::EC2::Instance").items()))
    instance_id, instance_definition = instance
    instance_properties = instance_definition["Properties"]
    subnet = next(iter(template.find_resources("AWS::EC2::Subnet").values()))["Properties"]
    assert volume_properties["AvailabilityZone"] == subnet["AvailabilityZone"]
    assert volume_properties["AvailabilityZone"] == instance_properties["AvailabilityZone"]
    assert len(instance_properties["BlockDeviceMappings"]) == 1
    assert instance_properties["BlockDeviceMappings"][0]["DeviceName"] == "/dev/xvda"

    attachments = template.find_resources("AWS::EC2::VolumeAttachment")
    assert len(attachments) == 1
    attachment = next(iter(attachments.values()))
    assert attachment["Properties"] == {
        "Device": "/dev/sdf",
        "InstanceId": {"Ref": instance_id},
        "VolumeId": {"Ref": volume_id},
    }
    assert "DeletionPolicy" not in attachment
    assert "UpdateReplacePolicy" not in attachment
    assert "UserData" not in instance_properties
    assert len(template.find_resources("AWS::IAM::Role")) == 1
    assert len(template.find_resources("AWS::EC2::SecurityGroup")) == 1
    assert template.find_resources("AWS::KMS::Key") == {}


def test_phase_one_dev_deploy_validation_uses_confirmed_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1, action="deploy")

    assert app.node.find_child("MinecraftStack-dev")


def test_prod_stack_is_rejected_before_synthesis() -> None:
    with pytest.raises(ConfigValidationError, match="aws.account_id"):
        build_app(REPOSITORY_ROOT, "prod")
