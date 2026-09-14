"""Real preview shape with synthetic policy read-back and negative review cases."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App
from aws_cdk.assertions import Template

from infrastructure.stacks.minecraft_target_stack import MinecraftTargetStack
from wishicraft.config import load_configuration
from wishicraft.host_capacity_review import review

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, Any]:
    config = load_configuration(ROOT, "dev")
    stack = MinecraftTargetStack(
        App(outdir=str(tmp_path / "cdk")), stage=config.stage, project=config.project
    )
    live = dict(Template.from_stack(stack).to_json())
    live["Resources"]["TargetInstance"]["Properties"]["InstanceType"] = "t3a.medium"
    candidate = deepcopy(live)
    candidate["Resources"]["TargetInstance"]["Properties"]["InstanceType"] = "m8a.large"
    evidence = json.loads(
        (ROOT / "docs/evidence/host_capacity_preview_2026-09-14.json").read_text()
    )
    policy = json.loads((ROOT / "config/stack-policies/target.json").read_text())
    return {
        "live": live,
        "candidate": candidate,
        "change_set": evidence["change_set"],
        "policy_response": {"StackPolicyBody": json.dumps(policy)},
        "canonical_policy": policy,
        "stack_id": evidence["change_set"]["StackId"],
        "instance_id": evidence["instance"]["InstanceId"],
    }


def test_real_conditional_shape_with_synthetic_policy(inputs: dict[str, Any]) -> None:
    review(**inputs)


@pytest.mark.parametrize(
    "property_name",
    [
        "ImageId",
        "AvailabilityZone",
        "NetworkInterfaces",
        "CpuOptions",
        "LaunchTemplate",
        "BlockDeviceMappings",
        "KeyName",
        "SubnetId",
    ],
)
def test_other_template_changes_rejected(inputs: dict[str, Any], property_name: str) -> None:
    inputs["candidate"]["Resources"]["TargetInstance"]["Properties"][property_name] = "changed"
    with pytest.raises(ValueError, match="beyond InstanceType"):
        review(**inputs)


@pytest.mark.parametrize(
    "case",
    [
        "policy_absent",
        "policy_weakened",
        "wrong_stack",
        "wrong_instance",
        "pagination",
        "executed",
        "replace",
        "delete",
        "other_resource",
        "other_trigger",
        "other_source",
        "missing_instance",
        "wrong_type",
    ],
)
def test_unsafe_reviews_rejected(inputs: dict[str, Any], case: str) -> None:
    cs = inputs["change_set"]
    rc = next(
        c["ResourceChange"]
        for c in cs["Changes"]
        if c["ResourceChange"]["LogicalResourceId"] == "TargetInstance"
    )
    if case == "policy_absent":
        inputs["policy_response"] = {}
    elif case == "policy_weakened":
        inputs["policy_response"]["StackPolicyBody"] = '{"Statement": []}'
    elif case == "wrong_stack":
        inputs["stack_id"] = "other-stack"
    elif case == "wrong_instance":
        inputs["instance_id"] = "other-instance"
    elif case == "pagination":
        cs["NextToken"] = "unread-page"
    elif case == "executed":
        cs["ExecutionStatus"] = "EXECUTE_COMPLETE"
    elif case == "replace":
        rc["Replacement"] = "True"
    elif case == "delete":
        rc["Action"] = "Remove"
    elif case == "other_resource":
        rc["LogicalResourceId"] = "OtherInstance"
    elif case == "other_trigger":
        rc["Details"][0]["Target"]["Name"] = "ImageId"
    elif case == "other_source":
        rc["Details"][0]["CausingEntity"] = "OtherResource"
    elif case == "missing_instance":
        cs["Changes"] = []
    elif case == "wrong_type":
        rc["Details"][0]["Target"]["AfterValue"] = "r8a.large"
    with pytest.raises(ValueError):
        review(**inputs)


def test_permanent_policy_protects_exact_resources_only() -> None:
    policy = json.loads((ROOT / "config/stack-policies/target.json").read_text())
    allow, deny = policy["Statement"]
    assert allow == {"Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*"}
    assert deny == {
        "Effect": "Deny",
        "Action": ["Update:Replace", "Update:Delete"],
        "Principal": "*",
        "Resource": [
            "LogicalResourceId/TargetInstance",
            "LogicalResourceId/TargetDataVolumeAttachment",
        ],
    }
    data = json.loads((ROOT / "config/stack-policies/data-volume-dev.json").read_text())
    assert data["Statement"] == [
        allow,
        {**deny, "Resource": "LogicalResourceId/MinecraftDataVolume30BACD41"},
    ]


def test_boot_cannot_start_canonical_minecraft_unit() -> None:
    text = (ROOT / "infrastructure/host_runtime/wishicraft-targeted-runtime.service").read_text()
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    assert "Restart=no" in lines
    assert "[Install]" not in lines
    assert not any(line.startswith(("WantedBy=", "RequiredBy=")) for line in lines)
    assert "EnvironmentFile=/run/wishicraft/runtime-run.env" in lines
