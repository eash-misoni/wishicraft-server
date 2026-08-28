"""Independent Phase 3/4 Control Plane persistence and admission stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Duration, Environment, RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from wishicraft.config import ProjectConfig, StageConfig
from wishicraft.naming import resource_name, resource_tags


class ControlPlaneStack(Stack):
    def __init__(self, scope: Construct, *, project: ProjectConfig, stage: StageConfig) -> None:
        super().__init__(
            scope,
            f"WishicraftControlPlaneStack-{stage.stage}",
            env=Environment(account=stage.aws_account_id, region=stage.aws_region),
            description="Wishicraft Reconcile, current state, and Operation admission",
            analytics_reporting=False,
        )
        raw_tags = project.values["resource_tags"]
        assert isinstance(raw_tags, dict)
        tags = resource_tags(
            {key: value for key, value in raw_tags.items() if isinstance(value, str)}, stage.stage
        )
        for key, value in tags.items():
            Tags.of(self).add(key, value)

        table = dynamodb.Table(
            self,
            "SystemStateTable",
            table_name=resource_name(project.resource_prefix, stage.stage, "system-state"),
            partition_key=dynamodb.Attribute(name="system_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )
        games_table = _table(
            self,
            "GamesTable",
            name=resource_name(project.resource_prefix, stage.stage, "games"),
            key="game_id",
        )
        operations_table = _table(
            self,
            "OperationsTable",
            name=resource_name(project.resource_prefix, stage.stage, "operations"),
            key="operation_id",
        )
        idempotency_table = _table(
            self,
            "IdempotencyTable",
            name=resource_name(project.resource_prefix, stage.stage, "idempotency"),
            key="idempotency_key",
        )
        locks_table = _table(
            self,
            "LocksTable",
            name=resource_name(project.resource_prefix, stage.stage, "locks"),
            key="lock_name",
        )
        log_group = logs.LogGroup(
            self,
            "ReconcileLogGroup",
            log_group_name=(
                f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'reconcile')}"
            ),
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        function = lambda_.Function(
            self,
            "ReconcileFunction",
            function_name=resource_name(project.resource_prefix, stage.stage, "reconcile"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
            handler="wishicraft.reconcile_lambda.handler",
            timeout=Duration.seconds(120),
            memory_size=256,
            log_group=log_group,
            environment={
                "SYSTEM_STATE_TABLE": table.table_name,
                "SYSTEM_ID": project.system_id,
                "STAGE": stage.stage,
                "PROJECT": project.project_slug,
                "GAME_ID": project.initial_game_id,
                "HOSTED_ZONE_ID": stage.route53_hosted_zone_id,
                "RECORD_NAME": stage.route53_record_name,
                "SSM_PROBE_TIMEOUT_SECONDS": str(stage.ssm_probe_timeout_seconds),
            },
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances", "ssm:DescribeInstanceInformation"],
                resources=["*"],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ssm:{stage.aws_region}::document/AWS-RunShellScript"],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:instance/*"],
                conditions={
                    "StringEquals": {
                        "ssm:resourceTag/Project": project.project_slug,
                        "ssm:resourceTag/Stage": stage.stage,
                        "ssm:resourceTag/Purpose": "phase2-target-validation",
                    }
                },
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(actions=["ssm:GetCommandInvocation"], resources=["*"])
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:ListResourceRecordSets"],
                resources=[f"arn:aws:route53:::hostedzone/{stage.route53_hosted_zone_id}"],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
                resources=[table.table_arn],
            )
        )

        admission_log_group = logs.LogGroup(
            self,
            "AdmissionLogGroup",
            log_group_name=(
                f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'admission')}"
            ),
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        admission = lambda_.Function(
            self,
            "AdmissionFunction",
            function_name=resource_name(project.resource_prefix, stage.stage, "admission"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
            handler="wishicraft.admission_lambda.handler",
            timeout=Duration.seconds(30),
            memory_size=256,
            log_group=admission_log_group,
            environment={
                "SYSTEM_STATE_TABLE": table.table_name,
                "GAMES_TABLE": games_table.table_name,
                "OPERATIONS_TABLE": operations_table.table_name,
                "IDEMPOTENCY_TABLE": idempotency_table.table_name,
                "LOCKS_TABLE": locks_table.table_name,
                "SYSTEM_ID": project.system_id,
                "GAME_ID": project.initial_game_id,
                "GLOBAL_LOCK_NAME": stage.global_lock_name,
                "LOCK_LEASE_SECONDS": str(stage.lock_lease_seconds),
                "STATUS_TIMEOUT_SECONDS": str(stage.operation_timeout_seconds("STATUS")),
                "START_TIMEOUT_SECONDS": str(stage.operation_timeout_seconds("START")),
                "STOP_TIMEOUT_SECONDS": str(stage.operation_timeout_seconds("STOP")),
                "BACKUP_TIMEOUT_SECONDS": str(stage.operation_timeout_seconds("BACKUP")),
            },
        )
        admission.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:TransactWriteItems"],
                resources=[
                    table.table_arn,
                    games_table.table_arn,
                    operations_table.table_arn,
                    idempotency_table.table_arn,
                    locks_table.table_arn,
                ],
            )
        )


def _table(
    scope: Construct,
    construct_id: str,
    *,
    name: str,
    key: str,
) -> dynamodb.Table:
    return dynamodb.Table(
        scope,
        construct_id,
        table_name=name,
        partition_key=dynamodb.Attribute(name=key, type=dynamodb.AttributeType.STRING),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        encryption=dynamodb.TableEncryption.AWS_MANAGED,
        removal_policy=RemovalPolicy.RETAIN,
    )
