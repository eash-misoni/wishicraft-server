"""Real HTTP, DynamoDB serialization, OAuth adapter and synthesized IAM boundaries."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from web.foundation import build_foundation
from web.local import FakeOAuth, MemoryStore, fixture
from wishicraft.system_state import _to_attribute
from wishicraft.web_app import AuthApp, WebApp
from wishicraft.web_auth import (
    SESSION_COOKIE,
    AuthRejected,
    DiscordOAuth,
    Policy,
    Sessions,
)
from wishicraft.web_lambda import DynamoSessions
from wishicraft.web_status import StatusReader, project

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 13, tzinfo=UTC)
POLICY = Policy("1", "2", "3", "4")


def event(
    path: str,
    *,
    jar: str = "",
    method: str = "GET",
    query: str = "",
    origin: str = "https://web.example",
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "rawQueryString": query,
        "cookies": [jar],
        "headers": {"origin": origin},
        "requestContext": {"http": {"method": method}},
    }


def session() -> Sessions:
    return Sessions(MemoryStore(), secrets.token_bytes(32), POLICY)


def test_state_signature_replay_expiration_and_logout() -> None:
    auth = session()
    state, header = auth.begin(10)
    signed = header.split(";")[0].split("=", 1)[1]
    with pytest.raises(AuthRejected):
        auth.consume("wrong", signed, 11)
    auth.consume(state, signed, 11)
    with pytest.raises(AuthRejected):
        auth.consume(state, signed, 11)
    state, header = auth.begin(10)
    with pytest.raises(AuthRejected):
        auth.consume(state, header.split(";")[0].split("=", 1)[1], 310)
    header = auth.create(10)
    assert all(
        flag in header for flag in ["Secure", "HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=900"]
    )
    signed = header.split(";")[0].split("=", 1)[1]
    auth.authenticate(signed, 11)
    with pytest.raises(AuthRejected):
        auth.authenticate(signed[:-1] + ("1" if signed[-1] != "1" else "2"), 11)
    with pytest.raises(AuthRejected):
        auth.authenticate(signed, 910)
    auth.logout(signed)
    with pytest.raises(AuthRejected):
        auth.authenticate(signed, 11)


@pytest.mark.parametrize(
    "roles,allowed", [(["3"], True), (["4"], True), ([], False), (["5"], False), ("3", False)]
)
def test_shared_policy(roles: object, allowed: bool) -> None:
    member = {"user": {"id": "9"}, "roles": roles}
    if allowed:
        POLICY.authorize({"id": "9"}, member)
    else:
        with pytest.raises(AuthRejected):
            POLICY.authorize({"id": "9"}, member)
    with pytest.raises(AuthRejected):
        POLICY.authorize({"id": "8"}, member)
    with pytest.raises(AuthRejected):
        POLICY.authorize({"id": "9"}, {**member, "pending": True})


def test_oauth_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    token = secrets.token_urlsafe(32)
    oauth = DiscordOAuth(POLICY, secrets.token_urlsafe(32), "https://web.example/auth/callback")

    class Reply:
        def __init__(self, value: object) -> None:
            self.value = value

        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, maximum: int) -> bytes:
            return b"" if self.value is None else json.dumps(self.value).encode()

    class Opener:
        def open(self, request: Any, **kwargs: Any) -> Reply:
            calls.append(request)
            assert request.get_header("User-agent") == (
                "DiscordBot (https://github.com/eash-misoni/wishicraft-server, 0.1.0)"
            )
            assert kwargs["timeout"] == 5
            if request.full_url.endswith("/token"):
                form = parse_qs(request.data.decode())
                assert form["redirect_uri"] == [oauth.redirect_uri]
                assert form["grant_type"] == ["authorization_code"]
                return Reply(
                    {
                        "access_token": token,
                        "token_type": "Bearer",
                        "scope": "identify guilds.members.read",
                    }
                )
            if request.full_url.endswith("/member"):
                assert "/guilds/2/member" in request.full_url
                assert request.headers["Authorization"] == "Bearer " + token
                return Reply({"user": {"id": "9"}, "roles": ["3"]})
            return Reply(None if request.full_url.endswith("/revoke") else {"id": "9"})

    monkeypatch.setattr("wishicraft.web_auth.build_opener", lambda *args: Opener())
    oauth.exchange("code")
    assert calls[-1].full_url.endswith("/token/revoke")
    assert len(calls) == 4
    url = parse_qs(urlsplit(oauth.authorization_url("nonce")).query)
    assert url["scope"] == ["identify guilds.members.read"]

    class Broken:
        def open(self, *args: Any, **kwargs: Any) -> None:
            raise OSError(token)

    monkeypatch.setattr("wishicraft.web_auth.build_opener", lambda *args: Broken())
    with pytest.raises(AuthRejected) as error:
        oauth.exchange("code")
    assert token not in str(error.value)


def test_http_routes_and_callback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = tmp_path / "site"
    build_foundation(ROOT, site)
    auth = session()
    oauth = FakeOAuth(POLICY, "", "https://web.example/auth/callback")
    callback = AuthApp(auth, oauth, "https://web.example")
    app = WebApp(assets=site, sessions=lambda: auth, status=lambda now: fixture(now, "players"))
    assert app.handle(event("/"), NOW)["statusCode"] == 200
    assert "Discordでログイン" in app.handle(event("/manage/"), NOW)["body"]
    assert "Discordでログイン" in app.handle(event("/manage/index.html"), NOW)["body"]
    assert app.handle(event("/api/status"), NOW)["statusCode"] == 401
    for path in ["/routes.json", "/_headers", "/../manage/index.html", "/config/stages/dev.yaml"]:
        assert app.handle(event(path), NOW)["statusCode"] == 404
    start = callback.handle(event("/auth/login"), NOW)
    state_cookie = start["cookies"][0].split(";")[0]
    query = urlsplit(start["headers"]["location"]).query
    denied = callback.handle(event("/auth/callback", query=query), NOW)
    assert denied["statusCode"] == 403
    done = callback.handle(event("/auth/callback", jar=state_cookie, query=query), NOW)
    assert done["statusCode"] == 303
    assert (
        callback.handle(event("/auth/callback", jar=state_cookie, query=query), NOW)["statusCode"]
        == 403
    )
    jar = done["cookies"][0].split(";")[0]
    assert SESSION_COOKIE in jar
    page = app.handle(event("/manage/", jar=jar), NOW)
    assert "現在の状態" in page["body"]
    result = app.handle(event("/api/status", jar=jar), NOW)
    assert json.loads(result["body"])["players"]["count"] == 3
    assert result["headers"]["cache-control"] == "no-store"
    assert "access_token" not in result["body"] + page["body"]
    assert (
        callback.handle(
            event("/auth/logout", jar=jar, method="POST", origin="https://evil.example"), NOW
        )["statusCode"]
        == 403
    )
    assert callback.handle(event("/auth/logout", jar=jar, method="POST"), NOW)["statusCode"] == 303
    assert app.handle(event("/api/status", jar=jar), NOW)["statusCode"] == 401
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    "scenario,kind,count",
    [
        ("stopped", "not_expected", None),
        ("running", "known", 0),
        ("players", "known", 3),
        ("stale", "unknown", None),
        ("unknown", "unknown", None),
        ("transition", "unknown", None),
    ],
)
def test_fixture_semantics(scenario: str, kind: str, count: int | None) -> None:
    result = json.loads(json.dumps(fixture(NOW, scenario)))
    assert result["players"]["state"] == kind
    assert result["players"]["count"] == count
    if scenario == "transition":
        assert result["current_operation"]["type"] == "SWITCH"
        assert result["health"] == "UNKNOWN"


class Dynamo:
    def __init__(self, state: dict[str, Any]) -> None:
        self.items = {"system": state, "heartbeat": {}, "games": {"display_name": "Third Game"}}
        self.calls: list[dict[str, Any]] = []
        self.fail: set[str] = set()

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        table = kwargs["TableName"]
        if table in self.fail:
            raise OSError("arn:aws:secret:raw-error")
        return {"Item": {k: _to_attribute(v) for k, v in self.items.get(table, {}).items()}}


def state() -> dict[str, Any]:
    return {
        "desired_state": "STOPPED",
        "desired_game_id": "game-third",
        "observed_at": NOW.isoformat(),
        "health": "HEALTHY",
        "discrepancies": [],
        "observation_errors": [],
        "observation": {"ec2_state": "stopped", "host_runtime_state": "not-running"},
    }


def test_dynamo_json_projection_partial_and_duplicates() -> None:
    db = Dynamo(state())
    reader = StatusReader(
        db, {k: k for k in ["system", "heartbeat", "games", "operation"]}, "system-id", 600
    )
    result = reader.read(NOW)
    assert result == reader.read(NOW)
    assert result["selected_game"]["name"] == "Third Game"
    assert result["health"] == "HEALTHY"
    assert all(call["ConsistentRead"] for call in db.calls)
    assert "game-third" not in json.dumps(result)
    db.fail.add("games")
    result = reader.read(NOW)
    assert result["quality"] == "partial" and result["health"] == "UNKNOWN"
    assert "arn:" not in json.dumps(result)
    db.fail.add("system")
    assert reader.read(NOW)["players"]["state"] == "unknown"


def test_stale_future_terminal_and_mismatch() -> None:
    saved = state()
    for instant in [NOW + timedelta(minutes=11), NOW - timedelta(seconds=1)]:
        result = project(saved, {}, {}, None, set(), instant)
        assert result["health"] == "UNKNOWN"
        assert result["players"]["state"] == "unknown"
    saved["current_operation_id"] = "op-private"
    saved["observation"]["observed_active_game_id"] = "game-other"
    result = project(
        saved,
        {},
        {},
        {
            "operation_type": "STOP",
            "status": "SUCCEEDED",
            "current_step": "arn:secret",
            "updated_at": NOW.isoformat(),
        },
        set(),
        NOW,
    )
    assert result["current_operation"]["terminal"] is True
    assert result["game_mismatch"] is True
    assert "arn:secret" not in json.dumps(result)
    assert result["players"]["state"] == "unknown"


def test_dynamo_session_atomic_delete() -> None:
    class Api:
        def delete_item(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["ReturnValues"] == "ALL_OLD"
            return {"Attributes": {"expires_at": {"N": "99"}}}

    assert DynamoSessions(Api(), "sessions").delete("state-value") == {"expires_at": 99}


def test_synthesized_environment_initializes_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="web", web_domain_phase="legacy")
    stack = app.node.find_child("WishicraftWebStack-dev")
    template = Template.from_stack(stack)  # type: ignore[arg-type]
    document = template.to_json()
    resources = document["Resources"]
    functions = [
        v["Properties"] for v in resources.values() if v["Type"] == "AWS::Lambda::Function"
    ]
    assert len(functions) == 2
    web = next(f for f in functions if f["Handler"].endswith(".handler"))
    env = web["Environment"]["Variables"]
    for key, value in env.items():
        monkeypatch.setenv(key, value if isinstance(value, str) else "sessions")
    from wishicraft import web_lambda

    db = Dynamo(state())
    monkeypatch.setattr(web_lambda, "client", lambda name: db)
    reader = web_lambda.status_reader()
    assert reader.system_id == "wishicraft-main"
    assert reader.tables["system"] == "wc-dev-system-state"
    assert web_lambda.policy().guild_id == env["WEB_GUILD_ID"]
    policies = [
        v["Properties"]["PolicyDocument"]["Statement"]
        for v in resources.values()
        if v["Type"] == "AWS::IAM::Policy"
    ]
    statements = [s for group in policies for s in group]
    actions = {
        a
        for s in statements
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    }
    assert not actions.intersection(
        {
            "dynamodb:Scan",
            "dynamodb:UpdateItem",
            "lambda:InvokeFunction",
            "ssm:SendCommand",
            "states:StartExecution",
        }
    )
    assert "WEB_OAUTH_PARAMETER" not in env
    assert not any(
        v["Type"] in {"AWS::S3::Bucket", "AWS::CloudFront::Distribution", "AWS::Route53::RecordSet"}
        for v in resources.values()
    )
    assert len([v for v in resources.values() if v["Type"] == "AWS::DynamoDB::Table"]) == 1
    ephemeral = next(v for v in resources.values() if v["Type"] == "AWS::DynamoDB::Table")
    assert ephemeral["DeletionPolicy"] == "Delete"
    assert ephemeral["UpdateReplacePolicy"] == "Delete"
    assert ephemeral["Properties"]["TimeToLiveSpecification"] == {
        "AttributeName": "expires_at",
        "Enabled": True,
    }
    assert all(
        v["DeletionPolicy"] == "Retain"
        for v in resources.values()
        if v["Type"] == "AWS::Logs::LogGroup"
    )


def test_deployed_handlers_use_real_cookie_store_and_packaged_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.stacks.web_foundation_stack import bundle
    from wishicraft import web_lambda

    output = bundle(ROOT)
    assert not (output / "web/local.py").exists()
    assert not (output / "site/config").exists()
    key = secrets.token_urlsafe(32)
    records: dict[str, dict[str, Any]] = {}

    class Api:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["WithDecryption"] is True
            return {"Parameter": {"Value": key}}

        def put_item(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["TableName"] == "sessions"
            item = kwargs["Item"]
            records[item["id"]["S"]] = item
            return {}

        def get_item(self, **kwargs: Any) -> dict[str, Any]:
            table = kwargs["TableName"]
            if table == "sessions":
                return {"Item": records.get(kwargs["Key"]["id"]["S"])}
            value = state() if table == env["WEB_SYSTEM_TABLE"] else {"display_name": "Third Game"}
            return {"Item": {k: _to_attribute(v) for k, v in value.items()}}

        def delete_item(self, **kwargs: Any) -> dict[str, Any]:
            return {"Attributes": records.pop(kwargs["Key"]["id"]["S"], None)}

    api = Api()
    monkeypatch.setattr(web_lambda, "client", lambda name: api)
    monkeypatch.setattr(web_lambda, "__file__", str(output / "wishicraft/web_lambda.py"))
    monkeypatch.setattr(web_lambda, "utc_now", lambda: NOW)
    app = build_app(ROOT, "dev", phase=8, deployment="web", web_domain_phase="legacy")
    template = Template.from_stack(app.node.find_child("WishicraftWebStack-dev"))  # type: ignore[arg-type]
    env: dict[str, str] = {}
    for resource in template.to_json()["Resources"].values():
        if resource["Type"] == "AWS::Lambda::Function":
            for name, value in resource["Properties"]["Environment"]["Variables"].items():
                env[name] = (
                    value
                    if isinstance(value, str)
                    else ("https://web.example" if name == "WEB_ORIGIN" else "sessions")
                )
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(DiscordOAuth, "exchange", lambda self, code: None)
    web_lambda.web_app.cache_clear()
    try:
        assert web_lambda.handler(event("/"), None)["statusCode"] == 200
        assert web_lambda.handler(event("/api/status"), None)["statusCode"] == 401
        start = web_lambda.auth_handler(event("/auth/login"), None)
        state_value = parse_qs(urlsplit(start["headers"]["location"]).query)["state"][0]
        done = web_lambda.auth_handler(
            event(
                "/auth/callback",
                jar=start["cookies"][0].split(";")[0],
                query=urlencode({"state": state_value, "code": "code"}),
            ),
            None,
        )
        assert done["statusCode"] == 303
        jar = done["cookies"][0].split(";")[0]
        result = web_lambda.handler(event("/api/status", jar=jar), None)
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["players"]["state"] == "not_expected"
        assert key not in json.dumps(result)
        assert (
            web_lambda.auth_handler(event("/auth/logout", jar=jar, method="POST"), None)[
                "statusCode"
            ]
            == 303
        )
        assert web_lambda.handler(event("/api/status", jar=jar), None)["statusCode"] == 401
    finally:
        web_lambda.web_app.cache_clear()


@pytest.mark.parametrize("operation_type", ["START", "STOP", "SWITCH", "RESET"])
def test_all_transitions_hide_old_positive_count(operation_type: str) -> None:
    saved = state()
    saved["current_operation_id"] = "op-private"
    result = project(
        saved,
        {"player_count": 8, "observed_at": NOW.isoformat()},
        {},
        {"operation_type": operation_type, "status": "RUNNING"},
        set(),
        NOW,
    )
    assert result["players"] == {"state": "unknown", "count": None, "at": None}
    assert result["current_operation"]["type"] == operation_type


def test_new_desired_without_new_observation_cannot_claim_fresh_health() -> None:
    saved = state()
    saved["desired_updated_at"] = (NOW + timedelta(seconds=1)).isoformat()
    result = project(saved, {}, {}, None, set(), NOW + timedelta(seconds=2))
    assert result["health"] == "UNKNOWN"
    assert result["players"]["state"] == "unknown"


@pytest.mark.parametrize("failure", ["scope", "member", "role", "revoke"])
def test_oauth_authorization_failure_never_issues_session(failure: str) -> None:
    class OAuth(DiscordOAuth):
        def request(self, path: str, **kwargs: Any) -> dict[str, Any]:
            if path.endswith("/token"):
                return {
                    "access_token": secrets.token_urlsafe(32),
                    "token_type": "Bearer",
                    "scope": "identify" if failure == "scope" else "identify guilds.members.read",
                }
            if path.endswith("/revoke"):
                if failure == "revoke":
                    raise AuthRejected("upstream unavailable")
                return {}
            if path.endswith("/member"):
                if failure == "member":
                    raise AuthRejected("not a member of canonical guild")
                return {"user": {"id": "9"}, "roles": [] if failure == "role" else ["3"]}
            return {"id": "9"}

    sessions = session()
    app = AuthApp(
        sessions, OAuth(POLICY, "", "https://web.example/auth/callback"), "https://web.example"
    )
    state, header = sessions.begin(int(NOW.timestamp()))
    result = app.handle(
        event(
            "/auth/callback",
            jar=header.split(";")[0],
            query=urlencode({"state": state, "code": "code"}),
        ),
        NOW,
    )
    assert result["statusCode"] == 403
    assert not any(value.startswith(SESSION_COOKIE + "=") for value in result["cookies"])
    assert not sessions.store.records  # type: ignore[attr-defined]


def test_concurrent_saved_state_change_is_partial() -> None:
    class Changing(Dynamo):
        def get_item(self, **kwargs: Any) -> dict[str, Any]:
            result = super().get_item(**kwargs)
            if len([c for c in self.calls if c["TableName"] == "system"]) > 1:
                result["Item"]["desired_revision"] = {"N": "2"}
            return result

    reader = StatusReader(
        Changing(state()),
        {k: k for k in ["system", "heartbeat", "games", "operation"]},
        "system-id",
        600,
    )
    result = reader.read(NOW)
    assert result["quality"] == "partial"
    assert result["players"]["state"] == "unknown"


@pytest.mark.parametrize(
    "case",
    [
        "unexpected_scope",
        "wrong_type",
        "scope_not_text",
        "type_not_text",
        "member",
        "role",
        "revoke",
        "player",
        "admin",
        "missing",
        "empty",
        "not_text",
    ],
)
def test_callback_revokes_every_acquired_token_before_session(
    case: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []
    token = secrets.token_urlsafe(32)

    class Store(MemoryStore):
        def put(self, key: str, value: dict[str, Any]) -> None:
            if key.startswith("session-"):
                calls.append("session")
            super().put(key, value)

    class OAuth(DiscordOAuth):
        def request(self, path: str, **kwargs: Any) -> dict[str, Any]:
            calls.append(path)
            if path == "/oauth2/token":
                return {
                    "access_token": {"missing": None, "empty": "", "not_text": 1}.get(case, token),
                    "token_type": {"wrong_type": "Basic", "type_not_text": None}.get(
                        case, "Bearer"
                    ),
                    "scope": {"unexpected_scope": "identify email", "scope_not_text": []}.get(
                        case, "identify guilds.members.read"
                    ),
                }
            if path == "/oauth2/token/revoke":
                assert kwargs["form"]["token"] == token
                if case == "revoke":
                    raise AuthRejected("revocation unavailable")
                return {}
            if path.endswith("/member"):
                if case == "member":
                    raise AuthRejected("membership denied")
                return {
                    "user": {"id": "9"},
                    "roles": [] if case == "role" else ["4" if case == "admin" else "3"],
                }
            return {"id": "9"}

    store = Store()
    sessions = Sessions(store, secrets.token_bytes(32), POLICY)
    app = AuthApp(
        sessions, OAuth(POLICY, "", "https://web.example/auth/callback"), "https://web.example"
    )
    state, header = sessions.begin(int(NOW.timestamp()))
    result = app.handle(
        event(
            "/auth/callback",
            jar=header.split(";")[0],
            query=urlencode({"state": state, "code": "code"}),
        ),
        NOW,
    )
    acquired = case not in {"missing", "empty", "not_text"}
    assert calls.count("/oauth2/token/revoke") == int(acquired)
    if case in {"player", "admin"}:
        assert result["statusCode"] == 303
        assert calls[-2:] == ["/oauth2/token/revoke", "session"]
    else:
        assert result["statusCode"] == 403
        assert "session" not in calls
        assert not store.records
    assert token not in json.dumps(result) + json.dumps(store.records)
    assert not capsys.readouterr().out
