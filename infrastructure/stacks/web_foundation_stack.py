"""Proposed isolated Web resources. Existing Control Plane tables are read-only imports."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from aws_cdk import CfnOutput, Duration, Environment, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from web.foundation import build_foundation
from wishicraft.config import ProjectConfig, SecretsExampleConfig, StageConfig
from wishicraft.naming import resource_name


def bundle(root: Path) -> Path:
    output = Path(tempfile.mkdtemp(prefix="wishicraft-web-bundle-"))
    shutil.copytree(
        root / "src/wishicraft",
        output / "wishicraft",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    build_foundation(root, output / "site")
    return output


class WebFoundationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        *,
        project: ProjectConfig,
        stage: StageConfig,
        secrets: SecretsExampleConfig,
        root: Path,
    ) -> None:
        super().__init__(
            scope,
            f"WishicraftWebStack-{stage.stage}",
            env=Environment(account=stage.aws_account_id, region=stage.aws_region),
            description="Proposed Wishicraft public guide and authenticated read-only status",
            analytics_reporting=False,
        )
        api = apigw.HttpApi(self, "WebApi", create_default_stage=True)
        assert api.default_stage is not None
        cfn_stage = api.default_stage.node.default_child
        assert isinstance(cfn_stage, apigw.CfnStage)
        cfn_stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=10, throttling_rate_limit=5
        )
        sessions = dynamodb.Table(
            self,
            "WebSessions",
            partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )
        future: Any = secrets.values["future_secure_parameters"]
        signing = str(future["web_session_signing_key"][f"{stage.stage}_parameter_name"])
        oauth = str(future["discord_oauth_client_secret"][f"{stage.stage}_parameter_name"])
        common = {
            "WEB_SESSIONS_TABLE": sessions.table_name,
            "WEB_SIGNING_PARAMETER": signing,
            **{
                "WEB_" + key.upper(): stage.discord_public_id(key.removeprefix("discord_"))
                for key in ("application_id", "guild_id", "player_role_id", "admin_role_id")
            },
        }
        code = lambda_.Code.from_asset(str(bundle(root)))

        def function(name: str, handler: str, environment: dict[str, str]) -> lambda_.Function:
            group = logs.LogGroup(
                self,
                name + "Logs",
                retention=logs.RetentionDays.TWO_WEEKS,
                removal_policy=RemovalPolicy.RETAIN,
            )
            fn = lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler="wishicraft.web_lambda." + handler,
                code=code,
                timeout=Duration.seconds(29),
                memory_size=256,
                environment=environment,
                log_group=group,
            )
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[
                        self.format_arn(
                            service="ssm", resource="parameter", resource_name=signing.lstrip("/")
                        )
                    ],
                )
            )
            cloudwatch.Alarm(
                self,
                name + "Errors",
                metric=fn.metric_errors(),
                threshold=1,
                evaluation_periods=1,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            return fn

        env = {
            **common,
            "WEB_SYSTEM_ID": project.system_id,
            "WEB_OBSERVATION_SECONDS": str(
                stage.monitoring_int("observation_freshness_warning_minutes") * 60
            ),
        }
        names = {
            "system": "system-state",
            "heartbeat": "runtime-heartbeats",
            "games": "games",
            "operation": "operations",
        }
        for key, suffix in names.items():
            env["WEB_" + key.upper() + "_TABLE"] = resource_name(
                project.resource_prefix, stage.stage, suffix
            )
        web = function("Web", "handler", env)
        auth = function(
            "Auth",
            "auth_handler",
            {**common, "WEB_OAUTH_PARAMETER": oauth, "WEB_ORIGIN": api.api_endpoint},
        )
        auth.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm", resource="parameter", resource_name=oauth.lstrip("/")
                    )
                ],
            )
        )
        for fn, actions in (
            (web, ["dynamodb:GetItem"]),
            (auth, ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]),
        ):
            fn.add_to_role_policy(
                iam.PolicyStatement(actions=actions, resources=[sessions.table_arn])
            )
        for key in names:
            conditions = (
                {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": [project.system_id]}}
                if key in {"system", "heartbeat"}
                else None
            )
            web.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["dynamodb:GetItem"],
                    resources=[
                        self.format_arn(
                            service="dynamodb",
                            resource="table",
                            resource_name=env["WEB_" + key.upper() + "_TABLE"],
                        )
                    ],
                    conditions=conditions,
                )
            )
        api.add_routes(
            path="/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=integrations.HttpLambdaIntegration("WebIntegration", web),
        )
        api.add_routes(
            path="/",
            methods=[apigw.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("RootIntegration", web),
        )
        api.add_routes(
            path="/auth/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=integrations.HttpLambdaIntegration("AuthIntegration", auth),
        )
        CfnOutput(self, "WebOrigin", value=api.api_endpoint)
        CfnOutput(self, "OAuthRedirectUri", value=api.api_endpoint + "/auth/callback")
