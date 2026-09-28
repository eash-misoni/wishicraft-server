"""Opt-in future release bindings; disabled canonical stages have zero property changes."""

from __future__ import annotations

from aws_cdk import Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_

from infrastructure.retention_iam import shared_delete_policy
from wishicraft.config import ProjectConfig, StageConfig
from wishicraft.retention_release import RetentionRelease


def bind(
    stack: Stack,
    task: lambda_.Function,
    *,
    release: RetentionRelease,
    project: ProjectConfig,
    stage: StageConfig,
    state: dynamodb.Table,
    games: dynamodb.Table,
    operations: dynamodb.Table,
    backups: dynamodb.Table,
    locks: dynamodb.Table,
) -> None:
    if not release.provision:
        return
    task.add_environment("RETENTION_PROVISIONED", "1")
    task.add_environment("RETENTION_DELETE_ENABLED", "1" if release.enabled else "0")
    task.add_environment("GAMES_TABLE", games.table_name)
    task.add_environment(
        "RETENTION_WORKFLOW_NAME", f"{project.resource_prefix}-{stage.stage}-retention"
    )
    task.add_to_role_policy(
        iam.PolicyStatement(
            actions=[
                "ec2:DescribeImages",
                "ec2:DescribeSnapshotAttribute",
                "ec2:ListSnapshotsInRecycleBin",
            ],
            resources=["*"],
        )
    )
    task.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:Scan", "dynamodb:DescribeTable"],
            resources=[t.table_arn for t in (state, games, operations, backups)],
        )
    )
    task.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem"],
            resources=[backups.table_arn],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["DELETION#snap-*", "RETENTION#op-*"]
                }
            },
        )
    )
    task.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:ConditionCheckItem"],
            resources=[state.table_arn, operations.table_arn, locks.table_arn],
        )
    )
    # CF self-reference would create a cycle: derive the already canonical function ARN.
    fn = (
        f"arn:{stack.partition}:lambda:{stage.aws_region}:{stage.aws_account_id}:function:"
        f"{project.resource_prefix}-{stage.stage}-retention-task"
    )
    task.add_to_role_policy(
        iam.PolicyStatement(actions=["lambda:GetFunctionConfiguration"], resources=[fn])
    )
    execution = (
        f"arn:{stack.partition}:states:{stage.aws_region}:{stage.aws_account_id}:execution:"
        f"{project.resource_prefix}-{stage.stage}-retention:op-*"
    )
    task.add_to_role_policy(
        iam.PolicyStatement(
            actions=["states:DescribeExecution", "states:GetExecutionHistory"],
            resources=[execution],
        )
    )
    if release.enabled:
        task.add_to_role_policy(
            iam.PolicyStatement.from_json(
                shared_delete_policy(
                    partition=stack.partition,
                    region=stage.aws_region,
                    account=stage.aws_account_id,
                    project=project.project_slug,
                    stage=stage.stage,
                    volume_id=str(stage.host_runtime_value("target_host.existing_data_volume_id")),
                )
            )
        )
