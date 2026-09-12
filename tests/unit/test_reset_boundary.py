"""Synthesized environment -> real handler -> serialized Operation/Game -> host authorization."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from aws_cdk import App, Stack
from aws_cdk.assertions import Template
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer  # type: ignore[import-untyped]

from infrastructure.stacks.control_plane_stack import ControlPlaneStack
from wishicraft import start_workflow_lambda, stop_workflow_lambda
from wishicraft.artifacts.targeted_runtime import authorize
from wishicraft.config import load_configuration
from wishicraft.reset_migration import prepare as bundle
from wishicraft.runtime_contract import command
from wishicraft.world_reference import data_source

ROOT = Path(__file__).resolve().parents[2]
GAMES = ["game-vanilla-main", "game-vanilla-secondary"]
POLICY = {"fixed_seed": 0, "retain_previous": 3, "minimum_free_bytes": 4 * 1024**3}
NOW = datetime(2026, 9, 12, tzinfo=UTC)


def encoded(value: dict[str, Any]) -> dict[str, Any]:
    serializer = TypeSerializer()
    return {k: serializer.serialize(v) for k, v in value.items()}


@pytest.fixture(scope="module")
def resources() -> dict[str, Any]:
    cfg = load_configuration(ROOT, "dev")
    app = App()
    ControlPlaneStack(
        app,
        stage=cfg.stage,
        project=cfg.project,
        secrets=cfg.secrets,
        phase=8,
        games=tuple(GAMES),
        reset_policies={GAMES[1]: POLICY},
    )
    return dict(
        Template.from_stack(
            cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
        ).to_json()["Resources"]
    )


class Dynamo:
    def __init__(self, digest: str) -> None:
        self.game: dict[str, Any] = {
            "game_id": GAMES[1],
            "lifecycle_state": "ACTIVE",
            "materialization_state": "MATERIALIZED",
            "world": {},
        }
        self.op: dict[str, Any] = {
            "operation_id": "op-reset-one",
            "target_game_id": GAMES[1],
            "operation_type": "RESET",
            "lease_id": "lease-one",
            "status": "RUNNING",
            "timeout_at": "2099-01-01T00:00:00Z",
            "reset_seed_mode": "new",
        }
        self.lease = {
            "owner_operation_id": "op-reset-one",
            "lease_id": "lease-one",
            "resource_id": "wishicraft-main",
            "lease_expires_at": 4070908800,
        }
        self.source = {
            "instance_id": "i-0123456789abcdef0",
            "game_id": GAMES[1],
            "data_source": data_source(GAMES[1]),
            "config_digest": digest,
            "run_id": "op-original",
        }
        self.calls: list[dict[str, Any]] = []

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ConsistentRead"]
        key = next(iter(kwargs["Key"]))
        return {
            "Item": encoded(
                {"operation_id": self.op, "game_id": self.game, "lock_name": self.lease}[key]
            )
        }

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        values = {
            k: TypeDeserializer().deserialize(v)
            for k, v in kwargs["ExpressionAttributeValues"].items()
        }
        if ":plan" in values:
            assert "attribute_not_exists(reset_plan)" in kwargs["ConditionExpression"]
            self.op.update(
                reset_plan=values[":plan"],
                runtime_target=values[":target"],
                switch_source=values[":source"],
            )
        return {}

    def describe_instances(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "Reservations": [
                {
                    "Instances": [
                        {"InstanceId": self.source["instance_id"], "State": {"Name": "running"}}
                    ]
                }
            ]
        }


def setup_runtime(monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any]) -> Dynamo:
    properties = next(
        r["Properties"]
        for r in resources.values()
        if r["Type"] == "AWS::Lambda::Function"
        and r["Properties"]["FunctionName"] == "wc-dev-stop-task"
    )
    for key, value in properties["Environment"]["Variables"].items():
        monkeypatch.setenv(
            key,
            resources[value["Ref"]]["Properties"]["TableName"]
            if isinstance(value, dict)
            else value,
        )
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    # This capability comes from the candidate synthesized configuration, not an env override.
    assert json.loads(properties["Environment"]["Variables"]["RESET_POLICIES"]) == {
        GAMES[1]: POLICY
    }
    api = Dynamo(properties["Environment"]["Variables"]["RUNTIME_CONFIG_DIGEST"])
    import boto3  # type: ignore[import-untyped]

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: api)
    monkeypatch.setattr(stop_workflow_lambda, "_runtime", None)
    monkeypatch.setattr(start_workflow_lambda, "_runtime", None)
    return api


def state(api: Dynamo) -> dict[str, Any]:
    return {
        "game_id": GAMES[1],
        "desired_state": "RUNNING",
        "health": "HEALTHY",
        "observation_errors": [],
        "discrepancies": [],
        "observation": {
            "ec2_state": "running",
            "runtime_ready": True,
            "player_count": 0,
            "execution": {"phase": "running", "target": api.source},
        },
    }


def invoke(api: Dynamo, value: dict[str, Any] | None = None) -> dict[str, object]:
    return stop_workflow_lambda.handler(
        {
            "schema_version": 1,
            "action": "prepare_reset",
            "operation_id": "op-reset-one",
            "lease_id": "lease-one",
            "state": state(api) if value is None else value,
        },
        None,
    )


def test_handler_freezes_and_host_authorizes_same_game_new_world(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any]
) -> None:
    api = setup_runtime(monkeypatch, resources)
    assert invoke(api) == {"prepared": True}
    frozen = deepcopy(api.op)
    assert invoke(api, {"unusable_later_observation": True}) == {"prepared": True}
    assert api.op == frozen and len(api.calls) == 1
    target = api.op["runtime_target"]
    assert target["data_source"] == data_source(GAMES[1], "op-reset-one")
    cfg = {
        "instance_id": target["instance_id"],
        "config_digest": target["config_digest"],
        "system_id": "wishicraft-main",
        "games": GAMES,
        "reset_policies": {GAMES[1]: POLICY},
    }
    for action, expected in [
        ("STOP", api.source),
        ("START", target),
        ("RESET_PREPARE", target),
        ("RESET_CLEANUP", target),
    ]:
        payload = json.loads(
            base64.b64decode(
                command(operation_id="op-reset-one", lease_id="lease-one", action=action).split()[
                    -1
                ]
            )
        )
        assert authorize(payload, api.op, api.lease, cfg, NOW) == expected
    api.lease["owner_operation_id"] = "op-other"
    with pytest.raises(ValueError, match="STALE_OPERATION"):
        authorize(payload, api.op, api.lease, cfg, NOW)


@pytest.mark.parametrize(
    "field,value", [("game_id", GAMES[0]), ("health", "UNKNOWN"), ("desired_state", "STOPPED")]
)
def test_other_game_stopped_unknown_are_rejected_before_freeze(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any], field: str, value: str
) -> None:
    api = setup_runtime(monkeypatch, resources)
    observed = state(api)
    observed[field] = value
    with pytest.raises(ValueError):
        invoke(api, observed)
    assert api.calls == [] and "reset_plan" not in api.op


@pytest.mark.parametrize("count", [1, None, False])
def test_players_positive_unknown_boolean_are_rejected(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any], count: object
) -> None:
    api = setup_runtime(monkeypatch, resources)
    observed = state(api)
    observed["observation"]["player_count"] = count
    with pytest.raises(ValueError):
        invoke(api, observed)
    assert api.calls == []


def test_graph_has_no_host_shutdown_and_one_completion_after_cleanup(
    resources: dict[str, Any],
) -> None:
    graph = next(
        r["Properties"]["Definition"]
        for r in resources.values()
        if r["Type"] == "AWS::StepFunctions::StateMachine"
        and r["Properties"]["StateMachineName"] == "wc-dev-reset"
    )
    actions = [
        s["Parameters"]["Payload"].get("action")
        for s in graph["States"].values()
        if s.get("Type") == "Task"
    ]
    assert (
        "start_ec2" not in actions and "stop_ec2" not in actions and actions.count("complete") == 1
    )
    assert all(
        a in actions
        for a in [
            "prepare_reset",
            "run_host_stop",
            "run_reset_prepare",
            "commit_reset",
            "run_host_start",
            "run_reset_cleanup",
        ]
    )
    assert graph["States"]["ResetCleanupDone"]["Choices"][0]["Next"] == "StartMarkSucceeded"

    def edges(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [
                n for k, v in value.items() for n in ([v] if k in {"Next", "Default"} else edges(v))
            ]
        if isinstance(value, list):
            return [n for item in value for n in edges(item)]
        return []

    reached: set[str] = set()
    pending = [graph["StartAt"]]
    while pending:
        name = pending.pop()
        assert name in graph["States"]
        if name not in reached:
            reached.add(name)
            pending.extend(edges(graph["States"][name]))
    assert set(graph["States"]) == reached
    assert "ec2:DeleteSnapshot" not in json.dumps(resources)
    assert "RESET_POLICIES" in json.dumps(resources)


def test_bundle_uses_deployed_predecessors_and_has_no_world_mutation(tmp_path: Path) -> None:
    result = bundle(ROOT, tmp_path / "bundle", "{}")
    assert result["baseline"] == "1267ed5912e027ca2e0b1e1a419df62865f6bfcd"
    entries = result["plan"]["files"]
    assert len(entries) == 7
    assert all(not entry["destination"].startswith("/srv/") for entry in entries)
    assert (
        next(e for e in entries if e["destination"].endswith("operation-v2"))["predecessor"]
        == "84c257855962ca5a5a46547f21362d07062d5e3ccabc320256066c1af54a6729"
    )


@pytest.mark.parametrize("reply_lost", [False, True])
def test_world_selection_cas_and_exact_readback(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any], reply_lost: bool
) -> None:
    from wishicraft.operation import LeaseProof
    from wishicraft.reset_contract import commit_selection

    api = setup_runtime(monkeypatch, resources)
    invoke(api)
    runtime = stop_workflow_lambda._runtime
    assert runtime is not None
    calls = []

    def transaction(**kwargs: Any) -> None:
        items = kwargs["TransactItems"]
        assert len(items) == 3
        assert "lease_expires_at" in items[0]["ConditionCheck"]["ConditionExpression"]
        assert "reset_plan" in items[1]["ConditionCheck"]["ConditionExpression"]
        assert (
            items[2]["Update"]["ConditionExpression"] == "attribute_not_exists(#world.current_id)"
        )
        calls.append(items)
        api.game["world"] = {"current_id": api.op["operation_id"]}
        if reply_lost:
            raise TimeoutError("synthetic committed response loss")

    monkeypatch.setattr(api, "transact_write_items", transaction, raising=False)
    proof = LeaseProof("wishicraft-main", api.op["operation_id"], api.op["lease_id"], 0)
    commit_selection(runtime, proof, NOW)
    commit_selection(runtime, proof, NOW)
    assert len(calls) == 1
    api.game["world"] = {"current_id": "op-other"}
    with pytest.raises(ValueError, match="current world changed"):
        commit_selection(runtime, proof, NOW)


def test_fresh_start_and_stopped_receipt_after_selected_world_commit(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any]
) -> None:
    from types import SimpleNamespace

    from wishicraft.runtime_contract import select_target

    api = setup_runtime(monkeypatch, resources)
    invoke(api)
    runtime = stop_workflow_lambda._runtime
    assert runtime is not None
    api.op.pop("runtime_target")
    api.op.pop("switch_source")
    api.op["operation_type"] = "STOP"
    runtime.game_id = GAMES[1]
    runtime.data_source = data_source(GAMES[1], "op-newworld")
    runtime.targets.field = "runtime_target"

    def freeze(**kwargs: Any) -> dict[str, str]:
        return dict(kwargs["target"])

    monkeypatch.setattr(runtime.targets, "freeze", freeze)
    proof = SimpleNamespace(owner_operation_id="op-newrequest", lease_id="lease-one")
    obs: dict[str, Any] = {
        "observation": {
            "ec2_state": "running",
            "host_runtime_state": "not-running",
            "execution": {"phase": "stopped", "target": api.source},
        }
    }
    assert select_target(runtime, proof, obs, action="STOP") == api.source
    started = select_target(runtime, proof, obs, action="START")
    assert started is not None and started["data_source"] == runtime.data_source
    assert started["run_id"] == "op-newrequest"
    obs["observation"]["execution"]["phase"] = "running"
    with pytest.raises(ValueError, match="selected target mismatch"):
        select_target(runtime, proof, obs, action="STOP")


@pytest.mark.parametrize(
    "status,code,error",
    [
        ("Failed", 1, "ResetPreparationFailed"),
        ("TimedOut", -1, "RuntimeError"),
        ("Cancelled", -1, "RuntimeError"),
    ],
)
def test_preparation_exit_is_distinct_from_unknown_command(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any], status: str, code: int, error: str
) -> None:
    api = setup_runtime(monkeypatch, resources)
    invoke(api)
    api.op["reset_prepare_command"] = "command-one"
    monkeypatch.setattr(
        api,
        "get_command_invocation",
        lambda **kwargs: {"Status": status, "ResponseCode": code},
        raising=False,
    )
    with pytest.raises(RuntimeError) as failure:
        stop_workflow_lambda.handler(
            {
                "schema_version": 1,
                "action": "check_reset_prepare",
                "operation_id": api.op["operation_id"],
                "lease_id": api.op["lease_id"],
                "command_id": "command-one",
            },
            None,
        )
    assert type(failure.value).__name__ == error
    assert api.game["world"] == {}
    graph = next(
        r["Properties"]["Definition"]
        for r in resources.values()
        if r["Type"] == "AWS::StepFunctions::StateMachine"
        and r["Properties"]["StateMachineName"] == "wc-dev-reset"
    )
    catch = graph["States"]["ResetPrepareCheck"]["Catch"]
    assert catch == [
        {
            "ErrorEquals": ["ResetPreparationFailed"],
            "ResultPath": "$.workflow_error",
            "Next": "StopSetHostFailure",
        }
    ]


def test_cleanup_exited_failure_preserves_ready_runtime_and_reports_pending(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any]
) -> None:
    api = setup_runtime(monkeypatch, resources)
    invoke(api)
    api.op["reset_cleanup_command"] = "command-one"
    monkeypatch.setattr(
        api,
        "get_command_invocation",
        lambda **kwargs: {"Status": "Failed", "ResponseCode": 1},
        raising=False,
    )
    result = stop_workflow_lambda.handler(
        {
            "schema_version": 1,
            "action": "check_reset_cleanup",
            "operation_id": api.op["operation_id"],
            "lease_id": api.op["lease_id"],
            "command_id": "command-one",
        },
        None,
    )
    assert result == {"complete": True}
    assert any(c["ExpressionAttributeValues"].get(":pending") == {"BOOL": True} for c in api.calls)


@pytest.mark.parametrize("owned", [True, False])
def test_operator_resume_requires_same_execution_and_live_ownership(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, Any], owned: bool
) -> None:
    from types import SimpleNamespace

    from wishicraft.reset_operator import observe

    api = setup_runtime(monkeypatch, resources)
    invoke(api)
    arn = "arn:aws:states:ap-northeast-1:123456789012:execution:wc-dev-reset:op-reset-one"
    api.op["workflow_execution_arn"] = arn
    if not owned:
        api.lease["lease_expires_at"] = 0
    execution = {
        "executionArn": arn,
        "name": "op-reset-one",
        "status": "FAILED",
        "redriveStatus": "REDRIVABLE",
    }
    sfn = SimpleNamespace(describe_execution=lambda **kwargs: execution)
    args: dict[str, Any] = dict(
        operation_id="op-reset-one",
        system_id="wishicraft-main",
        lock_name="synthetic-lock",
        tables={k: "wc-dev-" + k for k in ("operations", "locks", "games")},
        now=NOW,
    )
    result = observe(api, sfn, **args)
    assert result["resume_eligible"] is owned and not api.calls[1:]
    execution["name"] = "another-operation"
    with pytest.raises(ValueError, match="identity mismatch"):
        observe(api, sfn, **args)
