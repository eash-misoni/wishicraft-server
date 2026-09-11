"""Proposed configuration/serializer/handler/provenance and operator boundaries."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template
from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]
from nacl.signing import SigningKey

from infrastructure.app import build_app
from tests.unit.test_backup_provenance import Dynamo, record
from tests.unit.test_discord_interactions import ADMIN_ROLE_ID, command_payload, configuration
from tests.unit.test_retention import CONTEXT, provenance, snapshot
from wishicraft import start_workflow_lambda, stop_workflow_lambda
from wishicraft.artifacts.prepare_second_game import materialize
from wishicraft.backup_provenance import BackupProvenanceRepository
from wishicraft.backup_recovery import recovery_digest, shared_tags
from wishicraft.discord_interactions import UnauthorizedInteraction, parse_and_authorize
from wishicraft.retention import plan_retention
from wishicraft.retention_workflow_lambda import _load_complete_provenance
from wishicraft.two_game_admin import declaration
from wishicraft.two_game_migration import prepare

ROOT = Path(__file__).resolve().parents[2]
GAMES = ["game-vanilla-main", "game-vanilla-secondary"]


def test_actual_cdk_configuration_initializes_and_drives_both_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="control-plane", two_games=True)
    resources = Template.from_stack(
        cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    ).to_json()["Resources"]
    functions = {
        r["Properties"]["FunctionName"]: r["Properties"]
        for r in resources.values()
        if r["Type"] == "AWS::Lambda::Function"
    }
    assert len(functions) == 11
    assert (
        len([r for r in resources.values() if r["Type"] == "AWS::StepFunctions::StateMachine"]) == 5
    )
    assert "ec2:DeleteSnapshot" not in json.dumps(resources)
    catalog = functions["wc-dev-start-task"]["Environment"]["Variables"]["RUNTIME_GAMES"]
    assert json.loads(catalog) == GAMES
    policies = json.dumps([r for r in resources.values() if r["Type"] == "AWS::IAM::Policy"])
    assert "states:StartExecution" in policies
    for module, name in [
        (start_workflow_lambda, "wc-dev-start-task"),
        (stop_workflow_lambda, "wc-dev-stop-task"),
    ]:
        env = functions[name]["Environment"]["Variables"]
        for key, value in env.items():
            monkeypatch.setenv(
                key,
                resources[value["Ref"]]["Properties"]["TableName"]
                if isinstance(value, dict)
                else value,
            )
        monkeypatch.setenv("AWS_REGION", "ap-northeast-1")

        class Api:
            game_id = GAMES[1]
            operation_type = "START" if module is start_workflow_lambda else "STOP"
            calls: list[dict[str, Any]] = []

            def get_item(self, **kwargs: Any) -> dict[str, Any]:
                assert kwargs["ConsistentRead"]
                return {
                    "Item": {
                        k: TypeSerializer().serialize(v)
                        for k, v in {
                            "operation_id": "op-current",
                            "target_game_id": self.game_id,
                            "operation_type": self.operation_type,
                        }.items()
                    }
                }

            def update_item(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs)
                assert "lease_expires_at >= :now" in kwargs["ConditionExpression"]
                return {}

        api = Api()
        import boto3  # type: ignore[import-untyped]

        monkeypatch.setattr(boto3, "client", lambda *args, _api=api, **kwargs: _api)
        monkeypatch.setattr(module, "_runtime", None)
        result = module.handler(
            {
                "schema_version": 1,
                "action": "renew",
                "operation_id": "op-current",
                "lease_id": "lease-current",
            },
            None,
        )
        assert result["lease_expires_at"] > 0
        assert module._runtime is not None and module._runtime.game_id == GAMES[1]
        api.game_id = GAMES[0]
        module.handler(
            {
                "schema_version": 1,
                "action": "renew",
                "operation_id": "op-current",
                "lease_id": "lease-current",
            },
            None,
        )
        assert module._runtime.game_id == GAMES[0]


def test_discord_registration_payload_parser_and_admin_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_GAMES", json.dumps(GAMES))
    document = declaration(ROOT, now=datetime.now(UTC))
    proposed = document["discord_commands"][0]["options"][-1]
    assert proposed["name"] == "switch"
    assert [x["value"] for x in proposed["options"][0]["choices"]] == GAMES
    payload = command_payload("switch", roles=[ADMIN_ROLE_ID])
    cast(dict[str, Any], payload["data"])["options"][0]["options"] = [
        {"type": 3, "name": "game", "value": GAMES[1]},
        {"type": 5, "name": "confirm", "value": True},
    ]
    config = configuration(SigningKey.generate())
    interaction = parse_and_authorize(json.dumps(payload).encode(), config=config)
    assert interaction.target_game_id == GAMES[1] and interaction.confirmed
    payload["member"] = {"roles": [config.player_role_id]}
    with pytest.raises(UnauthorizedInteraction):
        parse_and_authorize(json.dumps(payload).encode(), config=config)


def test_shared_provenance_wire_pair_and_loader_preserve_old_and_new() -> None:
    from wishicraft.config import load_configuration
    from wishicraft.host_runtime import render_boot_time_artifacts

    config = load_configuration(ROOT, "dev")
    rendered = render_boot_time_artifacts(
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=tuple(GAMES),
    )
    recovery = json.dumps(
        {
            "schema_version": 1,
            "source_volume_id": record().source_volume_id,
            "games": {
                g: {"game_id": g, "data_source": f"/srv/minecraft/games/{g}/server"} for g in GAMES
            },
            "runtime": {
                "manifest_json": rendered.manifest_json,
                "runtime_env": rendered.runtime_env,
                "compose_yaml": rendered.compose_yaml,
            },
        },
        sort_keys=True,
    )
    legacy = record()
    shared = replace(
        legacy,
        snapshot_id="snap-0123456789abcdef1",
        operation_id="op-shared",
        schema_version=2,
        recovery_json=recovery,
        metadata=shared_tags({**legacy.metadata, "WishicraftOperationId": "op-shared"}, recovery),
    )
    db = Dynamo()
    repository = BackupProvenanceRepository(db, table_name="backups")
    repository.register(legacy)
    repository.register(shared)
    assert repository.exact_match(shared)

    class Scan(Dynamo):
        def scan(self, **kwargs: Any) -> dict[str, Any]:
            return {"Items": list(db.items.values())}

    context = replace(
        CONTEXT,
        project=legacy.project,
        source_volume_id=legacy.source_volume_id,
        owner_id=legacy.verified_owner_id,
        shared_volume=True,
    )
    loaded = _load_complete_provenance(cast(Any, Scan()), "backups", context=context)
    assert loaded[legacy.snapshot_id].schema_version == 1
    assert loaded[shared.snapshot_id].recovery_digest == recovery_digest(recovery)
    raw = db.items["SNAPSHOT#" + shared.snapshot_id]
    raw["recovery_json"] = {"S": recovery.replace(GAMES[1], "game-other")}
    with pytest.raises(ValueError):
        _load_complete_provenance(cast(Any, Scan()), "backups", context=context)


def test_shared_retention_counts_volume_not_triggering_game_and_protects_legacy() -> None:
    items = []
    proofs = {}
    for index in range(8):
        item = snapshot(index)
        item = replace(
            item,
            tags={
                **item.tags,
                "WishicraftGameId": GAMES[index % 2],
                "WishicraftSchemaVersion": "2",
                "WishicraftBackupScope": "shared-volume",
                "WishicraftRecoveryDigest": "a" * 64,
            },
        )
        items.append(item)
        proofs[item.snapshot_id] = provenance(
            item, game_id=GAMES[index % 2], schema_version=2, recovery_digest="a" * 64
        )
    old = snapshot(10)
    items.append(old)
    proofs[old.snapshot_id] = provenance(old)
    plan = plan_retention(
        items,
        proofs,
        context=replace(CONTEXT, shared_volume=True),
        recycle_bin_preflight_complete=True,
    )
    assert len(plan.keep_ids) == 7 and plan.candidate_ids == (items[0].snapshot_id,)
    assert old.snapshot_id in plan.excluded_ids


def test_bundle_uses_deployed_predecessors_and_preserves_stopped_receipt(tmp_path: Path) -> None:
    document = declaration(ROOT, now=datetime.now(UTC))
    summary = prepare(ROOT, tmp_path / "bundle", document)
    plan = json.loads((tmp_path / "bundle/install.json").read_text())
    op = next(x for x in plan["files"] if x["destination"].endswith("/operation-v2"))
    assert op["predecessor"] == "aaf0233b0d4ad73c49aea3d7525413de62de27f2df880423a8f692569f9f61ee"
    assert plan["receipt_predecessor"]["phase"] == "stopped"
    assert all(not x["destination"].startswith("/srv/") for x in plan["files"])
    assert isinstance(summary["hashes"], dict)
    assert len(summary["hashes"]) > len(plan["files"])
    compile((tmp_path / "bundle/prepare-game.py").read_text(), "materializer", "exec")


def test_second_game_materialization_preserves_sibling_and_rejects_unknown_data(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / GAMES[0], tmp_path / GAMES[1]
    a.mkdir()
    (a / "world").write_bytes(b"existing world")
    files = declaration(ROOT, now=datetime.now(UTC))["materialization"]["files"]
    first = materialize(b, files, uid=os.getuid(), gid=os.getgid())
    assert materialize(b, files, uid=os.getuid(), gid=os.getgid()) == first
    assert (a / "world").read_bytes() == b"existing world"
    (b / "server/unknown").write_text("retain this data")
    with pytest.raises(ValueError, match="REQUIRES_OBSERVATION"):
        materialize(b, files, uid=os.getuid(), gid=os.getgid())
    assert (
        hashlib.sha256((a / "world").read_bytes()).digest()
        == hashlib.sha256(b"existing world").digest()
    )


def test_recovery_freeze_survives_lost_update_and_reuses_snapshot_time_games() -> None:
    from wishicraft.backup_recovery import RecoveryRepository
    from wishicraft.config import load_configuration
    from wishicraft.game_admin import initial_game
    from wishicraft.host_runtime import render_boot_time_artifacts
    from wishicraft.runtime_catalog import RuntimeCatalog

    config = load_configuration(ROOT, "dev")
    rendered = render_boot_time_artifacts(
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=tuple(GAMES),
    )

    class Api:
        operation: dict[str, Any] = {}
        game_reads = 0
        writes = 0

        def get_item(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["ConsistentRead"]
            if kwargs["TableName"] == "operations":
                return {"Item": self.operation}
            self.game_reads += 1
            game = replace(
                initial_game(ROOT, "dev", now=datetime.now(UTC)),
                game_id=kwargs["Key"]["game_id"]["S"],
            ).to_item()
            return {"Item": {k: TypeSerializer().serialize(v) for k, v in game.items()}}

        def update_item(self, **kwargs: Any) -> None:
            self.writes += 1
            assert "attribute_not_exists(backup_create_intent)" in kwargs["ConditionExpression"]
            self.operation["backup_recovery_json"] = kwargs["ExpressionAttributeValues"][
                ":recovery"
            ]
            raise TimeoutError("committed; reply lost")

    api = Api()
    repository = RecoveryRepository(api, "operations", "games")
    arguments: dict[str, Any] = dict(
        operation_id="op-backup",
        lease_id="lease-current",
        catalog=RuntimeCatalog(tuple(GAMES)),
        volume=record().source_volume_id,
        runtime_json=json.dumps(
            {
                "manifest_json": rendered.manifest_json,
                "runtime_env": rendered.runtime_env,
                "compose_yaml": rendered.compose_yaml,
            }
        ),
    )
    first = repository.freeze(**arguments)
    assert repository.freeze(**arguments) == first
    assert api.game_reads == 2 and api.writes == 1
    recovered = json.loads(first)
    assert recovered["games"][GAMES[0]]["world"]["generation"] == 1
    assert recovered["runtime"]["compose_yaml"] == rendered.compose_yaml
    with pytest.raises(ValueError, match="runtime mismatch"):
        recovery_digest(first.replace("VERSION=26.2", "VERSION=unknown"))


def test_new_game_changes_heartbeat_identity_within_same_boot() -> None:
    from datetime import timedelta

    from tests.unit.test_targeted_runtime_contract import NOW
    from wishicraft.runtime_heartbeat import ProtocolState, RuntimeObservation, derive_heartbeat
    from wishicraft.runtime_heartbeat_producer import _decode, _encode

    observation = RuntimeObservation(
        instance_id="i-0123456789abcdef0",
        runtime_id="runtime-main",
        boot_id="11111111-1111-1111-1111-111111111111",
        active_game_id=GAMES[0],
        protocol_state=ProtocolState.READY,
        player_count=0,
        observed_at=NOW,
        run_id="op-a",
        process_id="a" * 64,
    )
    a = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id=GAMES[0],
        observation=observation,
        previous=None,
    )
    b = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id=GAMES[1],
        previous=_decode(_encode(a)),
        observation=replace(
            observation,
            active_game_id=GAMES[1],
            run_id="op-b",
            process_id="b" * 64,
            observed_at=NOW + timedelta(minutes=29),
        ),
    )
    assert b.boot_id == a.boot_id and b.empty_since == NOW + timedelta(minutes=29)
    assert b.empty_since != a.empty_since and b.active_game_id == GAMES[1]
