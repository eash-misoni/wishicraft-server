from __future__ import annotations

from pathlib import Path
from typing import cast

from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app

ROOT = Path(__file__).resolve().parents[2]


def test_control_plane_runtime_heartbeats_table_is_retained_ttl_enabled_and_minimal() -> None:
    template = Template.from_stack(
        cast(
            Stack,
            build_app(ROOT, "dev", phase=8, deployment="control-plane").node.find_child(
                "WishicraftControlPlaneStack-dev"
            ),
        )
    ).to_json()
    tables = [
        value
        for value in template["Resources"].values()
        if value["Type"] == "AWS::DynamoDB::Table"
        and value["Properties"].get("TableName") == "wc-dev-runtime-heartbeats"
    ]
    assert len(tables) == 1
    table = tables[0]
    assert table["DeletionPolicy"] == "Retain"
    assert table["UpdateReplacePolicy"] == "Retain"
    assert table["Properties"]["KeySchema"] == [{"AttributeName": "system_id", "KeyType": "HASH"}]
    assert table["Properties"]["TimeToLiveSpecification"] == {
        "AttributeName": "expires_at",
        "Enabled": True,
    }
    assert "GlobalSecondaryIndexes" not in table["Properties"]
    assert "StreamSpecification" not in table["Properties"]


def test_target_role_can_only_get_and_conditionally_put_canonical_heartbeat() -> None:
    stack = cast(
        Stack,
        build_app(ROOT, "dev", phase=8, deployment="target").node.find_child(
            "MinecraftTargetStack-dev"
        ),
    )
    template = Template.from_stack(stack).to_json()
    policies = [
        statement
        for value in template["Resources"].values()
        if value["Type"] == "AWS::IAM::Policy"
        for statement in value["Properties"]["PolicyDocument"]["Statement"]
    ]
    heartbeat = [
        statement
        for statement in policies
        if statement.get("Action") == ["dynamodb:GetItem", "dynamodb:PutItem"]
    ]
    assert len(heartbeat) == 1
    assert heartbeat[0]["Resource"] == (
        "arn:aws:dynamodb:ap-northeast-1:385526546525:table/wc-dev-runtime-heartbeats"
    )
    assert heartbeat[0]["Condition"] == {
        "ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["wishicraft-main"]}
    }
    serialized = str(heartbeat)
    for forbidden in (
        "Scan",
        "Query",
        "UpdateItem",
        "DeleteItem",
        "TransactWriteItems",
        "StartInstances",
        "StopInstances",
        "Route53",
        "SendCommand",
        "Snapshot",
    ):
        assert forbidden not in serialized


def test_heartbeat_does_not_change_target_instance_or_attachment_contract() -> None:
    stack = cast(
        Stack,
        build_app(ROOT, "dev", phase=8, deployment="target").node.find_child(
            "MinecraftTargetStack-dev"
        ),
    )
    template = Template.from_stack(stack).to_json()
    instances = [v for v in template["Resources"].values() if v["Type"] == "AWS::EC2::Instance"]
    attachments = [
        v for v in template["Resources"].values() if v["Type"] == "AWS::EC2::VolumeAttachment"
    ]
    assert len(instances) == 1
    assert len(attachments) == 1
    assert attachments[0]["DeletionPolicy"] == "Retain"
