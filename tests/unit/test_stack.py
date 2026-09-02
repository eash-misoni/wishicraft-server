from __future__ import annotations

import base64
import gzip
from pathlib import Path
from typing import cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft.config import ConfigValidationError, load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _find_key(value: object, key: str, path: str = "$") -> list[tuple[str, object]]:
    matches: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            child_path = f"{path}.{child_key}"
            if child_key == key:
                matches.append((child_path, child_value))
            matches.extend(_find_key(child_value, key, child_path))
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            matches.extend(_find_key(child_value, key, f"{path}[{index}]"))
    return matches


def _resolve_user_data(value: object, references: dict[str, str]) -> str:
    if isinstance(value, str):
        return value
    assert isinstance(value, dict)
    if set(value) == {"Fn::Join"}:
        delimiter, values = value["Fn::Join"]
        assert isinstance(delimiter, str)
        assert isinstance(values, list)
        return delimiter.join(_resolve_user_data(item, references) for item in values)
    if set(value) == {"Ref"}:
        reference = value["Ref"]
        assert isinstance(reference, str)
        return references[reference]
    raise AssertionError(f"Unsupported UserData expression: {value!r}")


def _action_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    assert isinstance(value, list)
    assert all(isinstance(action, str) for action in value)
    return cast(list[str], value)


