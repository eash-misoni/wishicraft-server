from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.config import ConfigValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_dev_stack_is_empty_and_environment_agnostic() -> None:
    app = build_app(REPOSITORY_ROOT, "dev")

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    assert template.find_resources("AWS::EC2::Instance") == {}
    assert stack.environment == "aws://unknown-account/unknown-region"


def test_phase_one_dev_synth_uses_confirmed_settings_without_account_binding() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    assert stack.environment == "aws://unknown-account/unknown-region"


def test_phase_one_dev_deploy_validation_uses_confirmed_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1, action="deploy")

    assert app.node.find_child("MinecraftStack-dev")


def test_prod_stack_is_rejected_before_synthesis() -> None:
    with pytest.raises(ConfigValidationError, match="aws.account_id"):
        build_app(REPOSITORY_ROOT, "prod")
