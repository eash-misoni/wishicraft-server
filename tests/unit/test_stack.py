from __future__ import annotations

import base64
import gzip
from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.config import ConfigValidationError, load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _find_key(value: object, key: str, path: str = "$") -> list[tuple[str, object]]:
    matches: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_path = f"{path}.{child_key}"
            if child_key == key:
                matches.append((child_path, child_value))
            matches.extend(_find_key(child_value, key, child_path))
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            matches.extend(_find_key(child_value, key, f"{path}[{index}]"))
    return matches


def _resolve_user_data(value: object, references: dict[str, str]) -> str:
    if isinstance(value, str):
        return value
    assert isinstance(value, dict)
    if set(value) == {"Fn::Join"}:
        delimiter, values = value["Fn::Join"]
        assert isinstance(delimiter, str)
        assert isinstance(values, list)
        return delimiter.join(_resolve_user_data(item, references) for item in values)
    if set(value) == {"Ref"}:
        reference = value["Ref"]
        assert isinstance(reference, str)
        return references[reference]
    raise AssertionError(f"Unsupported UserData expression: {value!r}")


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
    instance_id, instance_resource = next(iter(instances.items()))
    instance = instance_resource["Properties"]
    template.has_output("MinecraftInstanceId", {"Value": {"Ref": instance_id}})
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
    assert "UserData" in instance
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
    assert "/wishicraft/dev/secret/rcon-password" in str(instance)
    assert "{{resolve:ssm-secure:" not in str(instance)


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
    assert len(template.find_resources("AWS::IAM::Role")) == 1
    assert len(template.find_resources("AWS::EC2::SecurityGroup")) == 1
    assert template.find_resources("AWS::KMS::Key") == {}