def test_control_plane_stack_adds_phase_six_stop_without_target_resources() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=6, deployment="control-plane")
    stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::DynamoDB::Table", 5)
    template.resource_count_is("AWS::Lambda::Function", 4)
    template.resource_count_is("AWS::Logs::LogGroup", 4)
    assert template.find_resources("AWS::EC2::Instance") == {}
    assert template.find_resources("AWS::EC2::VolumeAttachment") == {}
    tables = template.find_resources("AWS::DynamoDB::Table")
    table_names = {table["Properties"]["TableName"] for table in tables.values()}
    assert table_names == {
        "wc-dev-system-state",
        "wc-dev-games",
        "wc-dev-operations",
        "wc-dev-idempotency",
        "wc-dev-locks",
    }
    table = next(
        value["Properties"]
        for value in tables.values()
        if value["Properties"]["TableName"] == "wc-dev-system-state"
    )
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    assert table["KeySchema"] == [{"AttributeName": "system_id", "KeyType": "HASH"}]
    assert "StreamSpecification" not in table
    assert "TimeToLiveSpecification" not in table
    assert "GlobalSecondaryIndexes" not in table

    functions = template.find_resources("AWS::Lambda::Function")
    function = next(
        value["Properties"]
        for value in functions.values()
        if value["Properties"]["FunctionName"] == "wc-dev-reconcile"
    )
    environment = function["Environment"]["Variables"]
    assert "INSTANCE_ID" not in environment
    assert environment["GAME_ID"] == "game-vanilla-main"
    assert "i-04fc0629dc4ea466e" not in str(template.to_json())

    actions = {
        action
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        for action in _action_list(statement["Action"])
    }
    assert {
        "ec2:DescribeInstances",
        "ssm:DescribeInstanceInformation",
        "ssm:SendCommand",
        "ssm:GetCommandInvocation",
        "route53:ListResourceRecordSets",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:TransactWriteItems",
    } <= actions
    assert "ec2:TerminateInstances" not in actions
    assert "ssm:GetParameter" not in actions
    template.resource_count_is("AWS::StepFunctions::StateMachine", 2)
    assert "ec2:StartInstances" in actions
    assert "ec2:StopInstances" in actions
    assert "route53:ChangeResourceRecordSets" in actions
    state_machines = template.find_resources("AWS::StepFunctions::StateMachine")
    state_machine = next(
        value["Properties"]
        for value in state_machines.values()
        if value["Properties"]["StateMachineName"] == "wc-dev-start"
    )
    definition = state_machine["Definition"]
    states = definition["States"]
    assert definition["TimeoutSeconds"] == 1800
    assert states["WaitReady"]["Seconds"] == 120
    assert states["SetEc2Timeout"]["Result"]["error_code"] == "EC2_START_TIMEOUT"
    assert states["SetSsmTimeout"]["Result"]["error_code"] == "SSM_ONLINE_TIMEOUT"
    assert states["SetHostTimeout"]["Result"]["error_code"] == "SSM_COMMAND_TIMEOUT"
    assert states["SetReadyTimeout"]["Result"]["error_code"] == "MINECRAFT_READY_TIMEOUT"
    assert states["AlreadyReady"]["Choices"][0]["Next"] == "UpdateDnsRecord"
    assert states["DnsChangeInSync"]["Choices"][0]["Next"] == "ReconcileDns"

    reachable = {definition["StartAt"]}
    pending = [definition["StartAt"]]
    while pending:
        state = states[pending.pop()]
        targets = [
            state.get("Next"),
            state.get("Default"),
            *(choice.get("Next") for choice in state.get("Choices", [])),
            *(catch.get("Next") for catch in state.get("Catch", [])),
        ]
        for target in targets:
            if target is not None and target not in reachable:
                reachable.add(target)
                pending.append(target)
    assert reachable == set(states)

    stop_definition = next(
        value["Properties"]["Definition"]
        for value in state_machines.values()
        if value["Properties"]["StateMachineName"] == "wc-dev-stop"
    )
    stop_states = stop_definition["States"]
    assert stop_definition["TimeoutSeconds"] == 1200
    assert stop_states["RuntimeStopped"]["Choices"][0]["Next"] == "RenewBeforeEc2Stop"
    assert stop_states["Ec2Stopped"]["Choices"][0]["Next"] == "RenewBeforeDnsDelete"
    assert stop_states["SetDnsTimeout"]["Result"]["error_code"] == "DNS_INSYNC_TIMEOUT"
    assert stop_states["SetLockLostFailure"]["Result"]["error_code"] == "LOCK_LOST"
    assert stop_states["RenewBeforeHostStop"]["Next"] == "RunHostStop"
    assert stop_states["RenewBeforeEc2Stop"]["Next"] == "StopEc2"
    assert stop_states["RenewBeforeDnsDelete"]["Next"] == "DeleteDns"
    assert stop_states["SetLockLostFailure"]["Next"] == "ReconcileAfterFailure"
    assert stop_states["AlreadyEc2Stopped"]["Choices"][0]["Next"] == ("RenewBeforeDnsDelete")
    stop_reachable = {stop_definition["StartAt"]}
    stop_pending = [stop_definition["StartAt"]]
    while stop_pending:
        stop_state = stop_states[stop_pending.pop()]
        stop_targets = [
            stop_state.get("Next"),
            stop_state.get("Default"),
            *(choice.get("Next") for choice in stop_state.get("Choices", [])),
            *(catch.get("Next") for catch in stop_state.get("Catch", [])),
        ]
        for target in stop_targets:
            if target is not None and target not in stop_reachable:
                stop_reachable.add(target)
                stop_pending.append(target)
    assert stop_reachable == set(stop_states)

    admission = next(
        value["Properties"]
        for value in functions.values()
        if value["Properties"]["FunctionName"] == "wc-dev-admission"
    )
    admission_environment = admission["Environment"]["Variables"]
    assert admission_environment["SYSTEM_ID"] == "wishicraft-main"
    assert admission_environment["GAME_ID"] == "game-vanilla-main"
    assert admission_environment["GLOBAL_LOCK_NAME"] == "minecraft-control"
    assert admission_environment["LOCK_LEASE_SECONDS"] == "900"
    assert "INSTANCE_ID" not in admission_environment
    admission_role = admission["Role"]["Fn::GetAtt"][0]
    admission_policies = [
        policy["Properties"]["PolicyDocument"]
        for policy in template.find_resources("AWS::IAM::Policy").values()
        if {"Ref": admission_role} in policy["Properties"]["Roles"]
    ]
    admission_actions = {
        action
        for policy in admission_policies
        for statement in policy["Statement"]
        for action in _action_list(statement["Action"])
    }
    assert admission_actions == {
        "dynamodb:ConditionCheckItem",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:TransactWriteItems",
        "dynamodb:UpdateItem",
        "states:DescribeExecution",
        "states:StartExecution",
    }
    statements = [
        statement
        for policy in template.find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    send_command = [
        statement
        for statement in statements
        if "ssm:SendCommand" in _action_list(statement["Action"])
    ]
    assert len(send_command) == 6
    assert any(
        "document/AWS-RunShellScript" in str(statement["Resource"]) for statement in send_command
    )
    target_statement = next(
        statement for statement in send_command if ":instance/*" in str(statement["Resource"])
    )
    assert target_statement["Condition"]["StringEquals"] == {
        "ssm:resourceTag/Project": "wishicraft",
        "ssm:resourceTag/Purpose": "phase2-target-validation",
        "ssm:resourceTag/Stage": "dev",
    }
    route53_statement = next(
        statement
        for statement in statements
        if "route53:ListResourceRecordSets" in _action_list(statement["Action"])
    )
    assert route53_statement["Resource"] == "arn:aws:route53:::hostedzone/Z077818024BJUAUBFMTKV"


def test_dev_stack_is_empty_and_environment_agnostic() -> None:
    app = build_app(REPOSITORY_ROOT, "dev")

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    assert template.find_resources("AWS::EC2::Instance") == {}
    assert stack.environment == "aws://unknown-account/unknown-region"


def test_phase_eight_backup_is_data_volume_only_and_has_no_destructive_iam() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=8, deployment="control-plane")
    stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    template = Template.from_stack(stack)
    functions = template.find_resources("AWS::Lambda::Function")
    backup = next(
        value["Properties"]
        for value in functions.values()
        if value["Properties"]["FunctionName"] == "wc-dev-backup-task"
    )
    assert backup["Environment"]["Variables"]["DATA_VOLUME_ID"] == "vol-03ac9f534326c345c"
    policies = template.find_resources("AWS::IAM::Policy")
    backup_role = backup["Role"]["Fn::GetAtt"][0]
    actions = {
        action
        for policy in policies.values()
        if {"Ref": backup_role} in policy["Properties"]["Roles"]
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        for action in _action_list(statement["Action"])
    }
    assert {"ec2:CreateSnapshot", "ec2:DescribeSnapshots", "ec2:DescribeVolumes"} <= actions
    assert not actions & {
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:AttachVolume",
        "ec2:DetachVolume",
        "ec2:DeleteVolume",
        "ec2:DeleteSnapshot",
        "ssm:SendCommand",
        "route53:ChangeResourceRecordSets",
        "ssm:GetParameter",
    }
    machines = template.find_resources("AWS::StepFunctions::StateMachine")
    definition = next(
        value["Properties"]["Definition"]
        for value in machines.values()
        if value["Properties"]["StateMachineName"] == "wc-dev-backup"
    )
    assert definition["TimeoutSeconds"] == 900
    assert definition["States"]["CreateSnapshotOnce"].get("Retry") is None
    assert definition["States"]["WaitSnapshot"]["Seconds"] == 120
    assert definition["States"]["SetSnapshotTimeout"]["Result"]["error_code"] == (
        "BACKUP_SNAPSHOT_TIMEOUT"
    )


