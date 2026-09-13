"""CREATE through the real HTTP/session/Admission/domain/Dynamo serialization boundary."""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_web_operations import NOW, boundary, event, login, post  # noqa: F401
from wishicraft.artifacts import initial_game, reset_worlds
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.game_creation import REGISTRY_KEY
from wishicraft.web_status import decode


@pytest.fixture
def creation(boundary: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    monkeypatch.setenv("GAME_CREATION", "1")
    monkeypatch.setenv("GAMES_TABLE", "games")
    monkeypatch.setenv(
        "GAME_CREATION_DEFAULTS",
        json.dumps(
            {
                "package": {"package_id": "vanilla", "package_version": "initial-fixed-version"},
                "runtime": {"class": "default", "idle_shutdown_minutes": 30},
                "config_digest": "a" * 64,
            }
        ),
    )
    return boundary


def payload(**changes: Any) -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "type": "CREATE",
        "confirm": True,
        "creation": {"display_name": "第三のGame", "seed": None, "reset": False, **changes},
    }


@pytest.mark.parametrize("seed", [None, "0", "-9223372036854775808", "9223372036854775807"])
@pytest.mark.parametrize("reset", [False, True])
def test_create_terminal_metadata_only_stable_retry(
    creation: Any, seed: str | None, reset: bool
) -> None:
    app, sessions, backend, launches, calls = creation
    original = copy.deepcopy(backend.db.records)
    jar, request = login(sessions), payload(seed=seed, reset=reset)
    assert post(creation, jar, request)["statusCode"] == 202
    assert post(creation, jar, request)["statusCode"] == 200
    assert launches == []
    assert backend.db.transactions == 1
    for key, value in original.items():
        assert backend.db.records[key] == value
    keys = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"]
    assert len(keys) == 1
    game = {k: decode(v) for k, v in backend.db.records["games", keys[0]].items()}
    assert game["game_id"] != game["display_name"]
    assert game["materialization_state"] == "UNMATERIALIZED"
    assert game["creation"]["actor_id"] == "9"
    assert isinstance(game["created_at"], str)
    assert (
        game["world"]["seed"] == int(seed)
        if seed is not None
        else isinstance(game["world"]["seed"], int)
    )
    assert bool(game["creation"]["reset_policy"]) is reset
    op = backend.db.records["operation", game["creation"]["operation_id"]]
    assert op["status"] == {"S": "SUCCEEDED"}
    assert op["lease_id"] == {"NULL": True}
    read = app.handle(
        event(jar, path="/api/operations/request/" + request["request_id"], method="GET"), NOW
    )
    assert json.loads(read["body"])["operation"]["terminal"] is True
    caps = app.handle(event(jar, path="/api/capabilities", method="GET"), NOW)
    games = json.loads(caps["body"])["games"]
    assert len(games) == 3 and games[-1]["materialized"] is False
    changed = copy.deepcopy(request)
    changed["creation"]["display_name"] = "different"
    assert post(creation, jar, changed)["statusCode"] == 409
    # A re-login and page reload resolve the same durable actor-bound request.
    assert post(creation, login(sessions), request)["statusCode"] == 200
    assert backend.db.transactions == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"display_name": ""},
        {"display_name": "../world"},
        {"display_name": "<script>"},
        {"display_name": "x" * 81},
        {"display_name": "\x00"},
        {"seed": "9223372036854775808"},
        {"seed": "-9223372036854775809"},
        {"seed": 42},
        {"seed": True},
        {"seed": "hello"},
        {"seed": "1e9"},
        {"reset": "true"},
        {"path": "/data"},
        {"image": "arbitrary"},
    ],
)
def test_strict_validation(creation: Any, changes: dict[str, Any]) -> None:
    assert post(creation, login(creation[1]), payload(**changes))["statusCode"] == 400
    assert creation[2].db.transactions == 0


def test_player_and_forged_actor_rejected(creation: Any) -> None:
    assert post(creation, login(creation[1], ["3"]), payload())["statusCode"] == 403
    request = {**payload(), "roles": ["4"], "user_id": "9"}
    assert post(creation, login(creation[1]), request)["statusCode"] == 400
    assert creation[2].db.transactions == 0


