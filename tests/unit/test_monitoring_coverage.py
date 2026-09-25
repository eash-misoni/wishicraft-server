"""Four independent notification paths; retain the existing Web evaluation contract."""

from pathlib import Path
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.maintenance import SUPPRESSIBLE

ROOT = Path(__file__).resolve().parents[2]


def resources(deployment: str, phase: int = 8) -> dict[str, Any]:
    app = build_app(ROOT, "dev", phase=phase, deployment=deployment)
    name = "WishicraftWebStack-dev" if deployment == "web" else "WishicraftControlPlaneStack-dev"
    return cast(
        dict[str, Any],
        Template.from_stack(cast(Stack, app.node.find_child(name))).to_json()["Resources"],
    )


@pytest.mark.parametrize("phase", [7, 8])
def test_each_existing_dlq_has_independent_visible_alarm(phase: int) -> None:
    rs = resources("control-plane", phase)
    queues = {k: v["Properties"] for k, v in rs.items() if v["Type"] == "AWS::SQS::Queue"}
    alarms = {
        k: v["Properties"]
        for k, v in rs.items()
        if v["Type"] == "AWS::CloudWatch::Alarm" and v["Properties"].get("Namespace") == "AWS/SQS"
    }
    assert len(alarms) == 2
    assert len(queues) == 3
    topic = next(k for k, v in rs.items() if v["Type"] == "AWS::SNS::Topic")
    assert rs[topic]["Properties"]["TopicName"] == "wc-dev-monitoring"
    for construct, queue_name in (
        ("DiscordMessageDlq", "wc-dev-discord-message-dlq"),
        ("StatusExecutorDlq", "wc-dev-status-executor-dlq"),
    ):
        queue = next(k for k, v in queues.items() if v["QueueName"] == queue_name)
        logical, alarm = next((k, v) for k, v in alarms.items() if k.startswith(construct))
        assert alarm == {
            "AlarmName": "wc-dev-" + construct.lower() + "visiblealarm",
            "AlarmDescription": (
                f"{construct}: pending visible DLQ messages; always notify. "
                "First read docs/runbooks/monitoring_coverage.md#dlq-response"
            ),
            "Namespace": "AWS/SQS",
            "MetricName": "ApproximateNumberOfMessagesVisible",
            "Dimensions": [{"Name": "QueueName", "Value": {"Fn::GetAtt": [queue, "QueueName"]}}],
            "Statistic": "Maximum",
            "Period": 300,
            "Threshold": 1,
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "EvaluationPeriods": 1,
            "DatapointsToAlarm": 1,
            "TreatMissingData": "notBreaching",
            "AlarmActions": [{"Ref": topic}],
            "Tags": queues[queue]["Tags"],
        }
        assert all(
            logical not in str(v)
            for v in rs.values()
            if v["Type"] == "AWS::CloudWatch::CompositeAlarm"
        )
    assert SUPPRESSIBLE == {
        "DesiredStoppedEc2Running",
        "RuntimeObservationUnknown",
        "DesiredActualDivergence",
    }


def test_independent_web_import_preserves_logical_ids_and_error_evaluation() -> None:
    rs = resources("web")
    for logical, function in (
        ("AuthErrors8D0EDC3D", "AuthC256A5EC"),
        ("WebErrorsC4BB781A", "Web3C8945DB"),
    ):
        alarm = dict(rs[logical]["Properties"])
        actions = alarm.pop("AlarmActions")
        assert actions == [
            {
                "Fn::Join": [
                    "",
                    [
                        "arn:",
                        {"Ref": "AWS::Partition"},
                        ":sns:ap-northeast-1:385526546525:wc-dev-monitoring",
                    ],
                ]
            }
        ]
        assert alarm == {
            "ComparisonOperator": "GreaterThanOrEqualToThreshold",
            "Dimensions": [{"Name": "FunctionName", "Value": {"Ref": function}}],
            "EvaluationPeriods": 1,
            "MetricName": "Errors",
            "Namespace": "AWS/Lambda",
            "Period": 300,
            "Statistic": "Sum",
            "Threshold": 1,
            "TreatMissingData": "notBreaching",
        }
    assert not any(
        v["Type"]
        in {
            "AWS::SNS::Topic",
            "AWS::SNS::TopicPolicy",
            "AWS::KMS::Key",
            "AWS::CloudWatch::CompositeAlarm",
            "AWS::SQS::Queue",
        }
        for v in rs.values()
    )
    policies = str([v for v in rs.values() if v["Type"] == "AWS::IAM::Policy"])
    assert "sns:Publish" not in policies
    assert "kms:" not in policies
