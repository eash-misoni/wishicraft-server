"""Independent Phase 3/4 Control Plane persistence and admission stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import AssetHashType, CfnOutput, Duration, Environment, RemovalPolicy, Stack, Tags
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

from infrastructure.discord_command_bundle import discord_command_bundling
from wishicraft.config import ProjectConfig, SecretsExampleConfig, StageConfig
from wishicraft.naming import resource_name, resource_tags


class ControlPlaneStack(Stack):
    def __init__(
        self,
        scope: Construct,
        *,
        project: ProjectConfig,
        stage: StageConfig,
        secrets: SecretsExampleConfig,
        phase: int = 0,
    ) -> None:
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
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES if phase >= 7 else None,
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

        start_task_log_group = logs.LogGroup(
            self,
            "StartTaskLogGroup",
            log_group_name=(
                f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'start-task')}"
            ),
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        start_task = lambda_.Function(
            self,
            "StartTaskFunction",
            function_name=resource_name(project.resource_prefix, stage.stage, "start-task"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
            handler="wishicraft.start_workflow_lambda.handler",
            timeout=Duration.seconds(60),
            memory_size=256,
            log_group=start_task_log_group,
            environment={
                "SYSTEM_STATE_TABLE": table.table_name,
                "OPERATIONS_TABLE": operations_table.table_name,
                "LOCKS_TABLE": locks_table.table_name,
                "SYSTEM_ID": project.system_id,
                "GAME_ID": project.initial_game_id,
                "PROJECT": project.project_slug,
                "STAGE": stage.stage,
                "GLOBAL_LOCK_NAME": stage.global_lock_name,
                "LOCK_LEASE_SECONDS": str(stage.lock_lease_seconds),
                "HOST_START_TIMEOUT_SECONDS": str(stage.host_runtime_timeout_seconds("ssm")),
                "HOSTED_ZONE_ID": stage.route53_hosted_zone_id,
                "RECORD_NAME": stage.route53_record_name,
                "RECORD_TTL_SECONDS": str(project.route53_ttl_seconds),
            },
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeInstances"],
                resources=["*"],
            )
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:StartInstances"],
                resources=[f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:instance/*"],
                conditions={
                    "StringEquals": {
                        "ec2:ResourceTag/Project": project.project_slug,
                        "ec2:ResourceTag/Stage": stage.stage,
                        "ec2:ResourceTag/Purpose": "phase2-target-validation",
                    }
                },
            )
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ssm:{stage.aws_region}::document/AWS-RunShellScript"],
            )
        )
        start_task.add_to_role_policy(
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
        start_task.add_to_role_policy(
            iam.PolicyStatement(actions=["ssm:GetCommandInvocation"], resources=["*"])
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:ChangeResourceRecordSets"],
                resources=[f"arn:aws:route53:::hostedzone/{stage.route53_hosted_zone_id}"],
            )
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:GetChange"], resources=["arn:aws:route53:::change/*"]
            )
        )
        start_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:TransactWriteItems",
                ],
                resources=[table.table_arn, operations_table.table_arn, locks_table.table_arn],
            )
        )

        workflow_role = iam.Role(
            self,
            "StartWorkflowRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            description="Phase 5 START Standard workflow",
        )
        function.grant_invoke(workflow_role)
        start_task.grant_invoke(workflow_role)
        start_workflow = sfn.CfnStateMachine(
            self,
            "StartStateMachine",
            state_machine_name=resource_name(project.resource_prefix, stage.stage, "start"),
            state_machine_type="STANDARD",
            role_arn=workflow_role.role_arn,
            definition=_start_definition(
                reconcile_arn=function.function_arn,
                start_task_arn=start_task.function_arn,
                lease_renew_seconds=stage.lock_renew_interval_seconds,
            ),
        )

        stop_task_log_group = logs.LogGroup(
            self,
            "StopTaskLogGroup",
            log_group_name=(
                f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'stop-task')}"
            ),
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        stop_task = lambda_.Function(
            self,
            "StopTaskFunction",
            function_name=resource_name(project.resource_prefix, stage.stage, "stop-task"),
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
            handler="wishicraft.stop_workflow_lambda.handler",
            timeout=Duration.seconds(60),
            memory_size=256,
            log_group=stop_task_log_group,
            environment={
                "SYSTEM_STATE_TABLE": table.table_name,
                "OPERATIONS_TABLE": operations_table.table_name,
                "LOCKS_TABLE": locks_table.table_name,
                "SYSTEM_ID": project.system_id,
                "PROJECT": project.project_slug,
                "STAGE": stage.stage,
                "GLOBAL_LOCK_NAME": stage.global_lock_name,
                "LOCK_LEASE_SECONDS": str(stage.lock_lease_seconds),
                "HOST_STOP_TIMEOUT_SECONDS": str(stage.host_runtime_timeout_seconds("ssm")),
                "HOSTED_ZONE_ID": stage.route53_hosted_zone_id,
                "RECORD_NAME": stage.route53_record_name,
            },
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(actions=["ec2:DescribeInstances"], resources=["*"])
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ec2:StopInstances"],
                resources=[f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:instance/*"],
                conditions={
                    "StringEquals": {
                        "ec2:ResourceTag/Project": project.project_slug,
                        "ec2:ResourceTag/Stage": stage.stage,
                        "ec2:ResourceTag/Purpose": "phase2-target-validation",
                    }
                },
            )
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:SendCommand"],
                resources=[f"arn:aws:ssm:{stage.aws_region}::document/AWS-RunShellScript"],
            )
        )
        stop_task.add_to_role_policy(
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
        stop_task.add_to_role_policy(
            iam.PolicyStatement(actions=["ssm:GetCommandInvocation"], resources=["*"])
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:ListResourceRecordSets"],
                resources=[f"arn:aws:route53:::hostedzone/{stage.route53_hosted_zone_id}"],
            )
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:ChangeResourceRecordSets"],
                resources=[f"arn:aws:route53:::hostedzone/{stage.route53_hosted_zone_id}"],
                conditions={
                    "ForAllValues:StringEquals": {
                        "route53:ChangeResourceRecordSetsNormalizedRecordNames": [
                            stage.route53_record_name
                        ],
                        "route53:ChangeResourceRecordSetsRecordTypes": ["A"],
                        "route53:ChangeResourceRecordSetsActions": ["DELETE"],
                    }
                },
            )
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=["route53:GetChange"], resources=["arn:aws:route53:::change/*"]
            )
        )
        stop_task.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:TransactWriteItems",
                ],
                resources=[table.table_arn, operations_table.table_arn, locks_table.table_arn],
            )
        )
        stop_workflow_role = iam.Role(
            self,
            "StopWorkflowRole",
            assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
            description="Phase 6 STOP Standard workflow",
        )
        function.grant_invoke(stop_workflow_role)
        stop_task.grant_invoke(stop_workflow_role)
        stop_workflow = sfn.CfnStateMachine(
            self,
            "StopStateMachine",
            state_machine_name=resource_name(project.resource_prefix, stage.stage, "stop"),
            state_machine_type="STANDARD",
            role_arn=stop_workflow_role.role_arn,
            definition=_stop_definition(
                reconcile_arn=function.function_arn,
                stop_task_arn=stop_task.function_arn,
                lease_renew_seconds=stage.lock_renew_interval_seconds,
            ),
        )

        backup_task: lambda_.Function | None = None
        backup_workflow: sfn.CfnStateMachine | None = None
        if phase >= 8:
            backup_task_log_group = logs.LogGroup(
                self,
                "BackupTaskLogGroup",
                log_group_name=(
                    "/aws/lambda/"
                    f"{resource_name(project.resource_prefix, stage.stage, 'backup-task')}"
                ),
                retention=logs.RetentionDays.TWO_WEEKS,
                removal_policy=RemovalPolicy.DESTROY,
            )
            backup_task = lambda_.Function(
                self,
                "BackupTaskFunction",
                function_name=resource_name(project.resource_prefix, stage.stage, "backup-task"),
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.X86_64,
                code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
                handler="wishicraft.backup_workflow_lambda.handler",
                timeout=Duration.seconds(60),
                memory_size=256,
                log_group=backup_task_log_group,
                environment={
                    "SYSTEM_STATE_TABLE": table.table_name,
                    "OPERATIONS_TABLE": operations_table.table_name,
                    "LOCKS_TABLE": locks_table.table_name,
                    "SYSTEM_ID": project.system_id,
                    "GAME_ID": project.initial_game_id,
                    "PROJECT": project.project_slug,
                    "STAGE": stage.stage,
                    "AWS_ACCOUNT_ID": stage.aws_account_id,
                    "AVAILABILITY_ZONE": stage.availability_zone,
                    "DATA_VOLUME_ID": str(
                        stage.host_runtime_value("target_host.existing_data_volume_id")
                    ),
                    "GLOBAL_LOCK_NAME": stage.global_lock_name,
                    "LOCK_LEASE_SECONDS": str(stage.lock_lease_seconds),
                },
                description="Phase 8A stopped-only persistent Data EBS backup task",
            )
            backup_task.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ec2:DescribeVolumes", "ec2:DescribeSnapshots"], resources=["*"]
                )
            )
            backup_task.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ec2:CreateSnapshot"],
                    resources=[
                        f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:snapshot/*",
                    ],
                    conditions={
                        "StringEquals": {
                            "aws:RequestTag/Project": project.project_slug,
                            "aws:RequestTag/Stage": stage.stage,
                            "aws:RequestTag/WishicraftCategory": "backup",
                            "aws:RequestTag/WishicraftGameId": project.initial_game_id,
                            "aws:RequestTag/WishicraftProtected": "false",
                        }
                    },
                )
            )
            backup_task.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ec2:CreateSnapshot"],
                    resources=[
                        (
                            f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:volume/"
                            f"{stage.host_runtime_value('target_host.existing_data_volume_id')}"
                        )
                    ],
                )
            )
            backup_task.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ec2:CreateTags"],
                    resources=[f"arn:aws:ec2:{stage.aws_region}:{stage.aws_account_id}:snapshot/*"],
                    conditions={"StringEquals": {"ec2:CreateAction": "CreateSnapshot"}},
                )
            )
            backup_task.add_to_role_policy(
                iam.PolicyStatement(
                    actions=[
                        "dynamodb:GetItem",
                        "dynamodb:UpdateItem",
                        "dynamodb:DeleteItem",
                        "dynamodb:TransactWriteItems",
                    ],
                    resources=[table.table_arn, operations_table.table_arn, locks_table.table_arn],
                )
            )
            backup_workflow_role = iam.Role(
                self,
                "BackupWorkflowRole",
                assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
                description="Phase 8A BACKUP Standard workflow",
            )
            function.grant_invoke(backup_workflow_role)
            backup_task.grant_invoke(backup_workflow_role)
            backup_workflow = sfn.CfnStateMachine(
                self,
                "BackupStateMachine",
                state_machine_name=resource_name(project.resource_prefix, stage.stage, "backup"),
                state_machine_type="STANDARD",
                role_arn=backup_workflow_role.role_arn,
                definition=_backup_definition(
                    reconcile_arn=function.function_arn,
                    backup_task_arn=backup_task.function_arn,
                    poll_seconds=stage.lock_renew_interval_seconds,
                    timeout_seconds=stage.operation_timeout_seconds("BACKUP"),
                ),
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
                "START_STATE_MACHINE_ARN": start_workflow.attr_arn,
                "STOP_STATE_MACHINE_ARN": stop_workflow.attr_arn,
                **(
                    {"BACKUP_STATE_MACHINE_ARN": backup_workflow.attr_arn}
                    if backup_workflow is not None
                    else {}
                ),
            },
        )
        admission.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:ConditionCheckItem",
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:TransactWriteItems",
                    "dynamodb:UpdateItem",
                ],
                resources=[
                    table.table_arn,
                    games_table.table_arn,
                    operations_table.table_arn,
                    idempotency_table.table_arn,
                    locks_table.table_arn,
                ],
            )
        )
        admission.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[
                    start_workflow.attr_arn,
                    stop_workflow.attr_arn,
                    *([backup_workflow.attr_arn] if backup_workflow is not None else []),
                ],
            )
        )
        admission.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:DescribeExecution"],
                resources=[
                    (
                        f"arn:aws:states:{stage.aws_region}:{stage.aws_account_id}:execution:"
                        f"{resource_name(project.resource_prefix, stage.stage, 'start')}:*"
                    ),
                    (
                        f"arn:aws:states:{stage.aws_region}:{stage.aws_account_id}:execution:"
                        f"{resource_name(project.resource_prefix, stage.stage, 'stop')}:*"
                    ),
                    *(
                        [
                            (
                                f"arn:aws:states:{stage.aws_region}:"
                                f"{stage.aws_account_id}:execution:"
                                f"{resource_name(project.resource_prefix, stage.stage, 'backup')}:*"
                            )
                        ]
                        if backup_workflow is not None
                        else []
                    ),
                ],
            )
        )
        if phase >= 7:
            discord_functions = _add_discord_ingress(
                self,
                project=project,
                stage=stage,
                admission=admission,
                reconcile=function,
                operations_table=operations_table,
                locks_table=locks_table,
                system_state_table=table,
                bot_token_parameter_name=secrets.discord_bot_token_parameter_name(stage.stage),
            )
            _add_release_monitoring(
                self,
                project=project,
                stage=stage,
                system_state_table=table,
                locks_table=locks_table,
                start_workflow=start_workflow,
                stop_workflow=stop_workflow,
                backup_workflow=backup_workflow,
                monitored_functions=(
                    function,
                    start_task,
                    stop_task,
                    *([backup_task] if backup_task is not None else []),
                    admission,
                    *discord_functions,
                ),
            )


def _add_discord_ingress(
    stack: Stack,
    *,
    project: ProjectConfig,
    stage: StageConfig,
    admission: lambda_.Function,
    reconcile: lambda_.Function,
    operations_table: dynamodb.Table,
    locks_table: dynamodb.Table,
    system_state_table: dynamodb.Table,
    bot_token_parameter_name: str,
) -> tuple[lambda_.Function, lambda_.Function, lambda_.Function]:
    repository_root = Path(__file__).resolve().parents[2]
    log_group = logs.LogGroup(
        stack,
        "DiscordCommandLogGroup",
        log_group_name=(
            f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'discord-command')}"
        ),
        retention=logs.RetentionDays.TWO_WEEKS,
        removal_policy=RemovalPolicy.DESTROY,
    )
    function = lambda_.Function(
        stack,
        "DiscordCommandFunction",
        function_name=resource_name(project.resource_prefix, stage.stage, "discord-command"),
        runtime=lambda_.Runtime.PYTHON_3_12,
        architecture=lambda_.Architecture.X86_64,
        code=lambda_.Code.from_asset(
            str(repository_root),
            bundling=discord_command_bundling(repository_root),
            asset_hash_type=AssetHashType.OUTPUT,
        ),
        handler="wishicraft.discord_command_lambda.handler",
        timeout=Duration.seconds(10),
        memory_size=256,
        log_group=log_group,
        environment={
            "DISCORD_APPLICATION_ID": stage.discord_public_id("application_id"),
            "DISCORD_GUILD_ID": stage.discord_public_id("guild_id"),
            "DISCORD_OPERATION_CHANNEL_ID": stage.discord_public_id("operation_channel_id"),
            "DISCORD_PLAYER_ROLE_ID": stage.discord_public_id("player_role_id"),
            "DISCORD_ADMIN_ROLE_ID": stage.discord_public_id("admin_role_id"),
            "DISCORD_PUBLIC_KEY": stage.discord_public_key,
            "ADMISSION_FUNCTION_NAME": admission.function_name,
        },
        description="Phase 7G Discord callback ACK before shared STATUS, START, and STOP admission",
    )
    admission.grant_invoke(function)

    status_log_group = logs.LogGroup(
        stack,
        "StatusExecutorLogGroup",
        log_group_name=(
            f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'status-executor')}"
        ),
        retention=logs.RetentionDays.TWO_WEEKS,
        removal_policy=RemovalPolicy.DESTROY,
    )
    status_executor = lambda_.Function(
        stack,
        "StatusExecutorFunction",
        function_name=resource_name(project.resource_prefix, stage.stage, "status-executor"),
        runtime=lambda_.Runtime.PYTHON_3_12,
        architecture=lambda_.Architecture.X86_64,
        code=lambda_.Code.from_asset(str(repository_root / "src")),
        handler="wishicraft.status_executor_lambda.handler",
        timeout=Duration.seconds(stage.operation_timeout_seconds("STATUS") + 30),
        memory_size=256,
        log_group=status_log_group,
        environment={
            "OPERATIONS_TABLE": operations_table.table_name,
            "LOCKS_TABLE": locks_table.table_name,
            "SYSTEM_STATE_TABLE": system_state_table.table_name,
            "SYSTEM_ID": project.system_id,
            "GLOBAL_LOCK_NAME": stage.global_lock_name,
            "RECONCILE_FUNCTION_NAME": reconcile.function_name,
        },
        description="Phase 7C asynchronous non-locking STATUS executor",
    )
    status_executor.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=[operations_table.table_arn],
        )
    )
    reconcile.grant_invoke(status_executor)
    status_dlq = sqs.Queue(
        stack,
        "StatusExecutorDlq",
        queue_name=resource_name(project.resource_prefix, stage.stage, "status-executor-dlq"),
        encryption=sqs.QueueEncryption.SQS_MANAGED,
        retention_period=Duration.days(14),
    )
    status_executor.add_event_source(
        lambda_event_sources.DynamoEventSource(
            operations_table,
            starting_position=lambda_.StartingPosition.LATEST,
            batch_size=1,
            bisect_batch_on_error=True,
            retry_attempts=2,
            on_failure=lambda_event_sources.SqsDlq(status_dlq),
            filters=[
                lambda_.FilterCriteria.filter(
                    {
                        "eventName": ["INSERT"],
                        "dynamodb": {"NewImage": {"operation_type": {"S": ["STATUS"]}}},
                    }
                )
            ],
        )
    )

    delivery_dlq = sqs.Queue(
        stack,
        "DiscordMessageDlq",
        queue_name=resource_name(project.resource_prefix, stage.stage, "discord-message-dlq"),
        encryption=sqs.QueueEncryption.SQS_MANAGED,
        retention_period=Duration.days(14),
    )
    delivery_queue = sqs.Queue(
        stack,
        "DiscordMessageRetryQueue",
        queue_name=resource_name(project.resource_prefix, stage.stage, "discord-message-retry"),
        encryption=sqs.QueueEncryption.SQS_MANAGED,
        visibility_timeout=Duration.seconds(60),
        retention_period=Duration.days(1),
        dead_letter_queue=sqs.DeadLetterQueue(queue=delivery_dlq, max_receive_count=3),
    )
    message_log_group = logs.LogGroup(
        stack,
        "DiscordMessageLogGroup",
        log_group_name=(
            f"/aws/lambda/{resource_name(project.resource_prefix, stage.stage, 'discord-message')}"
        ),
        retention=logs.RetentionDays.TWO_WEEKS,
        removal_policy=RemovalPolicy.DESTROY,
    )
    message = lambda_.Function(
        stack,
        "DiscordMessageFunction",
        function_name=resource_name(project.resource_prefix, stage.stage, "discord-message"),
        runtime=lambda_.Runtime.PYTHON_3_12,
        architecture=lambda_.Architecture.X86_64,
        code=lambda_.Code.from_asset(str(repository_root / "src")),
        handler="wishicraft.discord_message_lambda.handler",
        timeout=Duration.seconds(30),
        memory_size=256,
        log_group=message_log_group,
        environment={
            "OPERATIONS_TABLE": operations_table.table_name,
            "BOT_TOKEN_PARAMETER_NAME": bot_token_parameter_name,
            "DELIVERY_RETRY_QUEUE_URL": delivery_queue.queue_url,
        },
        description="Phase 7D idempotent Discord message delivery",
    )
    message.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=[operations_table.table_arn],
        )
    )
    message.add_to_role_policy(
        iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{stage.aws_region}:{stage.aws_account_id}:parameter"
                f"{bot_token_parameter_name}"
            ],
        )
    )
    delivery_queue.grant_send_messages(message)
    message.add_event_source(
        lambda_event_sources.DynamoEventSource(
            operations_table,
            starting_position=lambda_.StartingPosition.LATEST,
            batch_size=1,
            bisect_batch_on_error=True,
            retry_attempts=2,
            on_failure=lambda_event_sources.SqsDlq(delivery_dlq),
            filters=[
                lambda_.FilterCriteria.filter(
                    {
                        "eventName": ["INSERT", "MODIFY"],
                        "dynamodb": {
                            "NewImage": {
                                "operation_type": {"S": ["STATUS", "START", "STOP"]},
                                "requested_by": {"M": {"source": {"S": ["DISCORD"]}}},
                            }
                        },
                    }
                )
            ],
        )
    )
    message.add_event_source(
        lambda_event_sources.SqsEventSource(
            delivery_queue,
            batch_size=1,
            report_batch_item_failures=True,
        )
    )
    api = apigwv2.HttpApi(
        stack,
        "DiscordInteractionsApi",
        api_name=resource_name(project.resource_prefix, stage.stage, "discord-interactions"),
        create_default_stage=True,
        description="Discord Interaction ingress with application signature verification",
    )
    integration = apigwv2_integrations.HttpLambdaIntegration(
        "DiscordCommandIntegration",
        function,
        payload_format_version=apigwv2.PayloadFormatVersion.VERSION_2_0,
    )
    api.add_routes(
        path="/discord/interactions",
        methods=[apigwv2.HttpMethod.POST],
        integration=integration,
    )
    CfnOutput(
        stack,
        "DiscordInteractionsEndpoint",
        value=f"{api.api_endpoint}/discord/interactions",
    )
    return function, status_executor, message


def _add_release_monitoring(
    stack: Stack,
    *,
    project: ProjectConfig,
    stage: StageConfig,
    system_state_table: dynamodb.Table,
    locks_table: dynamodb.Table,
    start_workflow: sfn.CfnStateMachine,
    stop_workflow: sfn.CfnStateMachine,
    backup_workflow: sfn.CfnStateMachine | None,
    monitored_functions: tuple[lambda_.Function, ...],
) -> None:
    namespace = "Wishicraft/ControlPlane"
    dimensions = {"Stage": stage.stage, "SystemId": project.system_id}
    key = kms.Key(
        stack,
        "MonitoringNotificationKey",
        alias=f"alias/{resource_name(project.resource_prefix, stage.stage, 'monitoring')}",
        enable_key_rotation=True,
        removal_policy=RemovalPolicy.RETAIN,
        description="Encrypt Wishicraft monitoring notifications",
    )
    topic = sns.Topic(
        stack,
        "MonitoringTopic",
        topic_name=resource_name(project.resource_prefix, stage.stage, "monitoring"),
        master_key=key,
    )
    for service in ("cloudwatch.amazonaws.com", "budgets.amazonaws.com"):
        principal = iam.ServicePrincipal(service)
        topic.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[principal], actions=["sns:Publish"], resources=[topic.topic_arn]
            )
        )
        key.grant_encrypt_decrypt(principal)

    observer_log = logs.LogGroup(
        stack,
        "MonitoringObserverLogGroup",
        log_group_name=(
            f"/aws/lambda/"
            f"{resource_name(project.resource_prefix, stage.stage, 'monitoring-observer')}"
        ),
        retention=logs.RetentionDays.TWO_WEEKS,
        removal_policy=RemovalPolicy.DESTROY,
    )
    observer = lambda_.Function(
        stack,
        "MonitoringObserverFunction",
        function_name=resource_name(project.resource_prefix, stage.stage, "monitoring-observer"),
        runtime=lambda_.Runtime.PYTHON_3_12,
        architecture=lambda_.Architecture.X86_64,
        code=lambda_.Code.from_asset(str(Path(__file__).resolve().parents[2] / "src")),
        handler="wishicraft.monitoring_lambda.handler",
        timeout=Duration.seconds(30),
        memory_size=256,
        log_group=observer_log,
        environment={
            "SYSTEM_STATE_TABLE": system_state_table.table_name,
            "LOCKS_TABLE": locks_table.table_name,
            "SYSTEM_ID": project.system_id,
            "GLOBAL_LOCK_NAME": stage.global_lock_name,
            "STAGE": stage.stage,
            "METRIC_NAMESPACE": namespace,
            "EC2_RUNNING_WARNING_SECONDS": str(
                stage.monitoring_int("ec2_running_warning_hours") * 3600
            ),
            "DESIRED_STOPPED_RUNNING_WARNING_SECONDS": str(
                stage.monitoring_int("desired_stopped_ec2_running_warning_minutes") * 60
            ),
            "DESIRED_RUNNING_NOT_READY_WARNING_SECONDS": str(
                stage.monitoring_int("desired_running_not_ready_warning_minutes") * 60
            ),
            "OBSERVATION_FRESHNESS_SECONDS": str(
                stage.monitoring_int("observation_freshness_warning_minutes") * 60
            ),
        },
        description="Phase 7 read-only monitoring observer",
    )
    observer.add_to_role_policy(
        iam.PolicyStatement(
            actions=["dynamodb:GetItem"],
            resources=[system_state_table.table_arn, locks_table.table_arn],
        )
    )
    observer.add_to_role_policy(
        iam.PolicyStatement(
            actions=["ec2:DescribeInstances", "cloudwatch:PutMetricData"], resources=["*"]
        )
    )
    events.Rule(
        stack,
        "MonitoringObserverSchedule",
        rule_name=resource_name(project.resource_prefix, stage.stage, "monitoring-observer"),
        schedule=events.Schedule.rate(
            Duration.minutes(stage.monitoring_int("observer_schedule_minutes"))
        ),
        targets=[events_targets.LambdaFunction(observer)],
    )

    alarm_action = cloudwatch_actions.SnsAction(topic)

    def add_alarm(
        construct_id: str,
        metric: cloudwatch.IMetric,
        *,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int | None = None,
        missing: cloudwatch.TreatMissingData = cloudwatch.TreatMissingData.NOT_BREACHING,
    ) -> None:
        alarm = cloudwatch.Alarm(
            stack,
            construct_id,
            alarm_name=resource_name(project.resource_prefix, stage.stage, construct_id.lower()),
            metric=metric,
            threshold=1,
            evaluation_periods=evaluation_periods,
            datapoints_to_alarm=datapoints_to_alarm,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=missing,
        )
        alarm.add_alarm_action(alarm_action)

    monitored_workflows = [("Start", start_workflow), ("Stop", stop_workflow)]
    if backup_workflow is not None:
        monitored_workflows.append(("Backup", backup_workflow))
    for logical, machine in monitored_workflows:
        machine_name = resource_name(project.resource_prefix, stage.stage, logical.lower())
        metrics = {
            name: cloudwatch.Metric(
                namespace="AWS/States",
                metric_name=name,
                dimensions_map={"StateMachineArn": machine.attr_arn},
                statistic="Sum",
                period=Duration.minutes(5),
            )
            for name in ("ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted")
        }
        add_alarm(
            f"{logical}WorkflowFailureAlarm",
            cloudwatch.MathExpression(
                expression="failed + timedout + aborted",
                using_metrics={
                    "failed": metrics["ExecutionsFailed"],
                    "timedout": metrics["ExecutionsTimedOut"],
                    "aborted": metrics["ExecutionsAborted"],
                },
                period=Duration.minutes(5),
                label=f"{machine_name} terminal failures",
            ),
        )

    for metric_name, alarm_id, evaluations in (
        ("TargetRunningTooLong", "TargetRunningTooLongAlarm", 1),
        ("DesiredStoppedEc2Running", "DesiredStoppedEc2RunningAlarm", 1),
        ("DesiredActualDivergence", "DesiredActualDivergenceAlarm", 3),
        ("ExpiredOperationLock", "ExpiredOperationLockAlarm", 1),
        ("DesiredRunningNotReady", "DesiredRunningNotReadyAlarm", 1),
        ("MonitoringObservationUnknown", "MonitoringObservationUnknownAlarm", 2),
    ):
        add_alarm(
            alarm_id,
            cloudwatch.Metric(
                namespace=namespace,
                metric_name=metric_name,
                dimensions_map=dimensions,
                statistic="Maximum",
                period=Duration.minutes(stage.monitoring_int("observer_schedule_minutes")),
            ),
            evaluation_periods=evaluations,
            datapoints_to_alarm=evaluations,
            missing=cloudwatch.TreatMissingData.BREACHING,
        )

    for function in (*monitored_functions, observer):
        for metric_name, metric in (
            ("Errors", function.metric_errors(period=Duration.minutes(5), statistic="Sum")),
            ("Throttles", function.metric_throttles(period=Duration.minutes(5), statistic="Sum")),
        ):
            add_alarm(f"{function.node.id}{metric_name}Alarm", metric)

    subscribers = [
        budgets.CfnBudget.SubscriberProperty(address=topic.topic_arn, subscription_type="SNS")
    ]
    notifications = [
        budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                comparison_operator="GREATER_THAN",
                notification_type="ACTUAL",
                threshold=threshold,
                threshold_type="PERCENTAGE",
            ),
            subscribers=subscribers,
        )
        for threshold in stage.budget_threshold_percentages
    ]
    if stage.notify_forecasted_budget:
        notifications.append(
            budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN",
                    notification_type="FORECASTED",
                    threshold=100,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=subscribers,
            )
        )
    budget = budgets.CfnBudget(
        stack,
        "MonthlyCostBudget",
        budget=budgets.CfnBudget.BudgetDataProperty(
            budget_name=resource_name(project.resource_prefix, stage.stage, "monthly-cost"),
            budget_type="COST",
            time_unit="MONTHLY",
            budget_limit=budgets.CfnBudget.SpendProperty(
                amount=stage.monitoring_int("monthly_budget_usd"), unit="USD"
            ),
        ),
        notifications_with_subscribers=notifications,
    )
    budget.node.add_dependency(topic)
    CfnOutput(stack, "MonitoringTopicArn", value=topic.topic_arn)


def _table(
    scope: Construct,
    construct_id: str,
    *,
    name: str,
    key: str,
    stream: dynamodb.StreamViewType | None = None,
) -> dynamodb.Table:
    return dynamodb.Table(
        scope,
        construct_id,
        table_name=name,
        partition_key=dynamodb.Attribute(name=key, type=dynamodb.AttributeType.STRING),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        encryption=dynamodb.TableEncryption.AWS_MANAGED,
        stream=stream,
        removal_policy=RemovalPolicy.RETAIN,
    )


def _start_definition(
    *, reconcile_arn: str, start_task_arn: str, lease_renew_seconds: int
) -> dict[str, object]:
    def invoke(
        action: str,
        *,
        failure_state: str,
        state_path: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "action": action,
            "operation_id.$": "$.operation_id",
            "lease_id.$": "$.lease_id",
        }
        if state_path is not None:
            payload["state.$"] = state_path
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {"FunctionName": start_task_arn, "Payload": payload},
            "OutputPath": "$.Payload",
            "Retry": [
                {
                    "ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
                    "IntervalSeconds": 2,
                    "MaxAttempts": 3,
                    "BackoffRate": 2,
                }
            ],
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "ResultPath": "$.workflow_error",
                    "Next": failure_state,
                }
            ],
        }

    reconcile = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
            "FunctionName": reconcile_arn,
            "Payload": {"schema_version": 1, "operation": "reconcile"},
        },
        "ResultSelector": {"state.$": "$.Payload"},
        "ResultPath": "$.reconcile",
        "Catch": [
            {
                "ErrorEquals": ["States.ALL"],
                "ResultPath": "$.workflow_error",
                "Next": "SetObservationFailure",
            }
        ],
    }
    states: dict[str, object] = {
        "InitializeWorkflow": {
            "Type": "Pass",
            "Result": {},
            "ResultPath": "$.workflow_error",
            "Next": "ReconcileBeforeStart",
        },
        "ReconcileBeforeStart": {**reconcile, "Next": "SetDesiredRunning"},
        "SetDesiredRunning": {
            **invoke(
                "set_desired",
                state_path="$.reconcile.state",
                failure_state="SetPreconditionFailure",
            ),
            "ResultPath": "$.desired",
            "OutputPath": "$",
            "Next": "AlreadyReady",
        },
        "AlreadyReady": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.desired.Payload.already_ready",
                    "BooleanEquals": True,
                    "Next": "UpdateDnsRecord",
                }
            ],
            "Default": "StartEc2IfNeeded",
        },
        "StartEc2IfNeeded": {
            **invoke("start_ec2", state_path="$.reconcile.state", failure_state="SetEc2Failure"),
            "ResultPath": "$.ec2_start",
            "OutputPath": "$",
            "Next": "InitEc2Poll",
        },
        "InitEc2Poll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.ec2_poll",
            "Next": "WaitEc2Running",
        },
        "WaitEc2Running": {"Type": "Wait", "Seconds": 30, "Next": "IncrementEc2Poll"},
        "IncrementEc2Poll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.ec2_poll.count, 1)"},
            "ResultPath": "$.ec2_poll",
            "Next": "Ec2PollWithinDeadline",
        },
        "Ec2PollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.ec2_poll.count",
                    "NumericGreaterThanEquals": 10,
                    "Next": "SetEc2Timeout",
                }
            ],
            "Default": "RenewBeforeEc2Probe",
        },
        "RenewBeforeEc2Probe": {
            **invoke("renew", failure_state="SetLockLostFailure"),
            "ResultPath": "$.lease",
            "OutputPath": "$",
            "Next": "ReconcileEc2",
        },
        "ReconcileEc2": {**reconcile, "Next": "Ec2Running"},
        "Ec2Running": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reconcile.state.observation.ec2_state",
                    "StringEquals": "running",
                    "Next": "InitSsmPoll",
                }
            ],
            "Default": "WaitEc2Running",
        },
        "InitSsmPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.ssm_poll",
            "Next": "WaitSsmOnline",
        },
        "WaitSsmOnline": {"Type": "Wait", "Seconds": 30, "Next": "IncrementSsmPoll"},
        "IncrementSsmPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.ssm_poll.count, 1)"},
            "ResultPath": "$.ssm_poll",
            "Next": "SsmPollWithinDeadline",
        },
        "SsmPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.ssm_poll.count",
                    "NumericGreaterThanEquals": 10,
                    "Next": "SetSsmTimeout",
                }
            ],
            "Default": "RenewBeforeSsmProbe",
        },
        "RenewBeforeSsmProbe": {
            **invoke("renew", failure_state="SetLockLostFailure"),
            "ResultPath": "$.lease",
            "OutputPath": "$",
            "Next": "ReconcileSsm",
        },
        "ReconcileSsm": {**reconcile, "Next": "SsmOnline"},
        "SsmOnline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reconcile.state.observation.ssm_state",
                    "StringEquals": "online",
                    "Next": "RunStartScript",
                }
            ],
            "Default": "WaitSsmOnline",
        },
        "RunStartScript": {
            **invoke("run_host_start", failure_state="SetHostFailure"),
            "ResultPath": "$.host_start",
            "OutputPath": "$",
            "Next": "InitHostPoll",
        },
        "InitHostPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.host_poll",
            "Next": "WaitHostStart",
        },
        "WaitHostStart": {"Type": "Wait", "Seconds": 15, "Next": "IncrementHostPoll"},
        "IncrementHostPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.host_poll.count, 1)"},
            "ResultPath": "$.host_poll",
            "Next": "HostPollWithinDeadline",
        },
        "HostPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.host_poll.count",
                    "NumericGreaterThanEquals": 24,
                    "Next": "SetHostTimeout",
                }
            ],
            "Default": "RenewBeforeHostCheck",
        },
        "RenewBeforeHostCheck": {
            **invoke("renew", failure_state="SetLockLostFailure"),
            "ResultPath": "$.lease",
            "OutputPath": "$",
            "Next": "CheckHostStart",
        },
        "CheckHostStart": {
            **invoke("check_host_start", failure_state="SetHostFailure"),
            "Parameters": {
                "FunctionName": start_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "check_host_start",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "command_id.$": "$.host_start.Payload.command_id",
                },
            },
            "ResultPath": "$.host_check",
            "OutputPath": "$",
            "Next": "HostStartComplete",
        },
        "HostStartComplete": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.host_check.Payload.complete",
                    "BooleanEquals": True,
                    "Next": "InitReadyPoll",
                }
            ],
            "Default": "WaitHostStart",
        },
        "InitReadyPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.ready_poll",
            "Next": "WaitReady",
        },
        "WaitReady": {
            "Type": "Wait",
            "Seconds": lease_renew_seconds,
            "Next": "IncrementReadyPoll",
        },
        "IncrementReadyPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.ready_poll.count, 1)"},
            "ResultPath": "$.ready_poll",
            "Next": "ReadyPollWithinDeadline",
        },
        "ReadyPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.ready_poll.count",
                    "NumericGreaterThanEquals": 5,
                    "Next": "SetReadyTimeout",
                }
            ],
            "Default": "RenewBeforeReadyProbe",
        },
        "RenewBeforeReadyProbe": {
            **invoke("renew", failure_state="SetLockLostFailure"),
            "ResultPath": "$.lease",
            "OutputPath": "$",
            "Next": "ReconcileReady",
        },
        "ReconcileReady": {**reconcile, "Next": "RuntimeReady"},
        "RuntimeReady": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reconcile.state.observation.runtime_ready",
                    "BooleanEquals": True,
                    "Next": "UpdateDnsRecord",
                }
            ],
            "Default": "WaitReady",
        },
        "UpdateDnsRecord": {
            **invoke(
                "upsert_dns",
                state_path="$.reconcile.state",
                failure_state="SetEndpointFailure",
            ),
            "ResultPath": "$.dns_change",
            "OutputPath": "$",
            "Next": "InitDnsPoll",
        },
        "InitDnsPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.dns_poll",
            "Next": "WaitDnsInSync",
        },
        "WaitDnsInSync": {"Type": "Wait", "Seconds": 30, "Next": "IncrementDnsPoll"},
        "IncrementDnsPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.dns_poll.count, 1)"},
            "ResultPath": "$.dns_poll",
            "Next": "DnsPollWithinDeadline",
        },
        "DnsPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.dns_poll.count",
                    "NumericGreaterThanEquals": 4,
                    "Next": "SetEndpointFailure",
                }
            ],
            "Default": "RenewBeforeDnsProbe",
        },
        "RenewBeforeDnsProbe": {
            **invoke("renew", failure_state="SetLockLostFailure"),
            "ResultPath": "$.lease",
            "OutputPath": "$",
            "Next": "CheckDnsChange",
        },
        "CheckDnsChange": {
            **invoke("check_dns_change", failure_state="SetEndpointFailure"),
            "Parameters": {
                "FunctionName": start_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "check_dns_change",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "change_id.$": "$.dns_change.Payload.change_id",
                },
            },
            "ResultPath": "$.dns_check",
            "OutputPath": "$",
            "Next": "DnsChangeInSync",
        },
        "DnsChangeInSync": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.dns_check.Payload.complete",
                    "BooleanEquals": True,
                    "Next": "ReconcileDns",
                }
            ],
            "Default": "WaitDnsInSync",
        },
        "ReconcileDns": {**reconcile, "Next": "EndpointReady"},
        "EndpointReady": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reconcile.state.health",
                    "StringEquals": "HEALTHY",
                    "Next": "MarkSucceeded",
                }
            ],
            "Default": "WaitDnsInSync",
        },
        "MarkSucceeded": {
            **invoke(
                "complete",
                state_path="$.reconcile.state",
                failure_state="SetEndpointFailure",
            ),
            "End": True,
        },
        "SetPreconditionFailure": {
            "Type": "Pass",
            "Result": {"error_code": "START_PRECONDITION_FAILED"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetEc2Failure": {
            "Type": "Pass",
            "Result": {"error_code": "EC2_START_FAILED"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetEc2Timeout": {
            "Type": "Pass",
            "Result": {"error_code": "EC2_START_TIMEOUT"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetSsmTimeout": {
            "Type": "Pass",
            "Result": {"error_code": "SSM_ONLINE_TIMEOUT"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetHostFailure": {
            "Type": "Pass",
            "Result": {"error_code": "SSM_COMMAND_FAILED"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetHostTimeout": {
            "Type": "Pass",
            "Result": {"error_code": "SSM_COMMAND_TIMEOUT"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetReadyTimeout": {
            "Type": "Pass",
            "Result": {"error_code": "MINECRAFT_READY_TIMEOUT"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetEndpointFailure": {
            "Type": "Pass",
            "Result": {"error_code": "ENDPOINT_DISCREPANCY"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetObservationFailure": {
            "Type": "Pass",
            "Result": {"error_code": "OBSERVATION_FAILED"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "SetLockLostFailure": {
            "Type": "Pass",
            "Result": {"error_code": "LOCK_LOST"},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        },
        "ReconcileAfterFailure": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": reconcile_arn,
                "Payload": {"schema_version": 1, "operation": "reconcile"},
            },
            "ResultPath": "$.failure_reconcile",
            "Next": "RecordFailure",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "UnrecoverableFailure"}],
        },
        "RecordFailure": {
            **invoke("fail", failure_state="UnrecoverableFailure"),
            "Parameters": {
                "FunctionName": start_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "fail",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "error_code.$": "$.failure.error_code",
                    "workflow_error.$": "$.workflow_error",
                },
            },
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "UnrecoverableFailure"}],
            "Next": "StartFailed",
        },
        "StartFailed": {"Type": "Fail", "Error": "START_WORKFLOW_FAILED"},
        "UnrecoverableFailure": {"Type": "Fail", "Error": "START_CLEANUP_FAILED"},
    }
    return {
        "Comment": "Wishicraft Phase 5 START; Desired remains RUNNING after post-CAS failure",
        "StartAt": "InitializeWorkflow",
        "TimeoutSeconds": 1800,
        "States": states,
    }


def _stop_definition(
    *, reconcile_arn: str, stop_task_arn: str, lease_renew_seconds: int
) -> dict[str, object]:
    def invoke(action: str, failure: str, *, state: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "action": action,
            "operation_id.$": "$.operation_id",
            "lease_id.$": "$.lease_id",
        }
        if state:
            payload["state.$"] = "$.reconcile.state"
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {"FunctionName": stop_task_arn, "Payload": payload},
            "Retry": [
                {
                    "ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
                    "IntervalSeconds": 2,
                    "MaxAttempts": 3,
                    "BackoffRate": 2,
                }
            ],
            "Catch": [
                {"ErrorEquals": ["States.ALL"], "ResultPath": "$.workflow_error", "Next": failure}
            ],
        }

    def reconcile(next_state: str) -> dict[str, object]:
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": reconcile_arn,
                "Payload": {"schema_version": 1, "operation": "reconcile"},
            },
            "ResultSelector": {"state.$": "$.Payload"},
            "ResultPath": "$.reconcile",
            "Next": next_state,
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "ResultPath": "$.workflow_error",
                    "Next": "SetObservationFailure",
                }
            ],
        }

    states: dict[str, object] = {
        "InitializeWorkflow": {
            "Type": "Pass",
            "Result": {},
            "ResultPath": "$.workflow_error",
            "Next": "ReconcileBeforeStop",
        },
        "ReconcileBeforeStop": reconcile("SetDesiredStopped"),
        "SetDesiredStopped": {
            **invoke("set_desired", "SetPreconditionFailure", state=True),
            "ResultPath": "$.desired",
            "Next": "AlreadyEc2Stopped",
        },
        "AlreadyEc2Stopped": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.desired.Payload.already_stopped",
                    "BooleanEquals": True,
                    "Next": "RenewBeforeDnsDelete",
                }
            ],
            "Default": "AlreadyRuntimeStopped",
        },
        "AlreadyRuntimeStopped": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.desired.Payload.runtime_stopped",
                    "BooleanEquals": True,
                    "Next": "RenewBeforeEc2Stop",
                }
            ],
            "Default": "RenewBeforeHostStop",
        },
        "RenewBeforeHostStop": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "RunHostStop",
        },
        "RunHostStop": {
            **invoke("run_host_stop", "SetHostFailure"),
            "ResultPath": "$.host_stop",
            "Next": "InitHostPoll",
        },
        "InitHostPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.host_poll",
            "Next": "WaitHostStop",
        },
        "WaitHostStop": {"Type": "Wait", "Seconds": 15, "Next": "IncrementHostPoll"},
        "IncrementHostPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.host_poll.count, 1)"},
            "ResultPath": "$.host_poll",
            "Next": "HostPollWithinDeadline",
        },
        "HostPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.host_poll.count",
                    "NumericGreaterThanEquals": 28,
                    "Next": "SetRuntimeTimeout",
                }
            ],
            "Default": "RenewBeforeHostCheck",
        },
        "RenewBeforeHostCheck": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "CheckHostStop",
        },
        "CheckHostStop": {
            **invoke("check_host_stop", "SetHostFailure"),
            "Parameters": {
                "FunctionName": stop_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "check_host_stop",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "command_id.$": "$.host_stop.Payload.command_id",
                },
            },
            "ResultPath": "$.host_check",
            "Next": "HostStopComplete",
        },
        "HostStopComplete": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.host_check.Payload.complete",
                    "BooleanEquals": True,
                    "Next": "ReconcileRuntimeStopped",
                }
            ],
            "Default": "WaitHostStop",
        },
        "ReconcileRuntimeStopped": reconcile("RuntimeStopped"),
        "RuntimeStopped": {
            "Type": "Choice",
            "Choices": [
                {
                    "And": [
                        {
                            "Variable": "$.reconcile.state.observation.host_runtime_state",
                            "StringEquals": "not-running",
                        },
                        {
                            "Variable": "$.reconcile.state.observation.minecraft_service_state",
                            "StringEquals": "not-running",
                        },
                        {
                            "Variable": "$.reconcile.state.observation.minecraft_protocol_state",
                            "StringEquals": "not-applicable",
                        },
                    ],
                    "Next": "RenewBeforeEc2Stop",
                }
            ],
            "Default": "SetRuntimeTimeout",
        },
        "RenewBeforeEc2Stop": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "StopEc2",
        },
        "StopEc2": {
            **invoke("stop_ec2", "SetEc2Failure", state=True),
            "ResultPath": "$.ec2_stop",
            "Next": "InitEc2Poll",
        },
        "InitEc2Poll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.ec2_poll",
            "Next": "WaitEc2Stopped",
        },
        "WaitEc2Stopped": {"Type": "Wait", "Seconds": 30, "Next": "IncrementEc2Poll"},
        "IncrementEc2Poll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.ec2_poll.count, 1)"},
            "ResultPath": "$.ec2_poll",
            "Next": "Ec2PollWithinDeadline",
        },
        "Ec2PollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.ec2_poll.count",
                    "NumericGreaterThanEquals": 10,
                    "Next": "SetEc2Timeout",
                }
            ],
            "Default": "RenewBeforeEc2Probe",
        },
        "RenewBeforeEc2Probe": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "ReconcileEc2Stopped",
        },
        "ReconcileEc2Stopped": reconcile("Ec2Stopped"),
        "Ec2Stopped": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.reconcile.state.observation.ec2_state",
                    "StringEquals": "stopped",
                    "Next": "RenewBeforeDnsDelete",
                }
            ],
            "Default": "WaitEc2Stopped",
        },
        "RenewBeforeDnsDelete": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "DeleteDns",
        },
        "DeleteDns": {
            **invoke("delete_dns", "SetDnsFailure"),
            "ResultPath": "$.dns_delete",
            "Next": "DnsAlreadyAbsent",
        },
        "DnsAlreadyAbsent": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.dns_delete.Payload.absent",
                    "BooleanEquals": True,
                    "Next": "ReconcileAfterStop",
                }
            ],
            "Default": "InitDnsPoll",
        },
        "InitDnsPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.dns_poll",
            "Next": "WaitDnsInSync",
        },
        "WaitDnsInSync": {"Type": "Wait", "Seconds": 30, "Next": "IncrementDnsPoll"},
        "IncrementDnsPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.dns_poll.count, 1)"},
            "ResultPath": "$.dns_poll",
            "Next": "DnsPollWithinDeadline",
        },
        "DnsPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.dns_poll.count",
                    "NumericGreaterThanEquals": 4,
                    "Next": "SetDnsTimeout",
                }
            ],
            "Default": "RenewBeforeDnsCheck",
        },
        "RenewBeforeDnsCheck": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.lease",
            "Next": "CheckDnsChange",
        },
        "CheckDnsChange": {
            **invoke("check_dns_change", "SetDnsFailure"),
            "Parameters": {
                "FunctionName": stop_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "check_dns_change",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "change_id.$": "$.dns_delete.Payload.change_id",
                },
            },
            "ResultPath": "$.dns_check",
            "Next": "DnsInSync",
        },
        "DnsInSync": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.dns_check.Payload.complete",
                    "BooleanEquals": True,
                    "Next": "ReconcileAfterStop",
                }
            ],
            "Default": "WaitDnsInSync",
        },
        "ReconcileAfterStop": reconcile("MarkSucceeded"),
        "MarkSucceeded": {**invoke("complete", "SetObservationFailure", state=True), "End": True},
    }
    failures = {
        "SetPreconditionFailure": "STOP_PRECONDITION_FAILED",
        "SetHostFailure": "GRACEFUL_RUNTIME_STOP_FAILED",
        "SetRuntimeTimeout": "MINECRAFT_STOP_TIMEOUT",
        "SetEc2Failure": "EC2_STOP_FAILED",
        "SetEc2Timeout": "EC2_STOP_TIMEOUT",
        "SetDnsFailure": "DNS_DELETE_FAILED",
        "SetDnsTimeout": "DNS_INSYNC_TIMEOUT",
        "SetObservationFailure": "OBSERVATION_FAILED",
        "SetLockLostFailure": "LOCK_LOST",
    }
    for name, code in failures.items():
        states[name] = {
            "Type": "Pass",
            "Result": {"error_code": code},
            "ResultPath": "$.failure",
            "Next": "ReconcileAfterFailure",
        }
    states.update(
        {
            "ReconcileAfterFailure": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": {
                    "FunctionName": reconcile_arn,
                    "Payload": {"schema_version": 1, "operation": "reconcile"},
                },
                "ResultPath": "$.failure_reconcile",
                "Next": "RecordFailure",
                "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "UnrecoverableFailure"}],
            },
            "RecordFailure": {
                **invoke("fail", "UnrecoverableFailure"),
                "Parameters": {
                    "FunctionName": stop_task_arn,
                    "Payload": {
                        "schema_version": 1,
                        "action": "fail",
                        "operation_id.$": "$.operation_id",
                        "lease_id.$": "$.lease_id",
                        "error_code.$": "$.failure.error_code",
                        "workflow_error.$": "$.workflow_error",
                    },
                },
                "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "UnrecoverableFailure"}],
                "Next": "StopFailed",
            },
            "StopFailed": {"Type": "Fail", "Error": "STOP_WORKFLOW_FAILED"},
            "UnrecoverableFailure": {"Type": "Fail", "Error": "STOP_CLEANUP_FAILED"},
        }
    )
    return {
        "Comment": "Wishicraft Phase 6 STOP; Desired remains STOPPED after post-CAS failure",
        "StartAt": "InitializeWorkflow",
        "TimeoutSeconds": 1200,
        "States": states,
    }


def _backup_definition(
    *, reconcile_arn: str, backup_task_arn: str, poll_seconds: int, timeout_seconds: int
) -> dict[str, object]:
    """Build a one-create-attempt workflow; polling may retry but snapshot creation may not."""
    max_polls = max(1, (timeout_seconds // poll_seconds) - 1)

    def invoke(action: str, failure: str) -> dict[str, object]:
        return {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": backup_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": action,
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                },
            },
            "Catch": [
                {"ErrorEquals": ["States.ALL"], "ResultPath": "$.workflow_error", "Next": failure}
            ],
        }

    states: dict[str, object] = {
        "ReconcileBeforeBackup": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": reconcile_arn,
                "Payload": {"schema_version": 1, "operation": "reconcile"},
            },
            "ResultSelector": {"state.$": "$.Payload"},
            "ResultPath": "$.reconcile",
            "Next": "ValidateStoppedHealthy",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "SetObservationFailure"}],
        },
        "ValidateStoppedHealthy": {
            **invoke("preflight", "SetPreconditionFailure"),
            "Parameters": {
                "FunctionName": backup_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "preflight",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "state.$": "$.reconcile.state",
                },
            },
            "ResultPath": "$.preflight",
            "Next": "CreateSnapshotOnce",
        },
        "CreateSnapshotOnce": {
            **invoke("create", "SetCreateFailure"),
            "ResultPath": "$.snapshot",
            "Next": "InitializeSnapshotPoll",
        },
        "InitializeSnapshotPoll": {
            "Type": "Pass",
            "Result": {"count": 0},
            "ResultPath": "$.snapshot_poll",
            "Next": "WaitSnapshot",
        },
        "WaitSnapshot": {"Type": "Wait", "Seconds": poll_seconds, "Next": "RenewLease"},
        "RenewLease": {
            **invoke("renew", "SetLockLostFailure"),
            "ResultPath": "$.renewal",
            "Next": "PollSnapshot",
        },
        "PollSnapshot": {
            **invoke("poll", "SetSnapshotFailure"),
            "Parameters": {
                "FunctionName": backup_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "poll",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "snapshot_id.$": "$.snapshot.Payload.snapshot_id",
                },
            },
            "ResultPath": "$.snapshot_status",
            "Next": "SnapshotCompleted",
        },
        "SnapshotCompleted": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.snapshot_status.Payload.complete",
                    "BooleanEquals": True,
                    "Next": "VerifyAndComplete",
                }
            ],
            "Default": "IncrementSnapshotPoll",
        },
        "IncrementSnapshotPoll": {
            "Type": "Pass",
            "Parameters": {"count.$": "States.MathAdd($.snapshot_poll.count, 1)"},
            "ResultPath": "$.snapshot_poll",
            "Next": "SnapshotPollWithinDeadline",
        },
        "SnapshotPollWithinDeadline": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.snapshot_poll.count",
                    "NumericGreaterThanEquals": max_polls,
                    "Next": "SetSnapshotTimeout",
                }
            ],
            "Default": "WaitSnapshot",
        },
        "VerifyAndComplete": {
            **invoke("complete", "SetVerificationFailure"),
            "Parameters": {
                "FunctionName": backup_task_arn,
                "Payload": {
                    "schema_version": 1,
                    "action": "complete",
                    "operation_id.$": "$.operation_id",
                    "lease_id.$": "$.lease_id",
                    "snapshot_id.$": "$.snapshot.Payload.snapshot_id",
                    "tags.$": "$.snapshot.Payload.tags",
                },
            },
            "End": True,
        },
    }
    failures = {
        "SetObservationFailure": "OBSERVATION_FAILED",
        "SetPreconditionFailure": "BACKUP_PRECONDITION_FAILED",
        "SetCreateFailure": "BACKUP_SNAPSHOT_CREATE_FAILED",
        "SetSnapshotFailure": "BACKUP_SNAPSHOT_FAILED",
        "SetSnapshotTimeout": "BACKUP_SNAPSHOT_TIMEOUT",
        "SetVerificationFailure": "BACKUP_SNAPSHOT_VERIFICATION_FAILED",
        "SetLockLostFailure": "LOCK_LOST",
    }
    for name, code in failures.items():
        states[name] = {
            "Type": "Pass",
            "Result": {"error_code": code},
            "ResultPath": "$.failure",
            "Next": "RecordFailure",
        }
    states["RecordFailure"] = {
        **invoke("fail", "UnrecoverableFailure"),
        "Parameters": {
            "FunctionName": backup_task_arn,
            "Payload": {
                "schema_version": 1,
                "action": "fail",
                "operation_id.$": "$.operation_id",
                "lease_id.$": "$.lease_id",
                "error_code.$": "$.failure.error_code",
            },
        },
        "Next": "BackupFailed",
    }
    states["BackupFailed"] = {"Type": "Fail", "Error": "BACKUP_WORKFLOW_FAILED"}
    states["UnrecoverableFailure"] = {"Type": "Fail", "Error": "BACKUP_CLEANUP_FAILED"}
    return {
        "Comment": "Wishicraft Phase 8A stopped-only Data EBS snapshot backup",
        "StartAt": "ReconcileBeforeBackup",
        "TimeoutSeconds": timeout_seconds,
        "States": states,
    }
