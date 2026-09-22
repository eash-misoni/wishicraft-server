"""Transported host evidence through the real STOP handler and package authority."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.probe_fixtures import TARGET_INSTANCE_ID, runtime_running_document
from tests.unit.test_full_game_binding import DIGEST, GAMES, full_game
from tests.unit.test_stop_workflow_lambda import _heartbeat_item, _intent_item
from wishicraft import runtime_catalog
from wishicraft import stop_workflow_lambda as stop
from wishicraft.artifacts import game_package
from wishicraft.operation import OperationStatus, _attribute_map
from wishicraft.probe import ProbeContractError, parse_host_runtime_probe
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.runtime_contract import RuntimeTargetRepository
from wishicraft.ssm_probe import CanonicalHostRuntimeProbeRunner

NOW = datetime(2026, 9, 22, 7, 0, tzinfo=UTC)


class Clock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Clock:
        return cls(2026, 9, 22, 7, 0, tzinfo=UTC)


def fixture_game(kind: str) -> dict[str, Any]:
    game = full_game(GAMES[0] if kind == "vanilla" else GAMES[2])
    if kind == "paper":
        package = next(p for p in game_package.load() if p["loader"]["type"] == "paper")
        game["package"] = {
            "package_id": package["package_id"],
            "package_version": package["package_version"],
            "definition": package,
        }
        game["creation"]["package_digest"] = game_package.digest(package)
    return game


def run_gate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str = "paper",
    count: int | None = 0,
    damage: str | None = None,
    packages: bool = True,
) -> tuple[dict[str, object], Any, dict[str, Any]]:
    game = fixture_game(kind)
    gid = game["game_id"]
    version = "26.2" if kind == "vanilla" else game["package"]["definition"]["minecraft_version"]
    document: Any = runtime_running_document(
        reported_version=f"Paper {version}" if kind == "paper" else version,
        player_count=count,
    )
    document["active_game"]["game_id"] = gid
    document["execution"] = {
        "phase": "running",
        "process_id": "b" * 64,
        "target": {
            "instance_id": TARGET_INSTANCE_ID,
            "game_id": gid,
            "data_source": f"/srv/minecraft/games/{gid}/server",
            "config_digest": DIGEST,
            "run_id": "op-running",
        },
    }
    if damage == "version":
        document["minecraft"]["protocol"]["reported_version"] = "26.2"
    if damage == "observed-game":
        document["active_game"]["game_id"] = GAMES[1]
    if damage == "run":
        document["execution"]["target"]["run_id"] = "op-other"
    if damage == "process":
        document["execution"]["process_id"] = "c" * 64
    if damage == "runtime-digest":
        document["execution"]["target"]["config_digest"] = "f" * 64
    heartbeat = _heartbeat_item(now=NOW)
    heartbeat.update(
        instance_id={"S": TARGET_INSTANCE_ID},
        active_game_id={"S": gid},
        run_id={"S": "op-running"},
        process_id={"S": "b" * 64},
    )
    intent = _intent_item(now=NOW)
    intent.update(game_id={"S": gid}, run_id={"S": "op-running"}, process_id={"S": "b" * 64})

    class Dynamo:
        direct = False
        game_reads = 0
        updates: list[dict[str, object]]

        def __init__(self) -> None:
            self.updates = []

        def get_item(self, **kwargs: Any) -> object:
            assert kwargs["ConsistentRead"] is True
            table = kwargs["TableName"]
            if table == "operations":
                return {
                    "Item": {
                        "operation_type": {"S": "STOP"},
                        "target_game_id": {"S": gid},
                    }
                }
            if table == "games":
                self.game_reads += 1
                assert kwargs["Key"] == {"game_id": {"S": gid}}
                current = copy.deepcopy(game)
                if self.direct:
                    if damage == "package-digest":
                        current["creation"]["package_digest"] = "f" * 64
                    if damage == "definition":
                        current["package"]["definition"]["minecraft_version"] = "26.2"
                    if damage == "returned-game":
                        current["game_id"] = GAMES[1]
                    if damage == "missing-game":
                        return {}
                return {"Item": _attribute_map(current)}
            assert table in {"intents", "heartbeats"}
            return {"Item": intent if table == "intents" else heartbeat}

        def update_item(self, **kwargs: Any) -> object:
            assert kwargs["TableName"] == "intents"
            self.updates.append(kwargs)
            return {}

    db = Dynamo()
    ec2, ssm = Mock(), Mock()
    ec2.describe_instances.return_value = {
        "Reservations": [
            {"Instances": [{"InstanceId": TARGET_INSTANCE_ID, "State": {"Name": "running"}}]}
        ]
    }
    ec2.describe_volumes.return_value = {
        "Volumes": [
            {
                "VolumeId": "vol-0123456789abcdef0",
                "Attachments": [
                    {
                        "InstanceId": TARGET_INSTANCE_ID,
                        "Device": "/dev/sdf",
                        "State": "attached",
                        "DeleteOnTermination": False,
                    }
                ],
            }
        ]
    }
    ssm.describe_instance_information.return_value = {
        "InstanceInformationList": [{"InstanceId": TARGET_INSTANCE_ID, "PingStatus": "Online"}]
    }
    runtime = SimpleNamespace(
        game_id=GAMES[1],  # A warm Lambda must bind this invocation's STOP Game.
        system_id="wishicraft-main",
        runtime_id="wishicraft-host-runtime",
        config_digest=DIGEST,
        targets=RuntimeTargetRepository(db, "operations"),
        dynamodb=db,
        intents_table="intents",
        heartbeats_table="heartbeats",
        resolver=SimpleNamespace(resolve=lambda: TARGET_INSTANCE_ID),
        ec2=ec2,
        ssm=ssm,
        data_volume_id="vol-0123456789abcdef0",
        data_volume_device="/dev/sdf",
        coordinator=Mock(),
        operations=Mock(),
        cloudwatch=Mock(),
    )
    catalog = RuntimeCatalog(GAMES)
    monkeypatch.setattr(runtime_catalog, "configured_catalog", lambda: catalog)
    monkeypatch.setattr(stop, "configured_catalog", lambda: catalog)
    monkeypatch.setattr(stop, "_runtime", runtime)
    monkeypatch.setattr(stop, "datetime", Clock)
    for key, value in {
        "GAME_PACKAGES": "1" if packages else "0",
        "GAMES_TABLE": "games",
        "RUNTIME_GAMES": json.dumps(GAMES[:2]),
        "RESET_CONTRACT": "0",
        "SSM_PROBE_TIMEOUT_SECONDS": "60",
        "METRIC_NAMESPACE": "Wishicraft/ControlPlane",
        "STAGE": "dev",
    }.items():
        monkeypatch.setenv(key, value)

    def probe(self: object, *, instance_id: str) -> object:
        assert instance_id == TARGET_INSTANCE_ID
        db.direct = True
        if damage == "transport":
            raise RuntimeError("observation failed")
        return SimpleNamespace(stdout=json.dumps(document))

    monkeypatch.setattr(CanonicalHostRuntimeProbeRunner, "run_probe", probe)
    result = stop.handler(
        {
            "schema_version": 1,
            "action": "automatic_final_gate",
            "operation_id": "op-scheduled-stop",
            "lease_id": "lease-scheduled-stop",
            "requested_by": "SCHEDULE",
            "auto_stop_intent_id": "asi-decimal-regression",
            "state": {
                "game_id": gid,
                "desired_state": "RUNNING",
                "health": "HEALTHY",
                "discrepancies": [],
                "observation_errors": [],
                "target_instance_id": TARGET_INSTANCE_ID,
            },
        },
        None,
    )
    assert db.direct  # Every case must reach the direct probe, not an earlier safety gate.
    assert runtime.game_id == gid
    assert game == fixture_game(kind)
    ec2.stop_instances.assert_not_called()
    ssm.send_command.assert_not_called()
    return result, runtime, document


@pytest.mark.parametrize("kind", ["paper", "vanilla", "neoforge"])
def test_real_final_gate_accepts_zero_using_registered_package(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    result, runtime, _ = run_gate(monkeypatch, kind=kind)
    assert result == {"proceed": True, "automatic": True}
    assert runtime.dynamodb.game_reads == 2  # Operation binding, then observed receipt authority.
    runtime.operations.complete_owned.assert_not_called()
    assert runtime.dynamodb.updates == []


def test_old_global_version_rejects_the_same_valid_paper_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, document = run_gate(monkeypatch)
    with pytest.raises(ProbeContractError, match="version comparison"):
        parse_host_runtime_probe(
            json.dumps(document),
            expected_instance_id=TARGET_INSTANCE_ID,
            expected_minecraft_version="26.2",
        )
    assert result["proceed"] is True


@pytest.mark.parametrize("count", [1, 5, None])
def test_positive_or_unknown_players_cancel(
    monkeypatch: pytest.MonkeyPatch, count: int | None
) -> None:
    result, runtime, _ = run_gate(monkeypatch, count=count)
    assert result["proceed"] is False
    assert result["reason"] == "DIRECT_PLAYER_OBSERVATION_NOT_ZERO"
    assert runtime.operations.complete_owned.call_args.kwargs["status"] is OperationStatus.CANCELLED


@pytest.mark.parametrize(
    "damage",
    [
        "package-digest",
        "definition",
        "returned-game",
        "missing-game",
        "observed-game",
        "runtime-digest",
        "version",
        "transport",
        "run",
        "process",
    ],
)
def test_untrusted_identity_or_observation_cancels(
    monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    result, runtime, _ = run_gate(monkeypatch, damage=damage)
    assert result["proceed"] is False
    assert runtime.operations.complete_owned.call_args.kwargs["status"] is OperationStatus.CANCELLED
    assert len(runtime.dynamodb.updates) == 1


def test_pre_package_vanilla_compatibility_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _, _ = run_gate(monkeypatch, kind="vanilla", packages=False)
    assert result["proceed"] is True
