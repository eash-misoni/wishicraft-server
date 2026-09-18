"""Immutable registration through the shared START/normal Reconcile boundary."""

from __future__ import annotations

import copy
import json
from typing import Any
from unittest.mock import Mock

import pytest

from tests.probe_fixtures import TARGET_INSTANCE_ID, runtime_running_document
from tests.unit.test_full_game_binding import DIGEST, GAMES, full_game
from tests.unit.test_reconcile import NOW, Dns, Repository, Resolver
from wishicraft.artifacts import game_package
from wishicraft.endpoint import DnsObservation, DnsState
from wishicraft.operation import _attribute_map
from wishicraft.package_authority import GamePackageAuthority, registered_package
from wishicraft.probe import ProbeContractError, parse_host_runtime_probe
from wishicraft.reconcile import ReconcileService
from wishicraft.reconcile_lambda import AwsStatusFactory
from wishicraft.start_workflow import StartObservation
from wishicraft.system_state import DesiredState


def boundary(game: dict[str, Any], observed: str | None) -> tuple[Any, dict[str, Any]]:
    document: Any = runtime_running_document(reported_version=observed)
    gid = game["game_id"]
    document["active_game"]["game_id"] = gid
    document["execution"] = {
        "phase": "running",
        "process_id": "b" * 64,
        "target": {
            "instance_id": TARGET_INSTANCE_ID,
            "game_id": gid,
            "data_source": f"/srv/minecraft/games/{gid}/server",
            "config_digest": DIGEST,
            "run_id": "op-fixture-new",
        },
    }
    api = Mock()
    api.get_item.return_value = {"Item": _attribute_map(game)}
    authority = GamePackageAuthority(api, "games", GAMES[:2])
    ec2, ssm = Mock(), Mock()
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": TARGET_INSTANCE_ID,
                        "State": {"Name": "running"},
                        "PublicIpAddress": "203.0.113.8",
                        "PrivateIpAddress": "10.0.0.8",
                    }
                ]
            }
        ]
    }
    ssm.describe_instance_information.return_value = {
        "InstanceInformationList": [
            {
                "InstanceId": TARGET_INSTANCE_ID,
                "PingStatus": "Online",
            }
        ]
    }
    factory = AwsStatusFactory(
        ec2, ssm, game_id=gid, timeout_seconds=60, expected_version=authority.expected_version
    )
    observer = factory.create(TARGET_INSTANCE_ID)
    transport = Mock()
    transport.run_probe.return_value.stdout = json.dumps(document)
    observer._host_runtime_probe = transport
    factory.create = Mock(return_value=observer)  # type: ignore[method-assign]
    result = ReconcileService(
        system_id="wishicraft-main",
        environment="dev",
        game_id=gid,
        target_resolver=Resolver(),
        status_factory=factory,
        dns_observer=Dns(DnsObservation("mc.example.", DnsState.PRESENT, ("203.0.113.8",))),
        repository=Repository(DesiredState.RUNNING),
    ).reconcile(observed_at=NOW)
    return result, document


@pytest.mark.parametrize(
    "gid,version", [(GAMES[0], "26.2"), (GAMES[1], "26.2"), (GAMES[2], "1.21.1")]
)
def test_start_and_running_reconcile_accept_authoritative_package(gid: str, version: str) -> None:
    result, _ = boundary(full_game(gid), version)
    assert result.observation["runtime_ready"] is True
    assert StartObservation.from_item(result.to_item()).ready_for_success(gid)


@pytest.mark.parametrize(
    "gid,version",
    [
        (GAMES[0], "1.21.1"),
        (GAMES[2], "26.2"),
        (GAMES[2], None),
        (GAMES[2], ""),
        (GAMES[2], "1.21.10"),
    ],
)
def test_host_claim_true_cannot_override_expected_package(gid: str, version: str | None) -> None:
    result, _ = boundary(full_game(gid), version)
    assert result.observation["runtime_ready"] is False
    assert not StartObservation.from_item(result.to_item()).ready_for_success(gid)


@pytest.mark.parametrize(
    "damage", ["digest", "unknown", "definition", "game", "legacy", "loader", "mod"]
)
def test_corrupt_or_unknown_authority_fails_closed(damage: str) -> None:
    game = full_game(GAMES[2])
    if damage == "digest":
        game["creation"]["package_digest"] = "f" * 64
    elif damage == "unknown":
        game["package"]["package_id"] = "unknown"
    elif damage == "definition":
        game["package"]["definition"]["minecraft_version"] = "26.2"
    elif damage == "game":
        game["schema_version"] = 2
    elif damage == "legacy":
        del game["creation"]
    elif damage == "loader":
        game["package"]["definition"]["loader"]["version"] = "21.1.220"
    else:
        game["package"]["definition"]["mods"][0]["sha256"] = "f" * 64
    result, _ = boundary(game, "1.21.1")
    assert result.observation["runtime_ready"] is False


def test_catalog_and_registration_are_read_without_mutation() -> None:
    game = full_game(GAMES[2])
    before = copy.deepcopy(game)
    api = Mock()
    api.get_item.return_value = {"Item": _attribute_map(game)}
    package = registered_package(api, "games", GAMES[2], legacy_ids=GAMES[:2])
    assert game == before
    assert package["loader"]["version"] == "21.1.219"
    assert (
        game_package.digest(package)
        == "720deb9f4a32515af87c7f620cf9d2667cabbc7e9b793db109cb011b71122f0b"
    )
    api.get_item.assert_called_once_with(
        TableName="games", Key={"game_id": {"S": GAMES[2]}}, ConsistentRead=True
    )
    assert api.method_calls == [api.method_calls[0]]


def test_unresolved_expected_version_never_defaults_to_vanilla() -> None:
    with pytest.raises(ProbeContractError, match="unresolved"):
        parse_host_runtime_probe(
            json.dumps(runtime_running_document()), expected_instance_id=TARGET_INSTANCE_ID
        )