def test_phase_one_network_uses_configured_public_subnet_and_internet_gateway() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)

    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    assert stack.environment == "aws://unknown-account/unknown-region"
    template.resource_count_is("AWS::EC2::Subnet", 1)
    template.resource_count_is("AWS::EC2::InternetGateway", 1)

    subnet = next(iter(template.find_resources("AWS::EC2::Subnet").values()))
    assert subnet["Properties"]["AvailabilityZone"] == configuration.stage.availability_zone

    internet_gateway_ids = set(template.find_resources("AWS::EC2::InternetGateway"))
    routes = template.find_resources("AWS::EC2::Route")
    assert any(
        route["Properties"].get("GatewayId", {}).get("Ref") in internet_gateway_ids
        for route in routes.values()
    )


def test_phase_one_network_allows_only_configured_minecraft_tcp_ingress() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    security_groups = template.find_resources("AWS::EC2::SecurityGroup")
    minecraft_group = next(
        group
        for group in security_groups.values()
        if group["Properties"]["GroupDescription"] == "Minecraft client ingress only"
    )
    ingress_rules = minecraft_group["Properties"]["SecurityGroupIngress"]
    assert ingress_rules == [
        {
            "CidrIp": "0.0.0.0/0",
            "Description": "Minecraft client connections",
            "FromPort": configuration.stage.minecraft_port,
            "IpProtocol": "tcp",
            "ToPort": configuration.stage.minecraft_port,
        }
    ]
    assert template.find_resources("AWS::EC2::NatGateway") == {}
    assert template.find_resources("AWS::EC2::EIP") == {}


