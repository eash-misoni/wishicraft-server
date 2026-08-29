"""Independent Phase 3/4 Control Plane persistence and admission stack."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Duration, Environment, RemovalPolicy, Stack, Tags
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_stepfunctions as sfn
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
                actions=["states:StartExecution"], resources=[start_workflow.attr_arn]
            )
        )
        admission.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:DescribeExecution"],
                resources=[
                    (
                        f"arn:aws:states:{stage.aws_region}:{stage.aws_account_id}:execution:"
                        f"{resource_name(project.resource_prefix, stage.stage, 'start')}:*"
                    )
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


def _start_definition(
    *, reconcile_arn: str, start_task_arn: str, lease_renew_seconds: int
) -> dict[str, object]:
    def invoke(
        action: str,
        *,
        state_path: str | None = None,
        failure_state: str = "SetTaskFailure",
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
        "SetTaskFailure": {
            "Type": "Pass",
            "Result": {"error_code": "INTERNAL_ERROR"},
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
