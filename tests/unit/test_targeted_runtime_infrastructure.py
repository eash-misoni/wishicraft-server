"""CDK environment -> real Lambda initialization -> SSM renderer boundary."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from wishicraft import start_workflow_lambda, stop_workflow_lambda
from wishicraft.runtime_contract import RuntimeTargetRepository

ROOT = Path(__file__).resolve().parents[2]


def test_cdk_environment_initializes_both_real_handlers_and_renders_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="control-plane")
    template = Template.from_stack(
        cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    ).to_json()

    class Api:
        def __init__(self) -> None:
            self.target: dict[str, Any] = {}
            self.sent: list[dict[str, Any]] = []

        def get_item(self, **kwargs: Any) -> dict[str, Any]:
            if "lock_name" in kwargs["Key"]:
                return {
                    "Item": {
                        k: {"S": v}
                        for k, v in {
                            "resource_id": "wishicraft-main",
                            "owner_operation_id": "op-current",
                            "lease_id": "lease-current",
                        }.items()
                    }
                    | {"lease_expires_at": {"N": "4070908800"}}
                }
            return {
                "Item": {"runtime_target": {"M": {k: {"S": v} for k, v in self.target.items()}}}
            }

        def update_item(self, **kwargs: Any) -> dict[str, Any]:
            return {}

        def describe_instances(self, **kwargs: Any) -> dict[str, Any]:
            return {"Reservations": [{"Instances": [{"InstanceId": "i-0123456789abcdef0"}]}]}

        def send_command(self, **kwargs: Any) -> dict[str, Any]:
            self.sent.append(kwargs)
            return {"Command": {"CommandId": "command-test"}}

    for module, action in [(start_workflow_lambda, "start"), (stop_workflow_lambda, "stop")]:
        handler_name = "wishicraft." + action + "_workflow_lambda.handler"
        function = next(
            v
            for v in template["Resources"].values()
            if v["Type"] == "AWS::Lambda::Function" and v["Properties"]["Handler"] == handler_name
        )
        env = function["Properties"]["Environment"]["Variables"]
        for key, value in env.items():
            monkeypatch.setenv(key, value if isinstance(value, str) else "table-" + key.lower())
        monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
        api = Api()
        monkeypatch.setitem(
            sys.modules, "boto3", SimpleNamespace(client=lambda *args, api=api, **kwargs: api)
        )
        runtime = module.Runtime()
        assert isinstance(runtime.targets, RuntimeTargetRepository)
        api.target = {
            "instance_id": "i-0123456789abcdef0",
            "game_id": runtime.game_id,
            "data_source": runtime.data_source,
            "config_digest": runtime.config_digest,
            "run_id": "op-launch",
        }
        monkeypatch.setattr(module, "_runtime", runtime)
        assert module.handler(
            {
                "schema_version": 1,
                "action": "run_host_" + action,
                "operation_id": "op-current",
                "lease_id": "lease-current",
            },
            None,
        ) == {"command_id": "command-test"}
        command = api.sent[0]["Parameters"]["commands"][0]
        payload = json.loads(base64.b64decode(command.split()[-1]))
        assert payload == {
            "schema_version": 2,
            "operation_id": "op-current",
            "lease_id": "lease-current",
            "action": action.upper(),
        }
        assert api.sent[0]["InstanceIds"] == [api.target["instance_id"]]