def test_phase_seven_command_ingress_has_no_control_plane_or_secret_permissions() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=7, deployment="control-plane")
    stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    template = Template.from_stack(stack)

    functions = template.find_resources("AWS::Lambda::Function")
    command_logical_id, command = next(
        (logical_id, value)
        for logical_id, value in functions.items()
        if value["Properties"]["FunctionName"] == "wc-dev-discord-command"
    )
    properties = command["Properties"]
    assert properties["Handler"] == "wishicraft.discord_command_lambda.handler"
    assert properties["Runtime"] == "python3.12"
    assert properties["Timeout"] == 10
    environment = properties["Environment"]["Variables"]
    assert set(environment) == {
        "DISCORD_APPLICATION_ID",
        "DISCORD_GUILD_ID",
        "DISCORD_OPERATION_CHANNEL_ID",
        "DISCORD_PLAYER_ROLE_ID",
        "DISCORD_ADMIN_ROLE_ID",
        "DISCORD_PUBLIC_KEY",
        "ADMISSION_FUNCTION_NAME",
    }
    assert "BOT_TOKEN" not in str(environment)

    role_logical_id = properties["Role"]["Fn::GetAtt"][0]
    command_actions: set[str] = set()
    for policy in template.find_resources("AWS::IAM::Policy").values():
        if {"Ref": role_logical_id} not in policy["Properties"]["Roles"]:
            continue
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            command_actions.update(_action_list(statement["Action"]))
    assert command_actions <= {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "lambda:InvokeFunction",
    }
    assert "lambda:InvokeFunction" in command_actions
    assert not any(
        action.startswith(prefix)
        for action in command_actions
        for prefix in ("ssm:", "states:", "dynamodb:", "ec2:", "route53:", "iam:")
    )

    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    assert len(routes) == 1
    route = next(iter(routes.values()))["Properties"]
    assert route["RouteKey"] == "POST /discord/interactions"
    assert template.resource_count_is("AWS::ApiGatewayV2::Api", 1) is None
    permissions = template.find_resources("AWS::Lambda::Permission")
    command_permissions = [
        item
        for item in permissions.values()
        if command_logical_id in str(item["Properties"].get("FunctionName"))
    ]
    assert len(command_permissions) == 1
    assert command_permissions[0]["Properties"]["Principal"] == "apigateway.amazonaws.com"

    status_logical_id, status_executor = next(
        (logical_id, value)
        for logical_id, value in functions.items()
        if value["Properties"]["FunctionName"] == "wc-dev-status-executor"
    )
    assert status_executor["Properties"]["Handler"] == "wishicraft.status_executor_lambda.handler"
    status_environment = status_executor["Properties"]["Environment"]["Variables"]
    assert set(status_environment) == {
        "OPERATIONS_TABLE",
        "LOCKS_TABLE",
        "SYSTEM_STATE_TABLE",
        "SYSTEM_ID",
        "GLOBAL_LOCK_NAME",
        "RECONCILE_FUNCTION_NAME",
    }
    status_role = status_executor["Properties"]["Role"]["Fn::GetAtt"][0]
    status_actions: set[str] = set()
    for policy in template.find_resources("AWS::IAM::Policy").values():
        if {"Ref": status_role} not in policy["Properties"]["Roles"]:
            continue
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            status_actions.update(_action_list(statement["Action"]))
    assert {"dynamodb:GetItem", "dynamodb:UpdateItem", "lambda:InvokeFunction"} <= status_actions
    assert (
        not {
            "dynamodb:PutItem",
            "dynamodb:DeleteItem",
            "dynamodb:TransactWriteItems",
            "dynamodb:Scan",
            "dynamodb:Query",
        }
        & status_actions
    )
    assert not any(
        action.startswith(prefix)
        for action in status_actions
        for prefix in (
            "ec2:",
            "ssm:SendCommand",
            "route53:",
            "states:",
            "iam:",
            "ssm:GetParameter",
        )
    )
    mappings = template.find_resources("AWS::Lambda::EventSourceMapping")
    status_mapping = next(
        value
        for value in mappings.values()
        if status_logical_id in str(value["Properties"].get("FunctionName"))
    )
    assert status_mapping["Properties"]["BatchSize"] == 1
    assert status_mapping["Properties"]["StartingPosition"] == "LATEST"
    assert status_mapping["Properties"]["MaximumRetryAttempts"] == 2
    assert "STATUS" in str(status_mapping["Properties"]["FilterCriteria"])
    assert "OnFailure" in status_mapping["Properties"]["DestinationConfig"]
    operations_table = next(
        value["Properties"]
        for value in template.find_resources("AWS::DynamoDB::Table").values()
        if value["Properties"]["TableName"] == "wc-dev-operations"
    )
    assert operations_table["StreamSpecification"] == {"StreamViewType": "NEW_AND_OLD_IMAGES"}

    message_logical_id, message = next(
        (logical_id, value)
        for logical_id, value in functions.items()
        if value["Properties"]["FunctionName"] == "wc-dev-discord-message"
    )
    assert message["Properties"]["Handler"] == "wishicraft.discord_message_lambda.handler"
    message_environment = message["Properties"]["Environment"]["Variables"]
    assert set(message_environment) == {
        "OPERATIONS_TABLE",
        "BOT_TOKEN_PARAMETER_NAME",
        "DELIVERY_RETRY_QUEUE_URL",
    }
    assert message_environment["BOT_TOKEN_PARAMETER_NAME"] == (
        "/wishicraft/dev/secret/discord-bot-token"
    )
    message_role = message["Properties"]["Role"]["Fn::GetAtt"][0]
    message_statements = [
        statement
        for policy in template.find_resources("AWS::IAM::Policy").values()
        if {"Ref": message_role} in policy["Properties"]["Roles"]
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    message_actions = {
        action for statement in message_statements for action in _action_list(statement["Action"])
    }
    assert {"dynamodb:GetItem", "dynamodb:UpdateItem", "ssm:GetParameter"} <= message_actions
    assert not any(
        action.startswith(prefix)
        for action in message_actions
        for prefix in ("ec2:", "ssm:SendCommand", "route53:", "states:", "iam:")
    )
    token_statement = next(
        statement
        for statement in message_statements
        if "ssm:GetParameter" in _action_list(statement["Action"])
    )
    assert token_statement["Resource"] == (
        "arn:aws:ssm:ap-northeast-1:385526546525:parameter/wishicraft/dev/secret/discord-bot-token"
    )
    for role_id in (role_logical_id, status_role):
        role_text = "".join(
            str(policy)
            for policy in template.find_resources("AWS::IAM::Policy").values()
            if {"Ref": role_id} in policy["Properties"]["Roles"]
        )
        assert "ssm:GetParameter" not in role_text
        assert "discord-bot-token" not in role_text
    message_mappings = [
        value
        for value in mappings.values()
        if message_logical_id in str(value["Properties"].get("FunctionName"))
    ]
    assert len(message_mappings) == 2
    assert any(
        "MODIFY" in str(mapping["Properties"].get("FilterCriteria")) for mapping in message_mappings
    )
    stream_filter = next(
        str(mapping["Properties"]["FilterCriteria"])
        for mapping in message_mappings
        if "FilterCriteria" in mapping["Properties"]
    )
    assert "INSERT" in stream_filter
    assert "START" in stream_filter
    assert "STOP" in stream_filter
    assert "STATUS" in stream_filter
    assert any(
        "EventSourceArn" in mapping["Properties"]
        and "SQS" not in str(mapping["Properties"].get("FilterCriteria", ""))
        for mapping in message_mappings
    )
    template.resource_count_is("AWS::SQS::Queue", 3)


def test_phase_seven_release_monitoring_is_complete_and_read_only() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=7, deployment="control-plane")
    stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    template = Template.from_stack(stack)

    functions = template.find_resources("AWS::Lambda::Function")
    observer = next(
        value
        for value in functions.values()
        if value["Properties"]["FunctionName"] == "wc-dev-monitoring-observer"
    )
    assert observer["Properties"]["Handler"] == "wishicraft.monitoring_lambda.handler"
    assert observer["Properties"]["Timeout"] == 30
    assert "BOT_TOKEN" not in str(observer)
    observer_role = observer["Properties"]["Role"]["Fn::GetAtt"][0]
    observer_actions = {
        action
        for policy in template.find_resources("AWS::IAM::Policy").values()
        if {"Ref": observer_role} in policy["Properties"]["Roles"]
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        for action in _action_list(statement["Action"])
    }
    assert {
        "dynamodb:GetItem",
        "ec2:DescribeInstances",
        "cloudwatch:PutMetricData",
    } <= observer_actions
    assert not any(
        action.startswith(prefix)
        for action in observer_actions
        for prefix in (
            "ec2:Start",
            "ec2:Stop",
            "ssm:",
            "route53:",
            "states:",
            "sns:",
            "dynamodb:Put",
            "dynamodb:Update",
            "dynamodb:Delete",
            "ssm:GetParameter",
        )
    )

    rules = template.find_resources("AWS::Events::Rule")
    schedule = next(iter(rules.values()))["Properties"]
    assert schedule["ScheduleExpression"] == "rate(5 minutes)"
    assert schedule["State"] == "ENABLED"

    alarms = template.find_resources("AWS::CloudWatch::Alarm")
    names = {alarm["Properties"]["AlarmName"] for alarm in alarms.values()}
    for fragment in (
        "startworkflowfailurealarm",
        "stopworkflowfailurealarm",
        "targetrunningtoolongalarm",
        "desiredstoppedec2runningalarm",
        "desiredactualdivergencealarm",
        "expiredoperationlockalarm",
        "desiredrunningnotreadyalarm",
        "monitoringobservationunknownalarm",
        "errorsalarm",
        "throttlesalarm",
    ):
        assert any(fragment in name for name in names)
    assert len(alarms) == 24
    assert all(alarm["Properties"]["AlarmActions"] for alarm in alarms.values())
    custom = [
        alarm["Properties"]
        for alarm in alarms.values()
        if alarm["Properties"].get("Namespace") == "Wishicraft/ControlPlane"
    ]
    assert len(custom) == 6
    assert all(alarm["TreatMissingData"] == "breaching" for alarm in custom)

    topics = template.find_resources("AWS::SNS::Topic")
    assert len(topics) == 1
    topic = next(iter(topics.values()))["Properties"]
    assert topic["TopicName"] == "wc-dev-monitoring"
    assert "KmsMasterKeyId" in topic
    policies = template.find_resources("AWS::SNS::TopicPolicy")
    policy_text = str(policies)
    assert "cloudwatch.amazonaws.com" in policy_text
    assert "budgets.amazonaws.com" in policy_text

    budgets = template.find_resources("AWS::Budgets::Budget")
    assert len(budgets) == 1
    budget = next(iter(budgets.values()))["Properties"]
    assert budget["Budget"]["BudgetLimit"] == {"Amount": 15, "Unit": "USD"}
    assert len(budget["NotificationsWithSubscribers"]) == 4
    assert all(
        item["Subscribers"][0]["SubscriptionType"] == "SNS"
        for item in budget["NotificationsWithSubscribers"]
    )


