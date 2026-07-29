from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.config import ConfigValidationError, load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


def test_phase_one_dev_deploy_validation_uses_confirmed_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1, action="deploy")

    assert app.node.find_child("MinecraftStack-dev")


def test_prod_stack_is_rejected_before_synthesis() -> None:
    with pytest.raises(ConfigValidationError, match="aws.account_id"):
        build_app(REPOSITORY_ROOT, "prod")
