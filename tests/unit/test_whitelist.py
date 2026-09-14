"""Real session -> Web -> Admission -> atomic policy/Operation serialization."""

from __future__ import annotations

import copy
import json
import urllib.request
import uuid
from typing import Any

import pytest

from tests.unit.test_game_creation import creation  # noqa: F401
from tests.unit.test_web_operations import NOW, boundary, event, login, post  # noqa: F401
from wishicraft import whitelist
from wishicraft.artifacts import whitelist_policy as model
from wishicraft.web_operations import game_key

PLAYER = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def access(boundary: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    monkeypatch.setenv("WHITELIST_MANAGEMENT", "1")
    monkeypatch.setattr(whitelist, "resolve", lambda name: (PLAYER, name))
    db = boundary[2].db
    db.records["games", model.COMMON] = {
        "game_id": {"S": model.COMMON},
        "policy_json": {"S": model.encoded(model.empty())},
    }
    return boundary


def payload(
    action: str = "add",
    player: str | None = "FixtureOne",
    game: str | None = None,
    revision: int = 0,
) -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "type": "WHITELIST",
        "game": game,
        "confirm": True,
        "whitelist": {"action": action, "player": player, "revision": revision},
    }


def test_common_specific_union_noop_retry(access: Any) -> None:
    app, sessions, backend, launches, calls = access
    original = copy.deepcopy(backend.db.records)
    jar = login(sessions)
    request = payload()
    assert post(access, jar, request)["statusCode"] == 202
    assert post(access, login(sessions), request)["statusCode"] == 200
    assert backend.db.transactions == 1
    assert model.read(backend.db, "games", None)["members"] == {PLAYER: "FixtureOne"}
    changed = copy.deepcopy(request)
    changed["whitelist"]["player"] = "FixtureTwo"
    assert post(access, jar, changed)["statusCode"] == 409
    game = backend.catalog[1]
    assert post(access, jar, payload(game=game_key(game)))["statusCode"] == 202
    caps = json.loads(app.handle(event(jar, path="/api/capabilities", method="GET"), NOW)["body"])
    entries = caps["whitelist"]["games"][game_key(game)]["members"]
    assert len(entries) == 1 and entries[0]["common"] and entries[0]["specific"]
    assert PLAYER not in json.dumps(caps)
    assert (
        post(access, jar, payload("remove", model.player_key(PLAYER), game_key(game), 1))[
            "statusCode"
        ]
        == 202
    )
    assert model.effective(
        model.read(backend.db, "games", None), model.read(backend.db, "games", game)
    ) == {PLAYER: "FixtureOne"}
    before = model.read(backend.db, "games", None)
    assert post(access, jar, payload("save", None, revision=1))["statusCode"] == 202
    assert model.read(backend.db, "games", None) == before
    assert (
        post(access, jar, payload("remove", model.player_key(PLAYER), revision=1))["statusCode"]
        == 202
    )
    assert model.read(backend.db, "games", None)["members"] == {}
    assert not launches
    for key, value in original.items():
        if key != ("games", model.COMMON):
            assert backend.db.records[key] == value


@pytest.mark.parametrize(
    "kind", ["START", "STOP", "SWITCH", "RESET", "BACKUP", "RETENTION", "UNKNOWN"]
)
def test_freeze_no_policy_mutation(access: Any, kind: str) -> None:
    _, sessions, backend, launches, _ = access
    backend.db.records["locks", "minecraft-control"] = {"operation_type": {"S": kind}}
    before = copy.deepcopy(backend.db.records)
    assert post(access, login(sessions), payload())["statusCode"] == 409
    assert backend.db.records == before and not launches


@pytest.mark.parametrize(
    "name", ["", "ab", "x" * 17, "../a", "<script>", "name\n", "évil", "a;id", "a b"]
)
def test_invalid_identity_rejected_before_admission(access: Any, name: str) -> None:
    assert post(access, login(access[1]), payload(player=name))["statusCode"] == 400
    assert not access[4]


