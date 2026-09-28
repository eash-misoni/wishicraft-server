from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App
from aws_cdk.assertions import Template

from infrastructure.app import retention_input
from infrastructure.stacks.control_plane_stack import ControlPlaneStack
from wishicraft.config import load_configuration
from wishicraft.retention_release import RetentionRelease

ROOT = Path(__file__).resolve().parents[2]


def template(release: RetentionRelease) -> dict[str, Any]:
    c = load_configuration(ROOT, "dev")
    app = App()
    stack = ControlPlaneStack(
        app,
        project=c.project,
        stage=c.stage,
        secrets=c.secrets,
        phase=8,
        games=("game-vanilla-main", "game-vanilla-secondary"),
        retention_release=release,
    )
    return dict(Template.from_stack(stack).to_json()["Resources"])


def test_two_stage_properties_and_canonical_no_delete_iam() -> None:
    off, a, b = [
        template(r)
        for r in (RetentionRelease(), RetentionRelease(True, False), RetentionRelease(True, True))
    ]
    assert off.keys() == a.keys() == b.keys()
    assert "ec2:DeleteSnapshot" not in json.dumps(off)
    assert "ec2:DeleteSnapshot" not in json.dumps(a)
    assert "ec2:DeleteSnapshot" in json.dumps(b)
    for key in off:
        if key.startswith("RetentionTaskFunction") and off[key]["Type"] in {
            "AWS::Lambda::Function",
            "AWS::IAM::Policy",
        }:
            continue
        if key.startswith("RetentionStateMachine"):
            assert off[key] == a[key]
            assert "execution_mode" not in json.dumps(a[key])
            assert "DELETE_ONE" in json.dumps(b[key])
            continue
        assert off[key] == a[key] == b[key]
    fn = next(
        k
        for k in off
        if k.startswith("RetentionTaskFunction") and off[k]["Type"] == "AWS::Lambda::Function"
    )
    assert "RETENTION_DELETE_ENABLED" not in off[fn]["Properties"]["Environment"]["Variables"]
    assert a[fn]["Properties"]["Environment"]["Variables"]["RETENTION_DELETE_ENABLED"] == "0"
    assert b[fn]["Properties"]["Environment"]["Variables"]["RETENTION_DELETE_ENABLED"] == "1"
    policies = [k for k in b if "ec2:DeleteSnapshot" in json.dumps(b[k])]
    assert len(policies) == 1 and policies[0].startswith("RetentionTaskFunction")


def test_validation_is_explicit_not_a_deployment_override() -> None:
    assert retention_input(ROOT, "dev") == RetentionRelease()
    assert retention_input(ROOT, "dev", validation="provisioned") == RetentionRelease(True, False)
    assert retention_input(ROOT, "dev", validation="enabled") == RetentionRelease(True, True)
    with pytest.raises(ValueError):
        retention_input(ROOT, "dev", validation="enabled", action="deploy")


def test_single_game_provision_rejected() -> None:
    c = load_configuration(ROOT, "dev")
    with pytest.raises(ValueError, match="shared runtime"):
        ControlPlaneStack(
            App(),
            project=c.project,
            stage=c.stage,
            secrets=c.secrets,
            phase=8,
            retention_release=RetentionRelease(True, False),
        )