def test_phase_one_minecraft_instance_role_has_only_required_ssm_permissions() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    roles = template.find_resources("AWS::IAM::Role")
    minecraft_role = next(
        role
        for role in roles.values()
        if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
    )
    principal = minecraft_role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0][
        "Principal"
    ]
    assert principal == {"Service": "ec2.amazonaws.com"}
    assert "ManagedPolicyArns" not in minecraft_role["Properties"]

    policies = template.find_resources("AWS::IAM::Policy")
    policy = next(iter(policies.values()))["Properties"]["PolicyDocument"]
    statements = policy["Statement"]
    actions = {action for statement in statements for action in _action_list(statement["Action"])}

    assert {
        "ssm:DescribeAssociation",
        "ssm:GetDocument",
        "ssm:UpdateInstanceInformation",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:OpenDataChannel",
        "ec2messages:GetMessages",
        "ec2messages:SendReply",
    } <= actions
    assert "ssm:GetParameter" in actions
    assert (
        not {
            "ssm:GetParameters",
            "ssm:GetParametersByPath",
            "ssm:GetParameterHistory",
            "ssm:DescribeParameters",
        }
        & actions
    )
    assert not any(
        action.startswith(prefix)
        for action in actions
        for prefix in ("kms:", "ec2:", "iam:", "route53:", "s3:", "dynamodb:", "logs:")
    )

    parameter_statement = next(
        statement
        for statement in statements
        if _action_list(statement["Action"]) == ["ssm:GetParameter"]
    )
    parameter_resource = parameter_statement["Resource"]
    assert parameter_resource != "*"
    parameter_resource_text = str(parameter_resource)
    assert configuration.stage.aws_region in parameter_resource_text
    assert configuration.stage.aws_account_id in parameter_resource_text
    assert ":parameter/" in parameter_resource_text
    assert "parameter//" not in parameter_resource_text
    assert configuration.secrets.rcon_password_parameter_name("dev") in parameter_resource_text
    assert "rcon-password" in parameter_resource_text
    assert not any(
        "ssm:GetParameter" in _action_list(statement["Action"]) and statement["Resource"] == "*"
        for statement in statements
    )

    template_text = str(template.to_json())
    assert "AmazonSSMManagedInstanceCore" not in template_text
    assert "rcon-password" in template_text
    assert "RCON_PASSWORD" not in template_text


