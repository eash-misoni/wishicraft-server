"""Registry changes reach both consumers without rebuilding or registering commands."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nacl.signing import SigningKey

from tests.unit.test_discord_interactions import (
    ADMIN_ROLE_ID,
    command_payload,
    configuration,
    signed_event,
)
from web.foundation import build_foundation
from wishicraft import discord_command_lambda as ingress
from wishicraft.artifacts import game_package
from wishicraft.discovery_commands import autocomplete
from wishicraft.game_creation import REGISTRY_KEY
from wishicraft.game_discovery import Discovery, choices, guide_html
from wishicraft.reset_commands import extend
from wishicraft.system_state import _to_attribute
from wishicraft.two_game_admin import declaration
from wishicraft.web_app import WebApp

ROOT = Path(__file__).resolve().parents[2]
POLICY = {"fixed_seed": 0, "retain_previous": 3, "minimum_free_bytes": 4294967296}


class Registry:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.ids: list[str] = []
        self.fail = False

    def add(self, index: int, package: dict[str, Any], *, reset: bool = False) -> str:
        game_id = "game-" + hashlib.sha256(str(index).encode()).hexdigest()
        self.ids.append(game_id)
        self.items[game_id] = {
            "game_id": game_id,
            "display_name": f"World {index}",
            "lifecycle_state": "ACTIVE",
            "materialization_state": "MATERIALIZED",
            "package": {
                **{k: package[k] for k in ("package_id", "package_version")},
                "definition": package,
            },
            "creation": {
                "package_digest": game_package.digest(package),
                "reset_policy": POLICY if reset else None,
            },
            "private": "arn:aws:private /srv/minecraft private.example.net",
        }
        return game_id

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("private database exception")
        key = kwargs["Key"]["game_id"]["S"]
        if key == REGISTRY_KEY:
            return (
                {"Item": {"game_id": {"S": key}, "registered_ids": {"SS": self.ids}}}
                if self.ids
                else {}
            )
        item = self.items.get(key)
        return {"Item": {k: _to_attribute(v) for k, v in item.items()}} if item else {}


@pytest.fixture
def registry() -> Registry:
    api = Registry()
    for i, package in enumerate(game_package.load()):
        api.add(i, package, reset=i == 0)
    return api


def reader(api: Registry) -> Discovery:
    return Discovery(api, "games", (), {})


def test_both_consumers_follow_new_arbitrary_games_and_mixed_packages(registry: Registry) -> None:
    discovery = reader(registry)
    first = discovery.read()
    assert len(first) == 4
    for i in range(4, 7):
        game = registry.add(i, game_package.load()[0])
        assert game in {c["value"] for c in choices(discovery.read(), "start", "")}
        assert f"World {i}" in guide_html(discovery.read())
    games = discovery.read()
    assert len(choices(games, "switch", "")) == 7
    assert len(choices(games, "reset", "")) == 1
    for value in ("vanilla", "neoforge", "paper", "26.2", "1.21.1", "26.1.2"):
        assert value in guide_html(games)
    assert "private" not in guide_html(games)
    assert all(g["id"] not in guide_html(games) for g in games)


def test_search_order_limit_duplicate_names_and_reset_filter(registry: Registry) -> None:
    for i in range(4, 40):
        registry.add(i, game_package.load()[0], reset=True)
    registry.items[registry.ids[1]]["display_name"] = "World 0"
    games = reader(registry).read()
    assert len(choices(games, "start", "")) == 25
    duplicates = [g for g in games if g["name"] == "World 0"]
    assert len({g["label"] for g in duplicates}) == 2
    assert all(len(g["label"]) <= 100 for g in games)
    assert choices(games, "start", "world 3")[0]["value"] == registry.ids[3]
    assert choices(games, "start", registry.ids[7][-10:])[0]["value"] == registry.ids[7]
    assert not choices(games, "reset", registry.ids[2])


@pytest.mark.parametrize("state", ["ARCHIVED", "DELETING", "DELETED", "UNKNOWN"])
def test_inactive_missing_and_unmaterialized_reset(registry: Registry, state: str) -> None:
    registry.items[registry.ids[0]]["lifecycle_state"] = state
    del registry.items[registry.ids[1]]
    registry.items[registry.ids[2]]["materialization_state"] = "UNMATERIALIZED"
    registry.items[registry.ids[2]]["creation"]["reset_policy"] = POLICY
    games = reader(registry).read()
    assert len(games) == 2
    assert not choices(games, "reset", "")


def test_failure_and_deadline_never_return_legacy_fallback(registry: Registry) -> None:
    with pytest.raises(TimeoutError):
        reader(registry).read(deadline=time.monotonic() - 1)
    registry.fail = True
    with pytest.raises(RuntimeError):
        Discovery(registry, "games", ("game-vanilla-main", "game-vanilla-secondary"), {}).read()


def test_schema_changes_game_options_only() -> None:
    old = extend(
        declaration(ROOT, now=datetime.now(UTC))["discord_commands"], ("game-vanilla-secondary",)
    )
    new = autocomplete(old)
    expected = deepcopy(old)
    for sub in expected[0]["options"]:
        for option in sub.get("options", []):
            if option["name"] == "game":
                option.pop("choices")
                option["autocomplete"] = True
    assert new == expected
    assert "choices" in old[0]["options"][1]["options"][0]


@pytest.mark.parametrize("command", ["start", "switch", "reset"])
def test_signed_autocomplete_routes_without_admission(
    registry: Registry, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    key = SigningKey.generate()
    monkeypatch.setattr(ingress, "_configuration", lambda: configuration(key))
    monkeypatch.setenv("RUNTIME_GAMES", '["game-legacy"]')
    monkeypatch.setenv("GAMES_TABLE", "games")
    monkeypatch.setenv("RESET_POLICIES", "{}")
    import boto3  # type: ignore[import-untyped]

    monkeypatch.setattr(boto3, "client", lambda *a, **k: registry)

    def forbidden() -> None:
        pytest.fail("autocomplete must never admit or defer")

    monkeypatch.setattr(ingress, "_get_operation_admission", forbidden)
    monkeypatch.setattr(ingress, "_get_interaction_callback", forbidden)
    payload: Any = command_payload(command, roles=[ADMIN_ROLE_ID])
    payload["type"] = 4
    payload["data"]["options"][0]["options"] = [
        {"name": "game", "type": 3, "value": "", "focused": True}
    ]
    result = json.loads(str(ingress.handler(signed_event(payload, key), None)["body"]))
    assert result["type"] == 8
    assert len(result["data"]["choices"]) == (1 if command == "reset" else 4)
    registry.fail = True
    assert (
        json.loads(str(ingress.handler(signed_event(payload, key), None)["body"]))["data"][
            "choices"
        ]
        == []
    )
    payload["guild_id"] = "99"
    assert (
        json.loads(str(ingress.handler(signed_event(payload, key), None)["body"]))["data"][
            "choices"
        ]
        == []
    )


def test_public_html_reloads_registry_without_auth_or_build(
    registry: Registry, tmp_path: Path
) -> None:
    assets = tmp_path / "site"
    build_foundation(ROOT, assets)

    def forbidden(*args: Any) -> Any:
        pytest.fail("public discovery cannot access auth, status or operations")

    app = WebApp(
        assets=assets,
        sessions=forbidden,
        status=forbidden,
        operations=forbidden,
        discovery=reader(registry).read,
    )
    event = {"rawPath": "/games/", "requestContext": {"http": {"method": "GET"}}}
    first = app.handle(event, datetime.now(UTC))
    assert first["statusCode"] == 200
    assert first["headers"]["cache-control"] == "no-store"
    assert first["body"].count('<section class="card">') == 4
    new_id = registry.add(87, game_package.load()[2])
    new = app.handle(event, datetime.now(UTC))
    assert "World 87" in new["body"] and new_id not in new["body"]
    registry.items[new_id]["display_name"] = '<script>alert("x")</script>'
    safe = app.handle(event, datetime.now(UTC))
    assert "<script>alert" not in safe["body"]
    registry.fail = True
    failed = app.handle(event, datetime.now(UTC))
    assert failed["statusCode"] == 503
    assert "再読み込み" in failed["body"]
    assert '<section class="card">' not in failed["body"]
    assert "private" not in failed["body"]


def test_execution_revalidates_registry_after_suggestion(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wishicraft import discord_interactions as boundary
    from wishicraft.game_creation import registry_ids
    from wishicraft.runtime_catalog import RuntimeCatalog

    game = choices(reader(registry).read(), "start", "")[0]["value"]
    monkeypatch.setattr(
        boundary, "configured_catalog", lambda: RuntimeCatalog(registry_ids(registry, "games", ()))
    )
    payload: Any = command_payload("start")
    payload["data"]["options"][0]["options"] = [{"name": "game", "type": 3, "value": game}]
    key = SigningKey.generate()
    assert (
        boundary.parse_and_authorize(
            json.dumps(payload).encode(), config=configuration(key)
        ).target_game_id
        == game
    )
    registry.ids.remove(game)
    with pytest.raises(boundary.MalformedInteraction):
        boundary.parse_and_authorize(json.dumps(payload).encode(), config=configuration(key))


def test_registration_guard_preserves_permissions_and_rejects_other_changes() -> None:
    from wishicraft.discovery_operator import canonical, update_body

    old = extend(
        declaration(ROOT, now=datetime.now(UTC))["discord_commands"], ("game-vanilla-secondary",)
    )
    old[0].update(id="123", default_member_permissions="8", dm_permission=False)
    body = update_body(old, canonical(ROOT))
    assert set(body) == {"options"}
    assert old[0]["default_member_permissions"] == "8"
    old[0]["options"][0]["description"] = "unreviewed"
    with pytest.raises(ValueError):
        update_body(old, canonical(ROOT))


def test_legacy_and_created_games_share_record_authority(registry: Registry) -> None:
    legacy = ("game-vanilla-main", "game-vanilla-secondary")
    package = game_package.load()[0]
    for index, game_id in enumerate(legacy):
        registry.items[game_id] = {
            "game_id": game_id,
            "display_name": f"Legacy {index}",
            "lifecycle_state": "ACTIVE",
            "materialization_state": "MATERIALIZED",
            "package": {k: package[k] for k in ("package_id", "package_version")},
        }
    discovery = Discovery(registry, "games", legacy, {legacy[1]: POLICY})
    games = discovery.read()
    assert len(games) == 6
    assert len(choices(games, "start", "")) == 6
    assert len(choices(games, "reset", "")) == 2
    del registry.items[legacy[0]]
    registry.items[legacy[1]]["lifecycle_state"] = "ARCHIVED"
    assert len(discovery.read()) == 4