def test_phase_one_data_volume_bootstrap_uses_volume_ref_and_preserves_ec2_invariants() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    volume_id = next(iter(template.find_resources("AWS::EC2::Volume")))
    instance = next(iter(template.find_resources("AWS::EC2::Instance").values()))["Properties"]
    user_data = instance["UserData"]
    user_data_matches = _find_key(template.to_json(), "UserData")
    assert len(user_data_matches) == 1, user_data_matches
    user_data_path, synthesized_user_data = user_data_matches[0]
    assert user_data_path.endswith(".Properties.UserData")
    assert synthesized_user_data == user_data
    assert {"Fn::Base64"} == set(user_data)
    user_data_text = _resolve_user_data(
        user_data["Fn::Base64"],
        {volume_id: "vol-00000000000000000"},
    )
    assert any(reference == volume_id for _, reference in _find_key(user_data["Fn::Base64"], "Ref"))
    assert configuration.stage.data_volume_mount_path in user_data_text
    assert configuration.stage.data_volume_filesystem_type in user_data_text
    assert "wishicraft-data-volume.service" in user_data_text
    assert "DATA_VOLUME_ID=" in user_data_text
    assert configuration.stage.java_runtime in user_data_text
    assert "base64 -d" in user_data_text
    assert "| gzip -d > /usr/local/sbin/wishicraft-bootstrap-runner" in user_data_text
    encoded_runner = user_data_text.split("printf '%s' '", 1)[1].split("' | base64 -d", 1)[0]
    runner = gzip.decompress(base64.b64decode(encoded_runner)).decode("utf-8")
    assert runner == (REPOSITORY_ROOT / "infrastructure/bootstrap/bootstrap_runner.sh").read_text(
        encoding="utf-8"
    )
    assert "sha256sum -c -" in runner
    assert "data_volume_mount.sh" in user_data_text
    assert "java_runtime_install.sh" in user_data_text
    assert "minecraft_artifact_install.sh" in user_data_text
    assert "minecraft_game_setup.sh" in user_data_text
    assert "minecraft_rcon_configure.sh" in user_data_text
    assert "minecraft_rcon_firewall.sh" in user_data_text
    assert "WISHICRAFT_DATA_VOLUME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_JAVA_RUNTIME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_ARTIFACT_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_GAME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_RCON_SCRIPT" not in user_data_text
    assert "minecraft.service" in user_data_text
    minecraft_environment_start = user_data_text.index("cat > /etc/wishicraft/minecraft.env ")
    minecraft_environment_end = user_data_text.index(
        "WISHICRAFT_MINECRAFT_ENV\n", minecraft_environment_start
    )
    minecraft_environment = user_data_text[minecraft_environment_start:minecraft_environment_end]
    assert "DATA_VOLUME_ID=vol-00000000000000000" in minecraft_environment
    assert (
        f"FILESYSTEM_TYPE={configuration.stage.data_volume_filesystem_type}"
        in minecraft_environment
    )
    prepare_call = "/usr/local/lib/wishicraft/minecraft_game_setup.sh --prepare"
    exported_minecraft_environment = "set -a\n. /etc/wishicraft/minecraft.env\nset +a\n"
    service_enable = "systemctl enable --now wishicraft-data-volume.service"
    assert exported_minecraft_environment + prepare_call in user_data_text
    assert user_data_text.index(service_enable) < user_data_text.index("JAVA_RUNTIME=")
    assert user_data_text.index("JAVA_RUNTIME=") < user_data_text.index(prepare_call)
    assert user_data_text.index("JAVA_RUNTIME=") < user_data_text.rindex(
        "minecraft_artifact_install.sh"
    )
    assert user_data_text.index("minecraft_rcon_configure.sh\n") < user_data_text.index(
        "wishicraft-rcon-firewall.service"
    )
    assert user_data_text.index("wishicraft-rcon-firewall.service") < user_data_text.rindex(
        "systemctl enable --now minecraft.service"
    )
    assert "/dev/sdf" not in user_data_text
    assert configuration.secrets.rcon_password_parameter_name("dev") in user_data_text
    assert "{{resolve:ssm-secure:" not in user_data_text
    assert len(user_data_text.encode("utf-8")) <= 16 * 1024

    assert instance["InstanceInitiatedShutdownBehavior"] == "stop"
    assert instance["MetadataOptions"] == {
        "HttpTokens": "required",
        "InstanceMetadataTags": "disabled",
    }
    assert len(instance["BlockDeviceMappings"]) == 1
    assert template.find_resources("AWS::IAM::Role")
    assert template.find_resources("AWS::IAM::ManagedPolicy") == {}
    assert template.find_resources("AWS::KMS::Key") == {}
    assert len(template.find_resources("AWS::EC2::SecurityGroup")) == 1


def test_phase_one_minecraft_service_uses_mount_guard_and_fixed_runtime_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    instance = next(iter(template.find_resources("AWS::EC2::Instance").values()))["Properties"]
    user_data = _resolve_user_data(
        instance["UserData"]["Fn::Base64"],
        {next(iter(template.find_resources("AWS::EC2::Volume"))): ("vol-00000000000000000")},
    )

    assert "Requires=wishicraft-data-volume.service" in user_data
    assert "After=wishicraft-data-volume.service" in user_data
    assert "Requires=wishicraft-rcon-firewall.service" in user_data
    assert "After=wishicraft-data-volume.service wishicraft-rcon-firewall.service" in user_data
    assert "Before=minecraft.service" in user_data
    assert "ExecStartPre=+/usr/local/lib/wishicraft/data_volume_mount.sh --verify" in user_data
    assert "ExecStartPre=+/usr/local/lib/wishicraft/minecraft_game_setup.sh --verify" in user_data
    assert f"-Xms{configuration.stage.java_xms} -Xmx{configuration.stage.java_xmx}" in user_data
    assert " -jar /srv/minecraft/packages/vanilla/26.2/server.jar nogui" in user_data
    assert "User=minecraft" in user_data
    assert "TimeoutStopSec=180" in user_data


def test_phase_one_dev_deploy_validation_uses_confirmed_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1, action="deploy")

    assert app.node.find_child("MinecraftStack-dev")


def test_prod_stack_is_rejected_before_synthesis() -> None:
    with pytest.raises(ConfigValidationError, match="aws.account_id"):
        build_app(REPOSITORY_ROOT, "prod")