def test_phase_one_minecraft_instance_uses_existing_network_role_and_root_ebs() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    instances = template.find_resources("AWS::EC2::Instance")
    assert len(instances) == 1
    instance_id, instance_resource = next(iter(instances.items()))
    instance = instance_resource["Properties"]
    template.has_output("MinecraftInstanceId", {"Value": {"Ref": instance_id}})
    assert instance["InstanceType"] == configuration.stage.instance_type
    assert "ami-" not in str(instance["ImageId"])
    image_parameter_id = instance["ImageId"]["Ref"]
    image_parameter = template.to_json()["Parameters"][image_parameter_id]
    assert image_parameter["Default"] == (
        "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    )
    network_interface = instance["NetworkInterfaces"][0]
    assert network_interface["SubnetId"] in [
        {"Ref": subnet_id} for subnet_id in template.find_resources("AWS::EC2::Subnet")
    ]
    assert network_interface["AssociatePublicIpAddress"] is True
    assert "KeyName" not in instance
    assert "UserData" in instance
    assert instance["InstanceInitiatedShutdownBehavior"] == "stop"
    assert instance["Monitoring"] is False
    assert instance["MetadataOptions"] == {
        "HttpTokens": "required",
        "InstanceMetadataTags": "disabled",
    }

    security_groups = template.find_resources("AWS::EC2::SecurityGroup")
    minecraft_security_group_id = next(
        logical_id
        for logical_id, group in security_groups.items()
        if group["Properties"]["GroupDescription"] == "Minecraft client ingress only"
    )
    assert network_interface["GroupSet"] == [
        {"Fn::GetAtt": [minecraft_security_group_id, "GroupId"]}
    ]
    assert template.find_resources("AWS::EC2::EIP") == {}

    instance_profiles = template.find_resources("AWS::IAM::InstanceProfile")
    assert len(instance_profiles) == 1
    profile_id, profile = next(iter(instance_profiles.items()))
    role_id = next(
        logical_id
        for logical_id, role in template.find_resources("AWS::IAM::Role").items()
        if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
    )
    assert profile["Properties"]["Roles"] == [{"Ref": role_id}]
    assert instance["IamInstanceProfile"] == {"Ref": profile_id}
    assert len(template.find_resources("AWS::IAM::Role")) == 1
    assert (
        "ManagedPolicyArns"
        not in next(
            role
            for role in template.find_resources("AWS::IAM::Role").values()
            if role["Properties"]["Description"] == "Minecraft EC2 managed node role"
        )["Properties"]
    )

    root_volume = instance["BlockDeviceMappings"]
    assert len(root_volume) == 1
    assert root_volume[0]["DeviceName"] == "/dev/xvda"
    root_ebs = root_volume[0]["Ebs"]
    assert root_ebs == {
        "DeleteOnTermination": True,
        "Encrypted": configuration.stage.root_volume_encrypted,
        "VolumeSize": configuration.stage.root_volume_size_gib,
        "VolumeType": configuration.stage.root_volume_type,
    }
    assert "/wishicraft/dev/secret/rcon-password" in str(instance)
    assert "{{resolve:ssm-secure:" not in str(instance)


def test_phase_one_minecraft_data_volume_is_retained_and_attached_to_the_instance() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    volumes = template.find_resources("AWS::EC2::Volume")
    assert len(volumes) == 1
    volume_id, volume = next(iter(volumes.items()))
    volume_properties = volume["Properties"]
    assert volume_properties["AvailabilityZone"] == configuration.stage.availability_zone
    assert volume_properties["Encrypted"] is configuration.stage.data_volume_encrypted
    assert volume_properties["Size"] == configuration.stage.data_volume_size_gib
    assert volume_properties["VolumeType"] == configuration.stage.data_volume_type
    assert volume["DeletionPolicy"] == "Retain"
    assert volume["UpdateReplacePolicy"] == "Retain"
    assert not {
        "Iops",
        "KmsKeyId",
        "MultiAttachEnabled",
        "SnapshotId",
        "Throughput",
    } & set(volume_properties)

    instance = next(iter(template.find_resources("AWS::EC2::Instance").items()))
    instance_id, instance_definition = instance
    instance_properties = instance_definition["Properties"]
    subnet = next(iter(template.find_resources("AWS::EC2::Subnet").values()))["Properties"]
    assert volume_properties["AvailabilityZone"] == subnet["AvailabilityZone"]
    assert volume_properties["AvailabilityZone"] == instance_properties["AvailabilityZone"]
    assert len(instance_properties["BlockDeviceMappings"]) == 1
    assert instance_properties["BlockDeviceMappings"][0]["DeviceName"] == "/dev/xvda"

    attachments = template.find_resources("AWS::EC2::VolumeAttachment")
    assert len(attachments) == 1
    attachment = next(iter(attachments.values()))
    assert attachment["Properties"] == {
        "Device": "/dev/sdf",
        "InstanceId": {"Ref": instance_id},
        "VolumeId": {"Ref": volume_id},
    }
    assert "DeletionPolicy" not in attachment
    assert "UpdateReplacePolicy" not in attachment
    assert len(template.find_resources("AWS::IAM::Role")) == 1
    assert len(template.find_resources("AWS::EC2::SecurityGroup")) == 1
    assert template.find_resources("AWS::KMS::Key") == {}


def test_phase_one_data_volume_bootstrap_uses_volume_ref_and_preserves_ec2_invariants() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")

    volume_id = next(iter(template.find_resources("AWS::EC2::Volume")))
    instance = next(iter(template.find_resources("AWS::EC2::Instance").values()))["Properties"]
    user_data = instance["UserData"]
    user_data_matches = _find_key(template.to_json(), "UserData")
    assert len(user_data_matches) == 1, user_data_matches
    user_data_path, synthesized_user_data = user_data_matches[0]
    assert user_data_path.endswith(".Properties.UserData")
    assert synthesized_user_data == user_data
    assert {"Fn::Base64"} == set(user_data)
    user_data_text = _resolve_user_data(
        user_data["Fn::Base64"],
        {volume_id: "vol-00000000000000000"},
    )
    assert any(reference == volume_id for _, reference in _find_key(user_data["Fn::Base64"], "Ref"))
    assert configuration.stage.data_volume_mount_path in user_data_text
    assert configuration.stage.data_volume_filesystem_type in user_data_text
    assert "wishicraft-data-volume.service" in user_data_text
    assert "DATA_VOLUME_ID=" in user_data_text
    assert configuration.stage.java_runtime in user_data_text
    assert "base64 -d" in user_data_text
    assert "| gzip -d > /usr/local/sbin/wishicraft-bootstrap-runner" in user_data_text
    encoded_runner = user_data_text.split("printf '%s' '", 1)[1].split("' | base64 -d", 1)[0]
    runner = gzip.decompress(base64.b64decode(encoded_runner)).decode("utf-8")
    assert runner == (REPOSITORY_ROOT / "infrastructure/bootstrap/bootstrap_runner.sh").read_text(
        encoding="utf-8"
    )
    assert "sha256sum -c -" in runner
    assert "data_volume_mount.sh" in user_data_text
    assert "java_runtime_install.sh" in user_data_text
    assert "minecraft_artifact_install.sh" in user_data_text
    assert "minecraft_game_setup.sh" in user_data_text
    assert "minecraft_rcon_configure.sh" in user_data_text
    assert "minecraft_rcon_firewall.sh" in user_data_text
    assert "WISHICRAFT_DATA_VOLUME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_JAVA_RUNTIME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_ARTIFACT_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_GAME_SCRIPT" not in user_data_text
    assert "WISHICRAFT_MINECRAFT_RCON_SCRIPT" not in user_data_text
    assert "minecraft.service" in user_data_text
    minecraft_environment_start = user_data_text.index("cat > /etc/wishicraft/minecraft.env ")
    minecraft_environment_end = user_data_text.index(
        "WISHICRAFT_MINECRAFT_ENV\n", minecraft_environment_start
    )
    minecraft_environment = user_data_text[minecraft_environment_start:minecraft_environment_end]
    assert "DATA_VOLUME_ID=vol-00000000000000000" in minecraft_environment
    assert (
        f"FILESYSTEM_TYPE={configuration.stage.data_volume_filesystem_type}"
        in minecraft_environment
    )
    prepare_call = "/usr/local/lib/wishicraft/minecraft_game_setup.sh --prepare"
    exported_minecraft_environment = "set -a\n. /etc/wishicraft/minecraft.env\nset +a\n"
    service_enable = "systemctl enable --now wishicraft-data-volume.service"
    assert exported_minecraft_environment + prepare_call in user_data_text
    assert user_data_text.index(service_enable) < user_data_text.index("JAVA_RUNTIME=")
    assert user_data_text.index("JAVA_RUNTIME=") < user_data_text.index(prepare_call)
    assert user_data_text.index("JAVA_RUNTIME=") < user_data_text.rindex(
        "minecraft_artifact_install.sh"
    )
    assert user_data_text.index("minecraft_rcon_configure.sh\n") < user_data_text.index(
        "wishicraft-rcon-firewall.service"
    )
    assert user_data_text.index("wishicraft-rcon-firewall.service") < user_data_text.rindex(
        "systemctl enable --now minecraft.service"
    )
    assert "/dev/sdf" not in user_data_text
    assert configuration.secrets.rcon_password_parameter_name("dev") in user_data_text
    assert "{{resolve:ssm-secure:" not in user_data_text
    assert len(user_data_text.encode("utf-8")) <= 16 * 1024

    assert instance["InstanceInitiatedShutdownBehavior"] == "stop"
    assert instance["MetadataOptions"] == {
        "HttpTokens": "required",
        "InstanceMetadataTags": "disabled",
    }
    assert len(instance["BlockDeviceMappings"]) == 1
    assert template.find_resources("AWS::IAM::Role")
    assert template.find_resources("AWS::IAM::ManagedPolicy") == {}
    assert template.find_resources("AWS::KMS::Key") == {}
    assert len(template.find_resources("AWS::EC2::SecurityGroup")) == 1


def test_phase_one_minecraft_service_uses_mount_guard_and_fixed_runtime_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1)
    stack = cast(Stack, app.node.find_child("MinecraftStack-dev"))
    template = Template.from_stack(stack)
    configuration = load_configuration(REPOSITORY_ROOT, "dev")
    instance = next(iter(template.find_resources("AWS::EC2::Instance").values()))["Properties"]
    user_data = _resolve_user_data(
        instance["UserData"]["Fn::Base64"],
        {next(iter(template.find_resources("AWS::EC2::Volume"))): ("vol-00000000000000000")},
    )

    assert "Requires=wishicraft-data-volume.service" in user_data
    assert "After=wishicraft-data-volume.service" in user_data
    assert "Requires=wishicraft-rcon-firewall.service" in user_data
    assert "After=wishicraft-data-volume.service wishicraft-rcon-firewall.service" in user_data
    assert "Before=minecraft.service" in user_data
    assert "ExecStartPre=+/usr/local/lib/wishicraft/data_volume_mount.sh --verify" in user_data
    assert "ExecStartPre=+/usr/local/lib/wishicraft/minecraft_game_setup.sh --verify" in user_data
    assert f"-Xms{configuration.stage.java_xms} -Xmx{configuration.stage.java_xmx}" in user_data
    assert " -jar /srv/minecraft/packages/vanilla/26.2/server.jar nogui" in user_data
    assert "User=minecraft" in user_data
    assert "TimeoutStopSec=180" in user_data


