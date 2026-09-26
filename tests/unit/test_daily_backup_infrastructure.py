from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aws_cdk import App
from aws_cdk.assertions import Template

from infrastructure.stacks.control_plane_stack import ControlPlaneStack
from wishicraft.config import load_configuration

ROOT = Path(__file__).resolve().parents[2]


def template(flags: dict[str, bool] | None) -> dict[str, Any]:
    configuration = load_configuration(ROOT, "dev")
    app = App()
    stack = ControlPlaneStack(
        app,
        project=configuration.project,
        stage=configuration.stage,
        daily_backup=flags,
        secrets=configuration.secrets,
        phase=8,
        games=("game-vanilla-main", "game-vanilla-secondary"),
    )
    return dict(Template.from_stack(stack).to_json()["Resources"])


@pytest.mark.parametrize("flags", [None, {"enabled": False, "provision": False}])
def test_unset_or_disabled_does_not_add_evaluator_resources(flags: dict[str, bool] | None) -> None:
    resources = template(flags)
    assert not any(k.startswith("DailyBackup") for k in resources)
    tracked = [
        v["Properties"]["Environment"]["Variables"]
        for v in resources.values()
        if v["Type"] == "AWS::Lambda::Function"
        and "PROTECTION_VOLUME_ID" in v["Properties"].get("Environment", {}).get("Variables", {})
    ]
    assert len(tracked) == 3


@pytest.mark.parametrize("enabled", [False, True])
def test_opt_in_schedule_alarms_and_least_privilege(enabled: bool) -> None:
    resources = template({"provision": True, "enabled": enabled})
    daily = {k: v for k, v in resources.items() if k.startswith("DailyBackup")}
    functions = [v for v in daily.values() if v["Type"] == "AWS::Lambda::Function"]
    assert len(functions) == 2
    assert not any(
        v["Type"] in {"AWS::DynamoDB::Table", "AWS::StepFunctions::StateMachine", "AWS::SQS::Queue"}
        for v in daily.values()
    )
    schedule = next(v["Properties"] for v in daily.values() if v["Type"] == "AWS::Events::Rule")
    assert schedule["ScheduleExpression"] == "rate(5 minutes)"
    assert schedule["State"] == ("ENABLED" if enabled else "DISABLED")
    alarms = [v["Properties"] for v in daily.values() if v["Type"] == "AWS::CloudWatch::Alarm"]
    assert len(alarms) == 5
    assert all(a["ActionsEnabled"] is enabled and a["AlarmActions"] for a in alarms)
    heartbeat = next(a for a in alarms if a["MetricName"] == "DailyBackupHeartbeat")
    assert heartbeat["TreatMissingData"] == ("breaching" if enabled else "notBreaching")
    assert heartbeat["EvaluationPeriods"] == 3
    for key, resource in resources.items():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        text = str(resource)
        if key.startswith("DailyBackupEvaluator"):
            assert "lambda:InvokeFunction" in text and "cloudwatch:PutMetricData" in text
            assert "dynamodb:Attributes" in text and "backup_protection" in text
            assert all(
                action not in text
                for action in (
                    "states:StartExecution",
                    "ec2:CreateSnapshot",
                    "ec2:StopInstances",
                    "ec2:DeleteSnapshot",
                )
            )
        if key.startswith("MonitoringObserver"):
            assert "lambda:InvokeFunction" not in text and "states:StartExecution" not in text
    assert all("ec2:DeleteSnapshot" not in str(v) for v in daily.values())


def test_stage_supplement_missing_is_disabled_and_invalid_enablement_rejected(
    tmp_path: Path,
) -> None:
    from wishicraft.config import load_daily_backup_configuration

    assert load_daily_backup_configuration(tmp_path, "dev") == {
        "provision": False,
        "enabled": False,
    }
    (tmp_path / "config").mkdir()
    path = tmp_path / "config/daily-backup-dev.json"
    path.write_text('{"schema_version":1,"provision":false,"enabled":true}')
    with pytest.raises(ValueError):
        load_daily_backup_configuration(tmp_path, "dev")


def test_full_package_configuration_with_enabled_daily_backup() -> None:
    from infrastructure.app import _games, _reset_policies

    configuration = load_configuration(ROOT, "dev")
    app = App(context={"game_packages": "true", "whitelist_management": "true"})
    stack = ControlPlaneStack(
        app,
        project=configuration.project,
        stage=configuration.stage,
        secrets=configuration.secrets,
        phase=8,
        games=_games(ROOT, "dev"),
        reset_policies=_reset_policies(ROOT, "dev"),
        game_creation=True,
        daily_backup={"enabled": True, "provision": True},
    )
    resources = Template.from_stack(stack).to_json()["Resources"]
    for resource in resources.values():
        if resource["Type"] == "AWS::Lambda::Function":
            variables = resource["Properties"].get("Environment", {}).get("Variables", {})
            assert sum(len(k) + len(str(v)) for k, v in variables.items()) < 4096
    assert any(key.startswith("DailyBackupEvaluator") for key in resources)
