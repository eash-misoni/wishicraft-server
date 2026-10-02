from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_provenance import NOW, record
from tests.unit.test_restore import evidence
from tests.unit.test_web_foundation import POLICY, ROOT, event, session
from web.foundation import build_foundation
from wishicraft.backup_recovery import shared_tags
from wishicraft.system_state import _to_attribute
from wishicraft.web_app import WebApp
from wishicraft.web_operations import WebRejected, game_key
from wishicraft.web_restore_candidates import PAGE_LIMIT, Candidates, encode_key


def wire(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _to_attribute(value) for key, value in item.items()}


class Dynamo:
    def __init__(self, item: dict[str, Any], reverse: dict[str, Any]) -> None:
        self.items = {item["provenance_key"]: item, reverse["provenance_key"]: reverse}
        self.page: dict[str, Any] = {"Items": [wire(item)]}
        self.calls: list[dict[str, Any]] = []

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        assert kwargs["Limit"] == PAGE_LIMIT
        return self.page

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        item = self.items.get(kwargs["Key"]["provenance_key"]["S"])
        return {"Item": wire(item)} if item else {}


def reader(db: Dynamo) -> Candidates:
    return Candidates(
        db, "backups", project="wishicraft", stage="dev", owner=record().verified_owner_id
    )


def test_shared_snapshot_games_are_historical_and_response_is_allowlisted() -> None:
    _, item, reverse, description = evidence()
    db = Dynamo(item, reverse)
    result = reader(db).listing(None, NOW)
    candidate = result["items"][0]
    assert {g["key"] for g in candidate["games"]} == {game_key(g) for g in description["games"]}
    assert all(g["generation"] == 1 for g in candidate["games"])
    assert candidate["coverage"] == "shared_volume"
    assert candidate["restorability"] == candidate["snapshot_presence"] == "unknown"
    assert candidate["acquired_at"] == "2026-09-08T01:02:03.000000Z"
    assert reader(db).detail(candidate["key"])["candidate"] == candidate
    serialized = json.dumps(result)
    for private in (
        "recovery_json",
        "runtime_env",
        "metadata",
        "source_volume_id",
        "snapshot_id",
        "verified_owner_id",
        "operation_id",
        "seed",
        "data_source",
    ):
        assert private not in serialized
    assert all(c["TableName"] == "backups" and c["ConsistentRead"] for c in db.calls)


def test_legacy_missing_generation_and_name_never_use_current_game() -> None:
    original = record()
    result = reader(Dynamo(original.snapshot_item(), original.operation_item())).listing(None, NOW)
    candidate = result["items"][0]
    assert candidate["coverage"] == "legacy_unknown"
    assert candidate["games"] == [
        {
            "key": game_key(original.game_id),
            "name": None,
            "generation": None,
            "materialization": "unknown",
        }
    ]


def test_shared_missing_generation_unmaterialized_and_unsafe_name() -> None:
    _, _, _, description = evidence()
    game = description["games"][record().game_id]
    game["world"].pop("generation")
    game["materialization_state"] = "UNMATERIALIZED"
    game["display_name"] = "<script>unsafe</script>"
    text = json.dumps(description)
    p = replace(
        record(),
        schema_version=2,
        recovery_json=text,
        metadata=shared_tags(record().metadata, text),
    )
    candidate = reader(Dynamo(p.snapshot_item(), p.operation_item())).listing(None, NOW)["items"][0]
    historical = next(g for g in candidate["games"] if g["key"] == game_key(p.game_id))
    assert historical == {
        "key": game_key(p.game_id),
        "name": None,
        "generation": None,
        "materialization": "UNMATERIALIZED",
    }


def test_empty_evaluated_page_can_have_continuation_and_is_one_scan() -> None:
    p = record()
    db = Dynamo(p.snapshot_item(), p.operation_item())
    key = "OPERATION#" + p.operation_id
    db.page = {"Items": [], "LastEvaluatedKey": {"provenance_key": {"S": key}}}
    page = reader(db).listing(None, NOW)
    assert page["items"] == [] and page["next_cursor"] == encode_key(key)
    assert len(db.calls) == 1
    db.page = {"Items": []}
    last = reader(db).listing(page["next_cursor"], NOW)
    assert last["next_cursor"] is None
    assert db.calls[-1]["ExclusiveStartKey"] == {"provenance_key": {"S": key}}
    assert last["order"] == "page_time_desc"


@pytest.mark.parametrize(
    "token", ["", "!", "x" * 301, encode_key("arbitrary"), encode_key("SNAPSHOT#snap-bad")]
)
def test_invalid_detail_key_performs_no_read(token: str) -> None:
    p = record()
    db = Dynamo(p.snapshot_item(), p.operation_item())
    with pytest.raises(WebRejected):
        reader(db).detail(token)
    assert db.calls == []


@pytest.mark.parametrize(
    "broken", ["fingerprint", "digest", "reverse", "scope", "malformed", "boolean_version"]
)
def test_bad_evidence_does_not_become_a_candidate(broken: str) -> None:
    _, item, reverse, _ = evidence()
    db = Dynamo(item, reverse)
    if broken == "fingerprint":
        item["metadata_fingerprint"] = "wrong"
    elif broken == "digest":
        item["recovery_digest"] = "wrong"
    elif broken == "reverse":
        db.items.pop(reverse["provenance_key"])
    elif broken == "scope":
        item["stage"] = "prod"
    elif broken == "boolean_version":
        item["schema_version"] = True
    else:
        item["snapshot_start_time"] = "not-time"
    db.page = {"Items": [wire(item)]}
    with pytest.raises((ValueError, KeyError)):
        reader(db).listing(None, NOW)


