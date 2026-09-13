"""HTTP -> session/CSRF -> real Admission handler/service/serializer -> read projection."""

from __future__ import annotations

import io
import json
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from web.foundation import build_foundation
from web.local import fixture
from web.local_operations import LocalOperations
from wishicraft import admission_lambda, web_lambda
from wishicraft.web_app import WebApp
from wishicraft.web_auth import Policy, Sessions
from wishicraft.web_operations import OPERATIONS, game_key
from wishicraft.web_status import decode

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(UTC)
ORIGIN = "https://web.wishicraft.net"
POLICY = Policy("1", "2", "3", "4")


class SessionDynamo:
    """AWS transport only; production session serialization is exercised unchanged."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        item = kwargs["Item"]
        key = item["id"]["S"]
        assert key not in self.records
        self.records[key] = json.loads(json.dumps(item))
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ConsistentRead"] is True
        return {"Item": self.records.get(kwargs["Key"]["id"]["S"], {})}

    def delete_item(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ReturnValues"] == "ALL_OLD"
        return {"Attributes": self.records.pop(kwargs["Key"]["id"]["S"], {})}


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    backend = LocalOperations(POLICY, "stopped")
    sessions = Sessions(
        web_lambda.DynamoSessions(SessionDynamo(), "sessions"),
        secrets.token_bytes(32),
        POLICY,
        origin=ORIGIN,
    )
    site = tmp_path / "site"
    build_foundation(ROOT, site)
    app = WebApp(
        assets=site,
        sessions=lambda: sessions,
        status=lambda now: fixture(now, "stopped"),
        operations=lambda: backend,
        origin=ORIGIN,
    )
    for name, value in {
        "AWS_REGION": "ap-northeast-1",
        "SYSTEM_STATE_TABLE": "system",
        "SYSTEM_ID": "local",
        "GAME_ID": backend.catalog[0],
        "RUNTIME_GAMES": json.dumps(backend.catalog),
        "RESET_POLICIES": json.dumps(
            {
                backend.catalog[1]: {
                    "fixed_seed": 0,
                    "retain_previous": 3,
                    "minimum_free_bytes": 4294967296,
                }
            }
        ),
        **{
            "ADMISSION_" + k: v
            for k, v in zip(
                ("APPLICATION_ID", "GUILD_ID", "PLAYER_ROLE_ID", "ADMIN_ROLE_ID"),
                ("1", "2", "3", "4"),
                strict=True,
            )
        },
        **{
            k + "_STATE_MACHINE_ARN": "test-" + k
            for k in ("START", "STOP", "BACKUP", "SWITCH", "RESET")
        },
        "OPERATIONS_TABLE": "operation",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(admission_lambda, "_get_service", lambda: backend.domain)
    launches: list[dict[str, Any]] = []

    class Launcher:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def start(self, **kwargs: Any) -> None:
            launches.append(kwargs)

    for name in ("_get_launcher", "_get_stop_launcher", "_get_backup_launcher"):
        monkeypatch.setattr(admission_lambda, name, Launcher)
    monkeypatch.setattr(admission_lambda, "WorkflowLauncher", Launcher)
    import boto3  # type: ignore[import-untyped]

    monkeypatch.setattr(boto3, "client", lambda *a, **k: backend.db)
    calls: list[dict[str, Any]] = []

    class Invoker:
        def invoke(self, **kwargs: Any) -> dict[str, Any]:
            payload = json.loads(kwargs["Payload"])
            calls.append(payload)
            result = admission_lambda.handler(payload, None)
            return {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(result).encode())}

    backend.lambda_api = Invoker()
    return app, sessions, backend, launches, calls


def login(sessions: Sessions, roles: list[str] | None = None, user: str = "9") -> str:
    return sessions.create(
        int(NOW.timestamp()),
        {
            "user_id": user,
            "display_name": "Test Operator",
            "roles": ["3", "4"] if roles is None else roles,
            "guild_id": "2",
        },
    ).split(";")[0]


def request(kind: str = "START", game: str = "game-demo-one") -> dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "type": kind,
        "game": game_key(game) if kind in {"START", "SWITCH", "RESET"} else None,
        "confirm": kind in {"SWITCH", "RESET"},
        "seed": "fixed" if kind == "RESET" else None,
    }


def event(
    jar: str = "",
    value: object = None,
    *,
    path: str = "/api/operations",
    method: str = "POST",
    csrf: str = "",
    origin: str = ORIGIN,
) -> dict[str, Any]:
    return {
        "rawPath": path,
        "cookies": [jar],
        "headers": {"origin": origin, "content-type": "application/json", "x-csrf-token": csrf},
        "body": json.dumps(value),
        "requestContext": {"domainName": "web.wishicraft.net", "http": {"method": method}},
    }


def post(boundary: Any, jar: str, value: object) -> dict[str, Any]:
    app, sessions, *_ = boundary
    token = sessions.csrf(jar.split("=", 1)[1])
    return dict(app.handle(event(jar, value, csrf=token), NOW))


def test_authenticated_dynamo_session_reaches_manage_capabilities_and_status(boundary: Any) -> None:
    app, sessions, *_ = boundary
    jar = login(sessions)
    for path in ["/manage/", "/api/capabilities", "/api/status"]:
        result = app.handle(event(jar, path=path, method="GET"), NOW)
        assert result["statusCode"] == 200
        assert "discord_user_id" not in result["body"]
    capabilities = json.loads(
        app.handle(event(jar, path="/api/capabilities", method="GET"), NOW)["body"]
    )
    assert capabilities["allowed"] == list(OPERATIONS)
    assert capabilities["csrf_token"] == sessions.csrf(jar.split("=", 1)[1])


@pytest.mark.parametrize("kind", OPERATIONS)
@pytest.mark.parametrize("roles", [["3"], ["4"], ["5"]])
def test_policy_enforced_at_http_and_admission(boundary: Any, kind: str, roles: list[str]) -> None:
    app, sessions, backend, launches, calls = boundary
    jar = login(sessions, roles)
    result = post(boundary, jar, request(kind, backend.catalog[1]))
    permitted = roles == ["4"] or roles == ["3"] and kind in {"START", "STOP", "RESET"}
    assert result["statusCode"] == (202 if permitted else 401 if roles == ["5"] else 403)
    assert len(launches) == int(permitted)
    if permitted:
        actor = calls[0]["web"]
        actor["roles"] = ["5"]
        denied = admission_lambda.handler(calls[0], None)
        assert denied == {"error": "forbidden"}
        assert len(launches) == 1


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "invalid",
        "expired",
        "logout",
        "csrf_missing",
        "csrf_mismatch",
        "other_session",
        "foreign_origin",
        "form",
    ],
)
def test_auth_csrf_fail_closed(boundary: Any, case: str) -> None:
    app, sessions, backend, launches, calls = boundary
    jar = login(sessions)
    signed = jar.split("=", 1)[1]
    ev = event(jar, request(), csrf=sessions.csrf(signed))
    now = NOW
    if case == "missing":
        ev["cookies"] = []
    if case == "invalid":
        ev["cookies"] = [jar + "x"]
    if case == "expired":
        now += timedelta(seconds=900)
    if case == "logout":
        sessions.logout(signed)
    if case == "csrf_missing":
        del ev["headers"]["x-csrf-token"]
    if case == "csrf_mismatch":
        ev["headers"]["x-csrf-token"] = "bad"
    if case == "other_session":
        ev["headers"]["x-csrf-token"] = sessions.csrf(login(sessions).split("=", 1)[1])
    if case == "foreign_origin":
        ev["headers"]["origin"] = "https://foreign.example"
    if case == "form":
        ev["headers"] = {
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://foreign.example",
        }
    result = app.handle(ev, now)
    assert result["statusCode"] in {401, 403}
    assert not launches and not calls and not backend.db.transactions


@pytest.mark.parametrize("kind", OPERATIONS)
def test_real_mapping_retry_terminal_and_actor(boundary: Any, kind: str) -> None:
    app, sessions, backend, launches, calls = boundary
    jar = login(sessions)
    value = request(kind, backend.catalog[1])
    assert post(boundary, jar, value)["statusCode"] == 202
    # Response lost: no operation handle is needed to recover the same request.
    assert post(boundary, jar, value)["statusCode"] == 200
    assert len(launches) == 1 and backend.db.transactions == 1
    op_id = launches[0]["operation_id"]
    raw = backend.db.records["operation", op_id]
    item = {k: decode(v) for k, v in raw.items()}
    assert item["requested_by"] == {
        "source": "WEB",
        "discord_user_id": "9",
        "display_name": "Test Operator",
    }
    assert item["discord"] == {
        "guild_id": None,
        "channel_id": None,
        "interaction_id": None,
        "message_id": None,
    }
    assert item["operation_type"] == kind
    assert item["target_game_id"] == (backend.catalog[1] if value["game"] else backend.catalog[0])
    raw["status"] = {"S": "SUCCEEDED"}
    raw["completed_at"] = {"S": NOW.isoformat()}
    raw["progress_reconciling_at"] = {"S": NOW.isoformat()}
    backend.db.records["system", "local"]["current_operation_id"] = {"NULL": True}
    backend.db.records["system", "local"]["desired_game_id"] = {"S": backend.catalog[1]}
    # Re-login retains actor-bound lookup; no old session credential is reused.
    next_jar = login(sessions)
    r = app.handle(
        event(next_jar, path="/api/operations/request/" + value["request_id"], method="GET"), NOW
    )
    body = json.loads(r["body"])
    assert body["operation"]["terminal"] and body["operation"]["status"] == "SUCCEEDED"
    assert body["operation"]["milestones"]
    for secret in (
        "discord_user_id",
        "game-demo",
        "op-",
        "lease-",
        "arn:",
        "session_fingerprint",
        "request_digest",
    ):
        assert secret not in r["body"]
    other = app.handle(
        event(login(sessions, user="8"), path="/api/operations/current", method="GET"), NOW
    )
    assert json.loads(other["body"])["operation"]["status"] == "SUCCEEDED"
    assert post(boundary, next_jar, value)["statusCode"] == 200
    # Also retry the trusted Lambda invocation itself after selection changed.
    assert admission_lambda.handler(calls[0], None)["created"] is False
    assert len(launches) == 1


def test_double_submit_and_conflicting_reuse(boundary: Any) -> None:
    _, sessions, backend, launches, _ = boundary
    jar = login(sessions)
    value = request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(boundary, jar, value), range(2)))
    assert all(r["statusCode"] in {200, 202} for r in results)
    assert len(launches) == 1 and backend.db.transactions == 1
    assert post(boundary, jar, {**value, "game": game_key(backend.catalog[1])})["statusCode"] == 409
    assert post(boundary, jar, request("STOP"))["statusCode"] == 409


@pytest.mark.parametrize(
    "mutation",
    [
        {"actor": "forged"},
        {"roles": ["4"]},
        {"confirm": False},
        {"seed": "arbitrary"},
        {"game": "../../../world"},
    ],
)
def test_reset_confirmation_and_forgery(boundary: Any, mutation: dict[str, Any]) -> None:
    _, sessions, backend, launches, _ = boundary
    jar = login(sessions)
    result = post(boundary, jar, {**request("RESET", backend.catalog[1]), **mutation})
    assert result["statusCode"] == 400
    assert not launches


def test_unsupported_reset_and_actor_scoped_request(boundary: Any) -> None:
    app, sessions, backend, launches, _ = boundary
    jar = login(sessions)
    assert post(boundary, jar, request("RESET"))["statusCode"] == 422
    value = request()
    assert post(boundary, jar, value)["statusCode"] == 202
    r = app.handle(
        event(
            login(sessions, user="8"),
            path="/api/operations/request/" + value["request_id"],
            method="GET",
        ),
        NOW,
    )
    assert json.loads(r["body"])["outcome"] == "not_recorded"
    assert len(launches) == 1


def test_result_unknown_and_partial_read(boundary: Any) -> None:
    app, sessions, backend, launches, _ = boundary
    jar = login(sessions)
    value = request()
    original = backend.lambda_api

    class Lost:
        def invoke(self, **kwargs: Any) -> Any:
            original.invoke(**kwargs)
            raise RuntimeError("arn:secret internal failure")

    backend.lambda_api = Lost()
    result = post(boundary, jar, value)
    assert result["statusCode"] == 503 and "result_unknown" in result["body"]
    assert "secret" not in result["body"]
    assert post(boundary, jar, value)["statusCode"] == 200
    assert len(launches) == 1
    raw = backend.db.records["operation", launches[0]["operation_id"]]
    raw["status"] = {"S": "FAILED"}
    raw["error"] = {"M": {"code": {"S": "WORKFLOW_START_FAILED"}, "message": {"S": "secret-raw"}}}
    read = app.handle(
        event(jar, path="/api/operations/request/" + value["request_id"], method="GET"), NOW
    )
    assert "workflow_start_failed" in read["body"] and "secret-raw" not in read["body"]
    raw["status"] = {"S": "invalid"}
    read = app.handle(
        event(jar, path="/api/operations/request/" + value["request_id"], method="GET"), NOW
    )
    assert read["statusCode"] == 503 and "invalid" not in read["body"]


def test_old_host_write_and_capabilities_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CANONICAL_ORIGIN", ORIGIN)
    for path in ("/api/operations", "/api/capabilities", "/api/operations/current"):
        ev = event(path=path, method="POST" if path.endswith("operations") else "GET")
        ev["requestContext"]["domainName"] = "old.execute-api.example"
        assert web_lambda.handler(ev, None)["statusCode"] == 421


def test_synth_exact_admission_permission_and_no_business_writes() -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="web")
    doc = Template.from_stack(app.node.find_child("WishicraftWebStack-dev")).to_json()  # type: ignore[arg-type]
    statements = [
        s
        for r in doc["Resources"].values()
        if r["Type"] == "AWS::IAM::Policy"
        for s in r["Properties"]["PolicyDocument"]["Statement"]
    ]
    invoke = [s for s in statements if s["Action"] == "lambda:InvokeFunction"]
    assert len(invoke) == 1
    assert invoke[0]["Resource"] == {
        "Fn::Join": [
            "",
            [
                "arn:",
                {"Ref": "AWS::Partition"},
                ":lambda:ap-northeast-1:385526546525:function:wc-dev-admission",
            ],
        ]
    }
    assert "*" not in json.dumps(invoke[0])
    assert not any(
        "dynamodb:UpdateItem" in str(s["Action"])
        or "states:StartExecution" in str(s["Action"])
        or "ssm:SendCommand" in str(s["Action"])
        for s in statements
    )
    assert "discord-bot-token" not in json.dumps(doc)
    assert "CorsConfiguration" not in json.dumps(doc)
