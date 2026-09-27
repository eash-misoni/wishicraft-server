"""Generated IAM and real registry/freeze/create boundaries; no live AWS claims."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from tests.unit.test_backup import stopped_state
from tests.unit.test_backup_safety import LEASE, OP, event, runtime  # noqa: F401
from tests.unit.test_game_creation import creation, payload  # noqa: F401
from tests.unit.test_web_operations import NOW, boundary, login, post  # noqa: F401
from tests.unit.test_world_import import source  # noqa: F401
from wishicraft import backup_workflow_lambda as task
from wishicraft.artifacts.game_package import load
from wishicraft.backup_recovery import RecoveryRepository, recovery_digest
from wishicraft.config import load_configuration
from wishicraft.game_admin import initial_game
from wishicraft.game_creation import REGISTRY_KEY
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_catalog import configured_catalog

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("two_games,create", [(False, False), (True, False), (True, True)])
def test_generated_backup_policy_boundaries(two_games: bool, create: bool) -> None:
    app = build_app(
        ROOT,
        "dev",
        phase=8,
        deployment="control-plane",
        daily_backup_validation="legacy",
        two_games=two_games,
        reset=create,
        game_creation=create,
    )
    template = Template.from_stack(
        cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    )
    functions = template.find_resources("AWS::Lambda::Function")
    backup = next(
        v["Properties"]
        for v in functions.values()
        if v["Properties"]["FunctionName"] == "wc-dev-backup-task"
    )
    role = backup["Role"]["Fn::GetAtt"][0]
    statements = [
        s
        for p in template.find_resources("AWS::IAM::Policy").values()
        if {"Ref": role} in p["Properties"]["Roles"]
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]

    def actions(s: dict[str, Any]) -> list[str]:
        return [s["Action"]] if isinstance(s["Action"], str) else s["Action"]

    creates = [s for s in statements if "ec2:CreateSnapshot" in actions(s)]
    assert len(creates) == 2
    snapshot = next(s for s in creates if "snapshot/" in str(s["Resource"]))
    volume = next(s for s in creates if "volume/" in str(s["Resource"]))
    assert volume == {
        "Action": "ec2:CreateSnapshot",
        "Effect": "Allow",
        "Resource": "arn:aws:ec2:ap-northeast-1:385526546525:volume/vol-03ac9f534326c345c",
    }
    assert snapshot["Resource"] == "arn:aws:ec2:ap-northeast-1::snapshot/*"
    expected = {
        "aws:RequestTag/Project": "wishicraft",
        "aws:RequestTag/Stage": "dev",
        "aws:RequestTag/WishicraftCategory": "backup",
        "aws:RequestTag/WishicraftProtected": "false",
    }
    conditions = snapshot["Condition"]
    game_key = "aws:RequestTag/WishicraftGameId"
    legacy = ["game-vanilla-main", "game-vanilla-secondary"] if two_games else ["game-vanilla-main"]
    if create:
        assert conditions == {
            "StringEquals": expected,
            "StringLike": {game_key: [*legacy, "game-" + "?" * 64]},
        }
        patterns = conditions["StringLike"][game_key]
    else:
        assert conditions == {
            "StringEquals": {**expected, game_key: legacy if two_games else legacy[0]}
        }
        patterns = legacy
    for value in legacy:
        assert any(fnmatchcase(value, p) for p in patterns)
    for value in ["game-" + "a" * 64, "game-" + "1" * 64, "game-" + "f" * 64]:
        assert any(fnmatchcase(value, p) for p in patterns) is create
    for value in ["", "game-", "game-" + "a" * 63, "game-" + "a" * 65]:
        assert not any(fnmatchcase(value, p) for p in patterns)
    # Missing tag has no StringEquals/StringLike match (no IfExists/Null escape).
    assert set(conditions) <= {"StringEquals", "StringLike"}
    tags = [s for s in statements if "ec2:CreateTags" in actions(s)]
    assert tags == [
        {
            "Action": "ec2:CreateTags",
            "Effect": "Allow",
            "Resource": snapshot["Resource"],
            "Condition": {"StringEquals": {"ec2:CreateAction": "CreateSnapshot"}},
        }
    ]
    assert {a for s in statements for a in actions(s) if a.startswith("ec2:")} == {
        "ec2:CreateSnapshot",
        "ec2:CreateTags",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
    }


@pytest.fixture
def dynamic(runtime: Any, creation: Any, source: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    _, sessions, backend, _, _ = creation
    config = load_configuration(ROOT, "dev")
    legacy = ("game-vanilla-main", "game-vanilla-secondary")
    backend.catalog = legacy
    rendered = render_boot_time_artifacts(
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=legacy,
        packages=load(),
    )
    monkeypatch.setenv("GAME_PACKAGES", "1")
    ids = []
    for package in ["create-survival", "create-terralith", "vps-survival", "vanilla"]:
        options: dict[str, Any] = {"package_id": package, "display_name": package, "seed": "-123"}
        if package == "vps-survival":
            options["import"] = source[1]
        assert post(creation, login(sessions), payload(**options))["statusCode"] == 202
        registered = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"]
        game = next(g for g in registered if g not in ids)
        ids.append(game)
        raw = backend.db.records["games", game]
        raw["creation"]["M"]["config_digest"] = {"S": rendered.digest}
        raw["materialization_state"] = {"S": "MATERIALIZED"}
    db = runtime.db
    for (_, key), item in backend.db.records.items():
        if key in [REGISTRY_KEY, *ids]:
            db.items[key] = db.decode(item)
    for game in legacy:
        db.items[game] = replace(initial_game(ROOT, "dev", now=NOW), game_id=game).to_item()
    db.items[legacy[1]]["world"].update(
        current_id="op-original", generation=1, generation_counter=2
    )
    original_update = db.update_item

    def update(**kwargs: Any) -> Any:
        values = db.decode(kwargs["ExpressionAttributeValues"])
        if ":recovery" in values:
            db.items[OP]["backup_recovery_json"] = values[":recovery"]
            return {}
        if ":step" in values:
            return {}
        return original_update(**kwargs)

    monkeypatch.setattr(db, "update_item", update)
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: db)
    monkeypatch.setenv("RUNTIME_GAMES", json.dumps(legacy))
    runtime.recovery = RecoveryRepository(db, "operations", "games")
    monkeypatch.setattr(
        task,
        "recovery_runtime_config",
        lambda: json.dumps(
            {
                "manifest_json": rendered.manifest_json,
                "runtime_env": rendered.runtime_env,
                "compose_yaml": rendered.compose_yaml,
                "creation_config": {"initial_whitelist": []},
            }
        ),
    )
    runtime.dynamic_ids = ids
    return runtime


@pytest.mark.parametrize("selected", range(4))
def test_registered_dynamic_backup_freezes_all_games_before_create(
    dynamic: Any, selected: int
) -> None:
    game = dynamic.dynamic_ids[selected]
    dynamic.db.items[OP]["target_game_id"] = game
    originals = {g: copy.deepcopy(v) for g, v in dynamic.db.items.items() if g.startswith("game-")}
    assert task.handler(event("preflight", state=stopped_state()), None) == {"allowed": True}
    result = cast(dict[str, Any], task.handler(event("create"), None))
    assert result["tags"]["WishicraftGameId"] == game
    assert result["tags"]["WishicraftBackupScope"] == "shared-volume"
    frozen = dynamic.db.items[OP]["backup_recovery_json"]
    assert result["tags"]["WishicraftRecoveryDigest"] == recovery_digest(frozen)
    records = json.loads(frozen)["games"]
    assert len(records) == 6
    for g, original in originals.items():
        assert dynamic.db.items[g] == original
        assert {k: v for k, v in records[g].items() if k != "data_source"} == original
    assert records["game-vanilla-secondary"]["world"]["generation_counter"] == 2
    assert len(dynamic.ec2.created) == 1


def test_registry_addition_is_visible_without_redeploy(dynamic: Any) -> None:
    before = configured_catalog()
    new_id = "game-" + "e" * 64
    record = copy.deepcopy(dynamic.db.items[dynamic.dynamic_ids[0]])
    record["game_id"] = new_id
    record["creation"]["operation_id"] = "op-" + "e" * 64
    dynamic.db.items[new_id] = record
    dynamic.db.items[REGISTRY_KEY]["registered_ids"].add(new_id)
    after = configured_catalog()
    assert before and after and new_id not in before.game_ids and new_id in after.game_ids
    dynamic.db.items[OP]["target_game_id"] = new_id
    task.handler(event("preflight", state=stopped_state()), None)
    result = cast(dict[str, Any], task.handler(event("create"), None))
    assert result["tags"]["WishicraftGameId"] == new_id


@pytest.mark.parametrize("corruption", ["unregistered", "record", "package", "registry-read"])
def test_dynamic_invalid_authority_never_creates_snapshot(
    dynamic: Any,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    game = dynamic.dynamic_ids[0]
    dynamic.db.items[OP]["target_game_id"] = game
    if corruption == "unregistered":
        dynamic.db.items[OP]["target_game_id"] = "game-" + "e" * 64
    elif corruption == "record":
        dynamic.db.items[game]["lifecycle_state"] = "BROKEN"
    elif corruption == "package":
        dynamic.db.items[game]["creation"]["package_digest"] = "f" * 64
    else:
        original = dynamic.db.get_item

        def get(**kwargs: Any) -> Any:
            if kwargs["Key"] == {"game_id": {"S": REGISTRY_KEY}}:
                raise RuntimeError("registry unavailable")
            return original(**kwargs)

        monkeypatch.setattr(dynamic.db, "get_item", get)
    with pytest.raises((ValueError, RuntimeError)):
        task.handler(event("preflight", state=stopped_state()), None)
    assert dynamic.ec2.created == []
    assert "backup_create_intent" not in dynamic.db.items[OP]
