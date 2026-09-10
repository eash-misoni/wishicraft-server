from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from tests.unit.test_monitoring_telemetry import setup_handler
from wishicraft import monitoring_lambda
from wishicraft.artifacts.host_runtime_probe import EXPECTED_DATA_VOLUME_ID
from wishicraft.config import load_configuration

ROOT = Path(__file__).resolve().parents[2]


def test_synthesized_environment_drives_actual_handler_and_all_new_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="control-plane")
    template = Template.from_stack(
        cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    )
    resources = template.to_json()["Resources"]
    observer = next(
        value["Properties"]
        for value in resources.values()
        if value["Type"] == "AWS::Lambda::Function"
        and value["Properties"]["FunctionName"] == "wc-dev-monitoring-observer"
    )
    aws = setup_handler(monkeypatch)
    for key, value in observer["Environment"]["Variables"].items():
        if isinstance(value, dict):
            assert set(value) == {"Ref"}
            table = resources[value["Ref"]]["Properties"]["TableName"]
            alias = {
                "SYSTEM_STATE_TABLE": "state",
                "LOCKS_TABLE": "lock",
                "RUNTIME_HEARTBEATS_TABLE": "heartbeat",
            }[key]
            aws.values[table] = aws.values[alias]
            monkeypatch.setenv(key, table)
        else:
            monkeypatch.setenv(key, value)
    assert monitoring_lambda.handler({}, None)["metric_count"] == 16
    alarm_metrics = {
        value["Properties"].get("MetricName"): value["Properties"]
        for value in resources.values()
        if value["Type"] == "AWS::CloudWatch::Alarm"
    }
    for name in (
        "RuntimeHeartbeatUnavailable",
        "RuntimeObservationUnknown",
        "RuntimeIdentityMismatch",
        "SystemStateObservationStale",
        "DataFilesystemObservationUnknown",
        "DataFilesystemUsageHigh",
    ):
        alarm = alarm_metrics[name]
        assert (
            alarm["Period"],
            alarm["EvaluationPeriods"],
            alarm["DatapointsToAlarm"],
            alarm["Threshold"],
        ) == (300, 2, 2, 1)
        assert alarm["TreatMissingData"] == (
            "ignore" if name == "DataFilesystemUsageHigh" else "breaching"
        )
        assert alarm["Statistic"] == "Maximum"
        assert alarm["AlarmActions"]
    schedule = next(
        value["Properties"]
        for value in resources.values()
        if value["Type"] == "AWS::Events::Rule"
        and value["Properties"]["Name"] == "wc-dev-monitoring-reconcile"
    )
    assert schedule["ScheduleExpression"] == "rate(5 minutes)"
    target = schedule["Targets"][0]
    assert json.loads(target["Input"]) == {"schema_version": 1, "operation": "scheduled_reconcile"}
    assert target["RetryPolicy"]["MaximumRetryAttempts"] == 0
    for value in resources.values():
        if value["Type"] == "AWS::Logs::LogGroup":
            assert value["Properties"]["RetentionInDays"] == 14
    role = observer["Role"]["Fn::GetAtt"][0]
    statements = [
        statement
        for value in resources.values()
        if value["Type"] == "AWS::IAM::Policy" and {"Ref": role} in value["Properties"]["Roles"]
        for statement in value["Properties"]["PolicyDocument"]["Statement"]
    ]
    metric_statement = next(
        statement for statement in statements if statement["Action"] == "cloudwatch:PutMetricData"
    )
    assert metric_statement["Condition"] == {
        "StringEquals": {"cloudwatch:namespace": "Wishicraft/ControlPlane"}
    }
    actions = {
        action
        for statement in statements
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    }
    assert actions <= {
        "dynamodb:GetItem",
        "ec2:DescribeInstances",
        "cloudwatch:PutMetricData",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    }
    assert EXPECTED_DATA_VOLUME_ID == load_configuration(ROOT, "dev").stage.host_runtime_value(
        "target_host.existing_data_volume_id"
    )
