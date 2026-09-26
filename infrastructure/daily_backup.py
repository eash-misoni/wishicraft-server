"""Opt-in daily evaluator; existing backup workflow and SNS remain authoritative."""

from __future__ import annotations

import json
from pathlib import Path

from aws_cdk import ArnFormat, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as actions
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_stepfunctions as sfn

from wishicraft.config import ProjectConfig, StageConfig
from wishicraft.naming import resource_name


def add(
    stack: Stack,
    *,
    project: ProjectConfig,
    stage: StageConfig,
    states: ddb.Table,
    operations: ddb.Table,
    locks: ddb.Table,
    games_table: ddb.Table,
    idempotency: ddb.Table,
    backup: sfn.CfnStateMachine,
    games: tuple[str, ...],
    creation: bool,
    enabled: bool,
) -> None:
    volume = str(stage.host_runtime_value("target_host.existing_data_volume_id"))
    common = {
        "SYSTEM_STATE_TABLE": states.table_name,
        "OPERATIONS_TABLE": operations.table_name,
        "LOCKS_TABLE": locks.table_name,
        "SYSTEM_ID": project.system_id,
        "GLOBAL_LOCK_NAME": stage.global_lock_name,
        "STAGE": stage.stage,
        "PROTECTION_VOLUME_ID": volume,
        "DAILY_BACKUP_ENABLED": "1" if enabled else "0",
    }

    def function(
        identifier: str, suffix: str, handler: str, environment: dict[str, str]
    ) -> lam.Function:
        name = resource_name(project.resource_prefix, stage.stage, suffix)
        log = logs.LogGroup(
            stack,
            identifier + "LogGroup",
            log_group_name="/aws/lambda/" + name,
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        return lam.Function(
            stack,
            identifier + "Function",
            function_name=name,
            runtime=lam.Runtime.PYTHON_3_12,
            architecture=lam.Architecture.X86_64,
            code=lam.Code.from_asset(str(Path(__file__).resolve().parents[1] / "src")),
            handler="wishicraft.daily_backup_lambda." + handler,
            timeout=Duration.seconds(60),
            memory_size=256,
            log_group=log,
            environment=environment,
        )

    admission = function(
        "DailyBackupAdmission",
        "daily-backup-admission",
        "admit",
        {
            **common,
            "GAMES_TABLE": games_table.table_name,
            "IDEMPOTENCY_TABLE": idempotency.table_name,
            "GAME_ID": project.initial_game_id,
            "LOCK_LEASE_SECONDS": str(stage.lock_lease_seconds),
            "BACKUP_STATE_MACHINE_ARN": backup.attr_arn,
            "RUNTIME_GAMES": json.dumps(games),
            "GAME_CREATION": "1" if creation else "0",
            "SWITCH_TIMEOUT_SECONDS": "3000",
            **{
                kind + "_TIMEOUT_SECONDS": str(stage.operation_timeout_seconds(kind))
                for kind in ("STATUS", "START", "STOP", "BACKUP", "RETENTION")
            },
        },
    )
    for action, tables in (
        ("dynamodb:GetItem", [states, operations, idempotency, locks, games_table]),
        ("dynamodb:PutItem", [operations, idempotency, locks]),
        ("dynamodb:UpdateItem", [states, operations]),
        ("dynamodb:ConditionCheckItem", [games_table]),
    ):
        admission.add_to_role_policy(
            iam.PolicyStatement(actions=[action], resources=[table.table_arn for table in tables])
        )
    admission.add_to_role_policy(
        iam.PolicyStatement(actions=["states:StartExecution"], resources=[backup.attr_arn])
    )
    admission.add_to_role_policy(
        iam.PolicyStatement(
            actions=["states:DescribeExecution"],
            resources=[
                stack.format_arn(
                    service="states",
                    resource="execution",
                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                    resource_name=resource_name(project.resource_prefix, stage.stage, "backup")
                    + ":op-*",
                )
            ],
        )
    )
    admission.add_to_role_policy(
        iam.PolicyStatement(actions=["dynamodb:DeleteItem"], resources=[locks.table_arn])
    )
    evaluator = function(
        "DailyBackupEvaluator",
        "daily-backup-evaluator",
        "handler",
        {**common, "DAILY_BACKUP_ADMISSION_FUNCTION": admission.function_name},
    )
    for fn in (admission, evaluator):
        fn.add_to_role_policy(
            iam.PolicyStatement(actions=["ec2:DescribeInstances"], resources=["*"])
        )
    evaluator.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:GetItem"],
            resources=[states.table_arn, locks.table_arn, operations.table_arn],
        )
    )
    evaluator.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:UpdateItem"],
            resources=[states.table_arn],
            conditions={
                "ForAllValues:StringEquals": {
                    "dynamodb:LeadingKeys": [project.system_id],
                    "dynamodb:Attributes": ["system_id", "backup_protection"],
                }
            },
        )
    )
    evaluator.add_to_role_policy(
        iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "Wishicraft/ControlPlane"}},
        )
    )
    admission.grant_invoke(evaluator)
    events.Rule(
        stack,
        "DailyBackupSchedule",
        schedule=events.Schedule.rate(Duration.minutes(5)),
        enabled=enabled,
        targets=[
            targets.LambdaFunction(
                evaluator,
                event=events.RuleTargetInput.from_object(
                    {"schema_version": 1, "operation": "evaluate_daily_backup"}
                ),
                retry_attempts=0,
            )
        ],
    )
    topic = stack.node.find_child("MonitoringTopic")
    assert isinstance(topic, sns.Topic)
    dimensions = {"Stage": stage.stage, "SystemId": project.system_id}
    for name in (
        "Heartbeat",
        "StoppedOverdue",
        "IntervalOverdue",
        "NeedsOperator",
        "ObservationUnknown",
    ):
        heartbeat = name == "Heartbeat"
        alarm = cw.Alarm(
            stack,
            "DailyBackup" + name + "Alarm",
            actions_enabled=enabled,
            alarm_description=(
                "Daily BACKUP " + name + "; inspect read-only daily status for reason"
            ),
            metric=cw.Metric(
                namespace="Wishicraft/ControlPlane",
                metric_name="DailyBackup" + name,
                dimensions_map=dimensions,
                period=Duration.minutes(5),
                statistic="Minimum" if heartbeat else "Maximum",
            ),
            threshold=1,
            evaluation_periods=3 if heartbeat else 1,
            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD
            if heartbeat
            else cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.BREACHING
            if heartbeat and enabled
            else cw.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(actions.SnsAction(topic))