def test_page_sort_is_local_and_pagination_is_bounded() -> None:
    _, item, reverse, _ = evidence()
    db = Dynamo(item, reverse)
    later = copy.deepcopy(item)
    later["snapshot_start_time"] = "2026-09-09T01:02:03Z"
    later["snapshot_id"] = "snap-00000000"
    later["provenance_key"] = "SNAPSHOT#snap-00000000"
    later_reverse = {**reverse, "snapshot_id": later["snapshot_id"]}
    # The old uniqueness entry belongs to its original snapshot; use a separate Operation.
    later["operation_id"] = "op-later"
    later["metadata"]["WishicraftOperationId"] = "op-later"
    import hashlib

    later["metadata_fingerprint"] = hashlib.sha256(
        json.dumps(
            later["metadata"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    later_reverse.update(operation_id="op-later", provenance_key="OPERATION#op-later")
    db.items[later_reverse["provenance_key"]] = later_reverse
    db.page = {"Items": [wire(item), wire(later)]}
    page = reader(db).listing(None, NOW)
    assert [c["acquired_at"] for c in page["items"]] == [
        "2026-09-09T01:02:03.000000Z",
        "2026-09-08T01:02:03.000000Z",
    ]
    db.page = {"Items": [wire(item)] * (PAGE_LIMIT + 1)}
    with pytest.raises(ValueError):
        reader(db).listing(None, NOW)
    key = encode_key(item["provenance_key"])
    db.page = {"Items": [], "LastEvaluatedKey": {"provenance_key": {"S": item["provenance_key"]}}}
    with pytest.raises(ValueError):
        reader(db).listing(key, NOW)


@pytest.fixture
def boundary(tmp_path: Path) -> Any:
    _, item, reverse, _ = evidence()
    db = Dynamo(item, reverse)
    auth = session()
    site = tmp_path / "site"
    build_foundation(ROOT, site)
    app = WebApp(
        assets=site, sessions=lambda: auth, status=lambda now: {}, candidates=lambda: reader(db)
    )
    return app, auth, db


def login(auth: Any, roles: list[str]) -> str:
    return str(
        auth.create(
            int(NOW.timestamp()),
            {
                "user_id": "9",
                "display_name": "Local viewer",
                "guild_id": POLICY.guild_id,
                "roles": roles,
            },
        )
    ).split(";")[0]


@pytest.mark.parametrize(
    "path",
    [
        "/api/restore-candidates",
        "/api/restore-candidates/" + encode_key("SNAPSHOT#snap-0123456789abcdef0"),
    ],
)
def test_authorization_is_server_side_for_list_and_detail(boundary: Any, path: str) -> None:
    app, auth, db = boundary
    assert app.handle(event(path), NOW)["statusCode"] == 401
    assert app.handle(event(path, jar=login(auth, [])), NOW)["statusCode"] == 401
    assert db.calls == []
    for roles in ([POLICY.player_role_id], [POLICY.admin_role_id]):
        result = app.handle(event(path, jar=login(auth, roles)), NOW)
        assert result["statusCode"] == 200
        assert result["headers"]["cache-control"] == "no-store"


def test_expired_session_and_non_get_are_rejected_without_read(boundary: Any) -> None:
    app, auth, db = boundary
    jar = login(auth, [POLICY.player_role_id])
    assert (
        app.handle(event("/api/restore-candidates", jar=jar, method="POST"), NOW)["statusCode"]
        == 405
    )
    signed = jar.split("=", 1)[1]
    auth.store.records[auth.verify(signed, "session-")]["expires_at"] = int(NOW.timestamp())
    assert app.handle(event("/api/restore-candidates", jar=jar), NOW)["statusCode"] == 401
    assert db.calls == []


def test_read_failure_not_found_and_bad_queries(boundary: Any) -> None:
    app, auth, db = boundary
    jar = login(auth, [POLICY.player_role_id])
    for query in ("cursor=", "cursor=a&cursor=b", "other=1", "cursor=" + "a" * 513):
        assert (
            app.handle(event("/api/restore-candidates", jar=jar, query=query), NOW)["statusCode"]
            == 400
        )
    db.page = {"Items": "invalid backend response"}
    result = app.handle(event("/api/restore-candidates", jar=jar), NOW)
    assert result["statusCode"] == 503 and "invalid backend" not in result["body"]
    assert "items" not in json.loads(result["body"])
    missing = encode_key("SNAPSHOT#snap-00000000")
    assert (
        app.handle(event("/api/restore-candidates/" + missing, jar=jar), NOW)["statusCode"] == 404
    )


def test_invalid_backend_cursor_is_service_failure(boundary: Any) -> None:
    app, auth, db = boundary
    db.page = {"Items": [], "LastEvaluatedKey": {"provenance_key": {"S": "bad-key"}}}
    result = app.handle(
        event("/api/restore-candidates", jar=login(auth, [POLICY.player_role_id])), NOW
    )
    assert result["statusCode"] == 503
