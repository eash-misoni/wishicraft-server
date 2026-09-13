from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from aws_cdk.assertions import Template

from infrastructure.app import build_app
from web.foundation import build_foundation
from web.local import FakeOAuth, MemoryStore, fixture
from wishicraft import web_lambda
from wishicraft.web_app import WebApp
from wishicraft.web_auth import AuthRejected, DiscordOAuth, Policy, Sessions

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://web.wishicraft.net"
POLICY = Policy("1", "2", "3", "4")


@pytest.mark.parametrize("phase", ["legacy", "certificate", "domain", "canonical"])
def test_staged_resources_and_handler_environment(
    phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = build_app(ROOT, "dev", phase=8, deployment="web", web_domain_phase=phase)
    template = Template.from_stack(app.node.find_child("WishicraftWebStack-dev"))  # type: ignore[arg-type]
    resources = template.to_json()["Resources"]
    certs = [r for r in resources.values() if r["Type"] == "AWS::CertificateManager::Certificate"]
    assert len(certs) == (0 if phase == "legacy" else 1)
    if certs:
        assert certs[0]["Properties"]["DomainName"] == "web.wishicraft.net"
        assert certs[0]["Properties"]["CertificateExport"] == "DISABLED"
        assert certs[0]["Properties"]["ValidationMethod"] == "DNS"
        assert certs[0]["Properties"]["DomainValidationOptions"] == [
            {"DomainName": "web.wishicraft.net", "HostedZoneId": "Z077818024BJUAUBFMTKV"}
        ]
        assert certs[0]["DeletionPolicy"] == "Retain"
    domains = [r for r in resources.values() if r["Type"] == "AWS::ApiGatewayV2::DomainName"]
    assert len(domains) == (1 if phase in {"domain", "canonical"} else 0)
    if domains:
        config = domains[0]["Properties"]["DomainNameConfigurations"][0]
        assert config["EndpointType"] == "REGIONAL" and config["SecurityPolicy"] == "TLS_1_2"
        alias = next(r for r in resources.values() if r["Type"] == "AWS::Route53::RecordSet")
        assert alias["Properties"]["Name"] == "web.wishicraft.net"
        assert alias["Properties"]["Type"] == "A"
        assert alias["Properties"]["HostedZoneId"] == "Z077818024BJUAUBFMTKV"
        assert alias["Properties"]["AliasTarget"]["EvaluateTargetHealth"] is False
    assert not any(
        r["Type"]
        in {"AWS::Route53::HostedZone", "AWS::CloudFront::Distribution", "AWS::S3::Bucket"}
        for r in resources.values()
    )
    policies = json.dumps([r for r in resources.values() if r["Type"] == "AWS::IAM::Policy"])
    assert "route53:" not in policies and "acm:" not in policies and "dynamodb:Scan" not in policies
    functions = [
        r["Properties"] for r in resources.values() if r["Type"] == "AWS::Lambda::Function"
    ]
    for fn in functions:
        env = fn["Environment"]["Variables"]
        assert ("WEB_CANONICAL_ORIGIN" in env) == (phase == "canonical")
        if phase == "canonical":
            monkeypatch.setenv("WEB_CANONICAL_ORIGIN", env["WEB_CANONICAL_ORIGIN"])
            assert web_lambda.canonical_guard(event("/")) is None
            redirected = web_lambda.canonical_guard(event("/", host="old.execute-api.example"))
            assert redirected is not None
            assert redirected["headers"]["location"] == ORIGIN + "/"
        if fn["Handler"].endswith("auth_handler"):
            assert (env["WEB_ORIGIN"] == ORIGIN) == (phase == "canonical")


def event(path: str, host: str = "web.wishicraft.net", method: str = "GET") -> dict[str, Any]:
    return {
        "rawPath": path,
        "rawQueryString": "code=never-forward&state=never-forward",
        "headers": {"host": "forged.example"},
        "requestContext": {"domainName": host, "http": {"method": method}},
    }


@pytest.mark.parametrize("path", ["/", "/games/", "/commands/start/", "/manage/", "/auth/login"])
def test_noncanonical_public_redirect_drops_query(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEB_CANONICAL_ORIGIN", ORIGIN)
    result = web_lambda.handler(event(path, "old.execute-api.example"), None)
    assert result["statusCode"] == 308
    assert result["headers"]["location"] == ORIGIN + path
    assert "never-forward" not in json.dumps(result)
    assert result["cookies"] == []


@pytest.mark.parametrize(
    "path,method", [("/api/status", "GET"), ("/auth/callback", "GET"), ("/auth/logout", "POST")]
)
def test_old_host_private_rejected_before_secret_read(
    path: str, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEB_CANONICAL_ORIGIN", ORIGIN)

    def forbidden(*args: Any) -> Any:
        raise AssertionError("must reject before AWS initialization")

    monkeypatch.setattr(web_lambda, "sessions", forbidden)
    result = web_lambda.auth_handler(event(path, "old.execute-api.example", method), None)
    assert result["statusCode"] == 421 and result["headers"]["cache-control"] == "no-store"
    assert "location" not in result["headers"]


def test_origin_bound_state_session_and_fixed_oauth() -> None:
    store = MemoryStore()
    key = secrets.token_bytes(32)
    old = Sessions(store, key, POLICY)
    current = Sessions(store, key, POLICY, origin=ORIGIN)
    old_cookie = old.create(100).split(";", 1)[0].split("=", 1)[1]
    with pytest.raises(AuthRejected):
        current.authenticate(old_cookie, 101)
    state, signed = old.begin(100)
    with pytest.raises(AuthRejected):
        current.consume(state, signed.split(";", 1)[0].split("=", 1)[1], 101)
    header = current.create(100)
    assert "Domain=" not in header
    assert all(x in header for x in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=900"))
    value = header.split(";", 1)[0].split("=", 1)[1]
    current.authenticate(value, 101)
    with pytest.raises(AuthRejected):
        current.authenticate(value, 1000)
    current.logout(value)
    with pytest.raises(AuthRejected):
        current.authenticate(value, 101)
    oauth = DiscordOAuth(POLICY, "test-only", ORIGIN + "/auth/callback")
    query = parse_qs(urlsplit(oauth.authorization_url("state-value")).query)
    assert query["redirect_uri"] == [ORIGIN + "/auth/callback"]
    assert query["scope"] == ["identify guilds.members.read"]


def test_local_and_public_links_remain_relative() -> None:
    assert "fetch('/api/status'" in (ROOT / "web/manage.js").read_text()
    assert 'action="/auth/logout"' in (ROOT / "web/manage.html").read_text()
    assert "execute-api" not in (ROOT / "web/manage.html").read_text()
    assert "127.0.0.1" in (ROOT / "web/local.py").read_text()


def test_unknown_migration_phase_rejected() -> None:
    with pytest.raises(ValueError, match="migration phase"):
        build_app(ROOT, "dev", phase=8, deployment="web", web_domain_phase="typo")


def test_custom_host_login_status_logout_through_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEB_CANONICAL_ORIGIN", ORIGIN)
    monkeypatch.setenv("WEB_ORIGIN", ORIGIN)
    monkeypatch.setenv("WEB_OAUTH_PARAMETER", "test-only")
    sessions = Sessions(MemoryStore(), secrets.token_bytes(32), POLICY, origin=ORIGIN)
    monkeypatch.setattr(web_lambda, "sessions", lambda: sessions)
    monkeypatch.setattr(web_lambda, "policy", lambda: POLICY)
    monkeypatch.setattr(web_lambda, "secret", lambda name: "test-only")
    monkeypatch.setattr(web_lambda, "DiscordOAuth", FakeOAuth)
    build_foundation(ROOT, tmp_path / "site")
    app = WebApp(
        assets=tmp_path / "site",
        sessions=lambda: sessions,
        status=lambda now: fixture(now, "stopped"),
    )
    monkeypatch.setattr(web_lambda, "web_app", lambda: app)
    assert web_lambda.handler(event("/"), None)["statusCode"] == 200
    assert web_lambda.handler(event("/api/status"), None)["statusCode"] == 401
    begin = web_lambda.auth_handler(event("/auth/login"), None)
    assert begin["statusCode"] == 302
    callback = event("/auth/callback")
    callback["cookies"] = [begin["cookies"][0].split(";", 1)[0]]
    callback["rawQueryString"] = urlsplit(begin["headers"]["location"]).query
    login = web_lambda.auth_handler(callback, None)
    assert login["statusCode"] == 303 and login["headers"]["location"] == "/manage/"
    signed = login["cookies"][0].split(";", 1)[0]
    read = event("/api/status")
    read["cookies"] = [signed]
    result = web_lambda.handler(read, None)
    assert json.loads(result["body"])["players"]["state"] == "not_expected"
    read["rawPath"] = "/manage/"
    assert 'src="/manage.js"' in web_lambda.handler(read, None)["body"]
    logout = event("/auth/logout", method="POST")
    logout["headers"]["origin"] = ORIGIN
    logout["cookies"] = [signed]
    ended = web_lambda.auth_handler(logout, None)
    assert ended["statusCode"] == 303 and ended["headers"]["location"] == "/"
    assert "Max-Age=0" in ended["cookies"][0]
    read["rawPath"] = "/api/status"
    assert web_lambda.handler(read, None)["statusCode"] == 401