def test_failed_resolution_does_not_mutate(access: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(name: str) -> tuple[str, str]:
        raise ValueError("private provider response")

    monkeypatch.setattr(whitelist, "resolve", failed)
    response = post(access, login(access[1]), payload())
    assert response["statusCode"] == 400 and "private" not in response["body"]
    assert access[2].db.transactions == 0


def test_missing_migration_fails_closed(access: Any) -> None:
    del access[2].db.records["games", model.COMMON]
    assert post(access, login(access[1]), payload())["statusCode"] == 400
    assert access[2].db.transactions == 0


def test_stale_revision_and_invalid_game(access: Any) -> None:
    jar = login(access[1])
    assert post(access, jar, payload(revision=2))["statusCode"] == 409
    assert post(access, jar, payload(game="f" * 24))["statusCode"] == 400
    assert access[2].db.transactions == 0


def test_authorization_csrf_origin_spoof_and_lost_reply(access: Any) -> None:
    app, sessions, backend, launches, calls = access
    assert post(access, login(sessions, roles=["3"]), payload())["statusCode"] == 403
    assert app.handle(event(value=payload()), NOW)["statusCode"] == 401
    jar = login(sessions)
    for kwargs in (
        {},
        {"csrf": "invalid"},
        {"csrf": sessions.csrf(jar.split("=", 1)[1]), "origin": "https://foreign.invalid"},
    ):
        assert app.handle(event(jar, payload(), **kwargs), NOW)["statusCode"] == 403
    forged = payload()
    forged["roles"] = ["4"]
    assert post(access, jar, forged)["statusCode"] == 400
    old = event(jar, payload())
    old["requestContext"]["domainName"] = "old.execute-api.ap-northeast-1.amazonaws.com"
    assert app.handle(old, NOW)["statusCode"] == 403
    invoke = backend.lambda_api.invoke

    def lose(**kwargs: Any) -> Any:
        invoke(**kwargs)
        raise TimeoutError("lost response")

    backend.lambda_api.invoke = lose
    request = payload()
    assert post(access, jar, request)["statusCode"] == 503
    assert post(access, login(sessions), request)["statusCode"] == 200
    assert backend.db.transactions == 1 and not launches
    # A different actor cannot use the original actor's durable request record.
    backend.lambda_api.invoke = invoke
    request["whitelist"]["revision"] = 1
    assert post(access, login(sessions, user="8"), request)["statusCode"] == 202
    assert backend.db.transactions == 2


@pytest.mark.parametrize(
    "mode", ["ok", "unknown", "timeout", "oversize", "wrong_name", "wrong_uuid"]
)
def test_official_profile_resolution(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    class Response:
        status = 204 if mode == "unknown" else 200

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, limit: int) -> bytes:
            assert limit == 4097
            if mode == "oversize":
                return b"x" * 4097
            return json.dumps(
                {
                    "id": "bad" if mode == "wrong_uuid" else PLAYER.replace("-", ""),
                    "name": "Different" if mode == "wrong_name" else "FixtureOne",
                }
            ).encode()

    class Opener:
        def open(self, request: Any, timeout: int) -> Any:
            assert request.full_url == "https://api.mojang.com/users/profiles/minecraft/fixtureone"
            assert timeout == 3
            if mode == "timeout":
                raise TimeoutError("private network detail")
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    if mode == "ok":
        assert whitelist.resolve("fixtureone") == (PLAYER, "FixtureOne")
    else:
        with pytest.raises(ValueError, match="^profile unavailable$"):
            whitelist.resolve("fixtureone")


def test_migration_exact_union_and_ambiguity() -> None:
    from wishicraft.whitelist_migration import plan

    source = {
        "game-a": [{"uuid": PLAYER, "name": "FixtureOne"}],
        "game-b": [{"uuid": PLAYER, "name": "FixtureOne"}, {"uuid": SECOND, "name": "FixtureTwo"}],
    }
    result = plan(source)
    assert result["common_count"] == 1
    assert result["proof"]["game-a"]["specific_count"] == 0
    assert result["proof"]["game-b"]["specific_count"] == 1
    for game, entries in source.items():
        assert model.effective(result["policy"]["common"], result["policy"]["games"][game]) == {
            entry["uuid"]: entry["name"] for entry in entries
        }
    source["game-a"][0]["name"] = "Renamed"
    with pytest.raises(ValueError, match="requires review"):
        plan(source)


def test_projection_replaces_ingame_changes_and_rejects_redirection(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setattr(model, "UID", os.getuid())
    monkeypatch.setattr(model, "GID", os.getgid())
    source = tmp_path / "server"
    source.mkdir()
    (source / "server.properties").write_text(
        "online-mode=true\nwhite-list=true\nenforce-whitelist=true\n"
    )
    path = source / "whitelist.json"
    path.write_text("[]")
    path.chmod(0o640)
    target = {"data_source": str(source)}
    common = {"revision": 1, "members": {PLAYER: "FixtureOne"}}
    expected = [{"uuid": PLAYER, "name": "FixtureOne"}]
    model.project(target, common, model.empty(), None)
    assert json.loads(path.read_text()) == expected
    # Graceful stop and crash leave the file; next inactive convergence ignores local changes.
    for changed in ([], [{"uuid": SECOND, "name": "FixtureTwo"}]):
        path.write_text(json.dumps(changed))
        model.project(target, common, model.empty(), None)
        assert json.loads(path.read_text()) == expected
    other = tmp_path / "other"
    other.write_text("unchanged")
    path.unlink()
    path.symlink_to(other)
    with pytest.raises(ValueError, match="WHITELIST_FILE_IDENTITY"):
        model.project(target, common, model.empty(), None)
    assert other.read_text() == "unchanged"


def test_host_upgrade_exact_predecessor_and_migration_transaction(tmp_path: Any) -> None:
    from pathlib import Path

    from wishicraft.whitelist_migration import host_bundle, plan, transaction

    root = Path(__file__).resolve().parents[2]
    evidence = json.loads(
        (root / "docs/evidence/minimal_game_creation_production_2026-09-13.json").read_text()
    )
    receipt = evidence["host_upgrade"]["plan"]["receipt_predecessor"]
    bundle = host_bundle(root, tmp_path / "bundle", receipt)
    assert len(bundle["files"]) == 3
    assert bundle["receipt_predecessor"] == receipt
    assert bundle["files"][2]["predecessor"] is None
    assert (
        bundle["files"][0]["predecessor"]
        == "536d153ab39a449e86f1805542eb5138c37f7c780d8469db42108ed9b556682e"
    )
    assert (
        bundle["files"][1]["predecessor"]
        == "afa1ba874bd2ca96979524ddf7929894a28db6d4d0025400b193f565db26cd9b"
    )
    planned = plan({"game-a": [], "game-b": []})
    records = {
        game: {"game_id": {"S": game}, "version": {"N": "1"}, "world": {"M": {}}}
        for game in ("game-a", "game-b")
    }
    result = transaction(
        planned, records, games_table="games", locks_table="locks", lock_name="runtime"
    )
    assert len(result["TransactItems"]) == 7
    assert all(
        action["Put"]["ConditionExpression"] == "attribute_not_exists(game_id)"
        for action in result["TransactItems"]
        if "Put" in action
    )


def test_unmaterialized_dynamic_game_inherits_and_edits(
    access: Any,
    creation: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_game_creation import payload as create_payload
    from wishicraft.game_creation import REGISTRY_KEY

    app, sessions, backend, launches, _ = access
    jar = login(sessions)
    assert post(access, jar, payload())["statusCode"] == 202
    assert post(creation, jar, create_payload())["statusCode"] == 202
    game = backend.db.records["games", REGISTRY_KEY]["registered_ids"]["SS"][0]
    before = copy.deepcopy(backend.db.records["games", game])
    assert before["materialization_state"] == {"S": "UNMATERIALIZED"}
    assert model.effective(
        model.read(backend.db, "games", None), model.read(backend.db, "games", game)
    ) == {PLAYER: "FixtureOne"}
    monkeypatch.setattr(whitelist, "resolve", lambda name: (SECOND, "FixtureTwo"))
    assert post(access, jar, payload(player="FixtureTwo", game=game_key(game)))["statusCode"] == 202
    assert backend.db.records["games", game] == before and not launches
    caps = json.loads(app.handle(event(jar, path="/api/capabilities", method="GET"), NOW)["body"])
    assert len(caps["games"]) == 3
    assert len(caps["whitelist"]["games"][game_key(game)]["members"]) == 2


def test_concurrent_duplicate_has_one_policy_transaction(access: Any) -> None:
    from concurrent.futures import ThreadPoolExecutor

    jar, request = login(access[1]), payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: post(access, jar, request), range(2)))
    assert {reply["statusCode"] for reply in replies} <= {200, 202}
    assert access[2].db.transactions == 1