def test_phase_one_dev_deploy_validation_uses_confirmed_settings() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", phase=1, action="deploy")

    assert app.node.find_child("MinecraftStack-dev")


def test_prod_stack_is_rejected_before_synthesis() -> None:
    with pytest.raises(ConfigValidationError, match="aws.account_id"):
        build_app(REPOSITORY_ROOT, "prod")


def test_target_stack_owns_only_the_imported_existing_data_attachment() -> None:
    app = build_app(REPOSITORY_ROOT, "dev", deployment="target")
    assert app.node.try_find_child("MinecraftStack-dev") is None
    stack = cast(Stack, app.node.find_child("MinecraftTargetStack-dev"))
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::EC2::Instance", 1)
    template.resource_count_is("AWS::EC2::SecurityGroup", 1)
    template.resource_count_is("AWS::IAM::Role", 1)
    template.resource_count_is("AWS::IAM::InstanceProfile", 1)
    assert template.find_resources("AWS::EC2::Volume") == {}
    attachments = template.find_resources("AWS::EC2::VolumeAttachment")
    assert list(attachments) == ["TargetDataVolumeAttachment"]
    assert template.find_resources("AWS::Route53::RecordSet") == {}

    instance = next(iter(template.find_resources("AWS::EC2::Instance").values()))["Properties"]
    assert instance["ImageId"] == "ami-0b4d2909a55ed2c78"
    assert instance["InstanceType"] == "t3a.medium"
    assert "UserData" not in instance
    assert instance["NetworkInterfaces"][0]["SubnetId"] == "subnet-0a70e5682ea8d0bd3"
    assert instance["NetworkInterfaces"][0]["AssociatePublicIpAddress"] is True
    assert instance["BlockDeviceMappings"] == [
        {
            "DeviceName": "/dev/xvda",
            "Ebs": {
                "DeleteOnTermination": True,
                "Encrypted": True,
                "VolumeSize": 16,
                "VolumeType": "gp3",
            },
        }
    ]
    instance_id = next(iter(template.find_resources("AWS::EC2::Instance")))
    attachment = attachments["TargetDataVolumeAttachment"]
    assert attachment["Properties"] == {
        "Device": "/dev/sdf",
        "InstanceId": {"Ref": instance_id},
        "VolumeId": "vol-03ac9f534326c345c",
    }
    assert attachment["DeletionPolicy"] == "Retain"
    assert attachment["UpdateReplacePolicy"] == "Retain"
    assert template.to_json()["Resources"]["CDKMetadata"]["Properties"]["Analytics"] == (
        "v2:deflate64:H4sIAAAAAAAA/03KQQrCMBBA0bN0n4w0FS/QhbiytAeQGBMcm05KMqGUk"
        "LuLiODq8eErUCcFbaO3JM1jlh7vUCbWZhZ6S7eCeoEyBm9F7+jnhRJrMnaIwaG3V"
        "VijoPSOJmtyRN7PMeT1/6z1U9fMa+Yqhp2fgQ4dtAqOzSshypiJcbEwfn0D8wPMUp"
        "cAAAA="
    )

    security_group = next(iter(template.find_resources("AWS::EC2::SecurityGroup").values()))[
        "Properties"
    ]
    # This imported value is replacement-only in CloudFormation. Its wording is
    # historical; the ingress assertions below define the effective baseline.
    assert security_group["GroupDescription"] == "Phase 2 target host with zero ingress"
    assert security_group["SecurityGroupIngress"] == [
        {
            "CidrIp": "0.0.0.0/0",
            "Description": "Minecraft client connections",
            "FromPort": 25565,
            "IpProtocol": "tcp",
            "ToPort": 25565,
        }
    ]
    assert security_group["VpcId"] == "vpc-0c3cca1e65696ed8e"
    assert security_group["SecurityGroupEgress"] == [
        {
            "CidrIp": "0.0.0.0/0",
            "Description": "HTTPS for SSM, AL2023 repositories, GitHub, and GHCR",
            "FromPort": 443,
            "IpProtocol": "tcp",
            "ToPort": 443,
        }
    ]

    role = next(iter(template.find_resources("AWS::IAM::Role").values()))["Properties"]
    assert role["ManagedPolicyArns"] == [
        {
            "Fn::Join": [
                "",
                [
                    "arn:",
                    {"Ref": "AWS::Partition"},
                    ":iam::aws:policy/AmazonSSMManagedInstanceCore",
                ],
            ]
        }
    ]
    template_text = str(template.to_json())
    for forbidden in (
        "/srv/minecraft",
        "route53:",
        "ec2:AttachVolume",
    ):
        assert forbidden not in template_text
    assert "ssm:GetParameter" in template_text
    assert "/wishicraft/dev/secret/rcon-password" in template_text
    assert "i-021eaa7f33ddaf0a6" not in template_text