def test_dynamic_reset_requires_materialization_and_reuses_policy(creation: Any) -> None:
    from tests.unit.test_web_operations import request
    from wishicraft.reset_policy import configured, seed

    _, sessions, backend, launches, _ = creation
    jar = login(sessions)
    post(creation, jar, payload(seed="-42", reset=True))
    game = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"][0]
    reset_request = request("RESET", game)
    assert post(creation, jar, reset_request)["statusCode"] == 422
    backend.db.records["games", game]["materialization_state"] = {"S": "MATERIALIZED"}
    assert post(creation, jar, reset_request)["statusCode"] == 202
    assert len(launches) == 1
    policy = configured()[game]
    assert policy == {"fixed_seed": -42, "retain_previous": 3, "minimum_free_bytes": 4294967296}
    assert seed("op-same", "fixed", policy) == -42
    assert seed("op-same", "new", policy) == seed("op-same", "new", policy)


@pytest.mark.parametrize("materialized", [False, True])
def test_shared_recovery_includes_dynamic_game(creation: Any, materialized: bool) -> None:
    import hashlib
    from dataclasses import replace

    from wishicraft.backup_recovery import RecoveryRepository, recovery_digest
    from wishicraft.config import load_configuration
    from wishicraft.game_admin import initial_game
    from wishicraft.host_runtime import render_boot_time_artifacts
    from wishicraft.operation import _attribute_map
    from wishicraft.runtime_catalog import RuntimeCatalog

    _, sessions, backend, _, _ = creation
    root = Path(__file__).resolve().parents[2]
    config = load_configuration(root, "dev")
    backend.catalog = (config.project.initial_game_id, backend.catalog[1])
    rendered = render_boot_time_artifacts(
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=backend.catalog,
    )
    post(creation, login(sessions), payload(seed="42", reset=True))
    game = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"][0]
    raw = backend.db.records["games", game]
    raw["creation"]["M"]["config_digest"] = {"S": rendered.digest}
    if materialized:
        raw["materialization_state"] = {"S": "MATERIALIZED"}
        raw["world"]["M"]["current_id"] = {"S": "op-reset-current"}
    for legacy in backend.catalog:
        backend.db.records["games", legacy] = _attribute_map(
            replace(initial_game(root, "dev", now=NOW), game_id=legacy).to_item()
        )
    backend.db.records["operation", "op-backup"] = {"operation_id": {"S": "op-backup"}}

    def update(**kwargs: Any) -> None:
        backend.db.records["operation", "op-backup"]["backup_recovery_json"] = kwargs[
            "ExpressionAttributeValues"
        ][":recovery"]

    backend.db.update_item = update
    repository = RecoveryRepository(backend.db, "operation", "games")
    value = repository.freeze(
        operation_id="op-backup",
        lease_id="lease-backup",
        catalog=RuntimeCatalog(backend.game_ids()),
        volume="vol-03ac9f534326c345c",
        runtime_json=json.dumps(
            {
                "manifest_json": rendered.manifest_json,
                "runtime_env": rendered.runtime_env,
                "compose_yaml": rendered.compose_yaml,
                "creation_config": {"initial_whitelist": []},
            }
        ),
    )
    assert recovery_digest(value) == hashlib.sha256(value.encode()).hexdigest()
    document = json.loads(value)
    assert len(document["games"]) == 3
    saved = document["games"][game]
    assert saved["materialization_state"] == ("MATERIALIZED" if materialized else "UNMATERIALIZED")
    assert saved["creation"]["reset_policy"]["fixed_seed"] == 42
    assert saved["data_source"] == f"/srv/minecraft/games/{game}/" + (
        "worlds/op-reset-current/server" if materialized else "server"
    )
    # Offline recovery uses the Snapshot-time registry, including a dynamic triggering Game.
    from tests.unit.test_backup_provenance import record
    from tests.unit.test_isolated_restore import source_evidence
    from wishicraft.backup_recovery import shared_tags
    from wishicraft.isolated_restore import verify_source

    previous = record()
    metadata = shared_tags({**previous.metadata, "WishicraftGameId": game}, value)
    captured = record(
        verified_owner_id="385526546525",
        game_id=game,
        metadata=metadata,
        schema_version=2,
        recovery_json=value,
    )
    evidence = source_evidence(captured)
    operation = evidence["operations"][0]
    operation["backup_recovery_json"] = {"S": value}
    operation["result"]["M"].update(
        _attribute_map({"scope": "shared-volume", "recovery_digest": recovery_digest(value)})
    )
    assert verify_source(evidence, captured.snapshot_id, root)["game_id"] == game


def test_backup_fence_and_lost_response(creation: Any) -> None:
    _, sessions, backend, launches, _ = creation
    jar, request = login(sessions), payload(reset=True)
    backend.db.records["locks", "minecraft-control"] = {"operation_type": {"S": "BACKUP"}}
    assert post(creation, jar, request)["statusCode"] == 409
    assert backend.db.transactions == 0
    backend.db.records["locks", "minecraft-control"] = {"operation_type": {"S": "START"}}
    invoke = backend.lambda_api.invoke

    def lose(**kwargs: Any) -> Any:
        invoke(**kwargs)
        raise TimeoutError("synthetic response lost")

    backend.lambda_api.invoke = lose
    assert post(creation, jar, request)["statusCode"] == 503
    assert post(creation, jar, request)["statusCode"] == 200
    assert backend.db.transactions == 1 and launches == []


def test_initial_preparation_retry_unknown_and_other_game(
    creation: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    post(creation, login(creation[1]), payload(seed="42", reset=True))
    backend = creation[2]
    game_id = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"][0]
    game = {k: decode(v) for k, v in backend.db.records["games", game_id].items()}
    games = tmp_path / "games"
    games.mkdir(mode=0o755)
    sibling = games / "existing"
    sibling.mkdir()
    (sibling / "sentinel").write_bytes(b"original")
    monkeypatch.setattr(reset_worlds, "GAMES", games)
    monkeypatch.setattr(reset_worlds, "OWNER_UID", os.getuid())
    monkeypatch.setattr(reset_worlds, "OWNER_GID", os.getgid())
    target = {
        "game_id": game_id,
        "data_source": str(games / game_id / "server"),
        "config_digest": "a" * 64,
        "run_id": "op-first-start",
    }
    config = {"initial_whitelist": [{"name": "fixture", "uuid": "synthetic"}]}

    def fail(path: Path, value: str) -> None:
        if path.name == "whitelist.json":
            raise OSError("synthetic interruption")
        atomic(path, value)

    with pytest.raises(OSError):
        initial_game.prepare(game, config, target, fail, uid=os.getuid(), gid=os.getgid())
    initial_game.prepare(game, config, target, atomic, uid=os.getuid(), gid=os.getgid())
    initial_game.prepare(
        game, config, {**target, "run_id": "op-retry"}, atomic, uid=os.getuid(), gid=os.getgid()
    )
    data = Path(target["data_source"])
    assert "level-seed=42" in (data / "server.properties").read_text()
    assert initial_game.initialized(target, atomic) is True
    (data / "world").mkdir()
    (data / "world/level.dat").write_bytes(b"synthetic world")
    assert initial_game.initialized(target, atomic) is True
    (data / "world/level.dat").unlink()
    with pytest.raises(ValueError, match="INITIAL_WORLD_MISSING"):
        initial_game.initialized(target, atomic)
    assert (sibling / "sentinel").read_bytes() == b"original"


def test_host_bundle_reproduces_predecessors_and_never_moves_worlds(tmp_path: Path) -> None:
    from wishicraft.game_creation_migration import prepare

    root = Path(__file__).resolve().parents[2]
    evidence = json.loads((root / "docs/evidence/2026-09-12-reset-production.json").read_text())
    receipt = copy.deepcopy(evidence["bundle"]["plan"]["receipt_predecessor"])
    receipt["target"]["config_digest"] = evidence["bundle"]["config_digest"]
    plan = prepare(root, tmp_path / "bundle", receipt)
    assert {entry["destination"] for entry in plan["files"]} == {
        "/etc/wishicraft/runtime-contract.json",
        "/usr/local/libexec/wishicraft/operation-v2",
        "/usr/local/libexec/wishicraft/initial_game.py",
    }
    assert plan["receipt_predecessor"] == receipt
    assert plan["files"][-1]["predecessor"] is None
    assert plan["backup_namespace"] == "game-creation-v1"
    with pytest.raises(FileExistsError):
        prepare(root, tmp_path / "bundle", receipt)
