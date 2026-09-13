"""Loopback-only fake OAuth and synthetic state. Never part of the Lambda asset."""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from web.foundation import build_foundation
from wishicraft.web_app import AuthApp, WebApp
from wishicraft.web_auth import DiscordOAuth, Policy, Sessions
from wishicraft.web_status import project


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self.records.get(key)

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.records[key] = value

    def delete(self, key: str) -> dict[str, Any] | None:
        return self.records.pop(key, None)


class FakeOAuth(DiscordOAuth):
    def authorization_url(self, state: str) -> str:
        return "/auth/callback?code=local-only&state=" + state

    def exchange(self, code: str) -> dict[str, Any]:
        if code != "local-only":
            raise ValueError("local code rejected")
        return {
            "user_id": "9",
            "display_name": "Local operator",
            "roles": getattr(
                self, "roles", [self.policy.player_role_id, self.policy.admin_role_id]
            ),
            "guild_id": self.policy.guild_id,
        }


def fixture(now: datetime, scenario: str) -> dict[str, Any]:
    at = now.isoformat()
    state: dict[str, Any] = {
        "desired_state": "STOPPED",
        "desired_game_id": "game-local",
        "target_instance_id": "local-host",
        "health": "HEALTHY",
        "observed_at": at,
        "discrepancies": [],
        "observation_errors": [],
        "observation": {
            "ec2_state": "stopped",
            "host_runtime_state": "not-running",
            "observed_active_game_id": None,
        },
    }
    heartbeat = {
        "observed_at": at,
        "instance_id": "local-host",
        "active_game_id": "game-local",
        "run_id": "local-run",
        "process_id": "local-process",
        "protocol_state": "ready",
        "player_count": 0,
    }
    if scenario != "stopped":
        state.update(desired_state="RUNNING")
        state["observation"].update(
            ec2_state="running",
            host_runtime_state="running",
            observed_active_game_id="game-local",
            execution={
                "phase": "running",
                "target": {"run_id": "local-run"},
                "process_id": "local-process",
            },
        )
    if scenario == "players":
        heartbeat["player_count"] = 3
    if scenario == "stale":
        heartbeat["observed_at"] = "2000-01-01T00:00:00Z"
    if scenario == "unknown":
        heartbeat["protocol_state"] = "unknown"
    operation = None
    if scenario == "transition":
        state["current_operation_id"] = "local-operation"
        operation = {
            "operation_type": "SWITCH",
            "status": "RUNNING",
            "current_step": "HOST_RUNTIME_STOPPING",
            "updated_at": at,
        }
    return project(
        state,
        heartbeat,
        {"game-local": {"display_name": "Local demonstration"}},
        operation,
        set(),
        now,
    )


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=8765)
    cli.add_argument(
        "--scenario",
        choices=[
            "stopped",
            "creation",
            "running",
            "players",
            "stale",
            "unknown",
            "transition",
            "rejection",
            "conflict",
            "failure",
            "player-role",
        ],
        default="stopped",
    )
    args = cli.parse_args()
    if args.scenario == "creation":
        import os

        os.environ["GAME_CREATION"] = "1"
    root = Path(tempfile.mkdtemp(prefix="wishicraft-foundation-local-"))
    site = root / "site"
    build_foundation(Path(__file__).resolve().parents[1], site)
    policy = Policy("1", "2", "3", "4")
    sessions = Sessions(MemoryStore(), secrets.token_bytes(32), policy)
    origin = f"http://127.0.0.1:{args.port}"
    oauth = FakeOAuth(policy, "", origin + "/auth/callback")
    if args.scenario == "player-role":
        oauth.roles = [policy.player_role_id]  # type: ignore[attr-defined]
    auth = AuthApp(sessions, oauth, origin)
    from web.local_operations import LocalOperations

    operations = LocalOperations(policy, args.scenario)
    app = WebApp(
        assets=site,
        sessions=lambda: sessions,
        status=lambda now: fixture(now, args.scenario),
        operations=lambda: operations,
        origin=origin,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Callback queries/cookies are never logged, even in the local harness.

        def do_GET(self) -> None:
            self.serve()

        def do_POST(self) -> None:
            self.serve()

        def serve(self) -> None:
            url = urlsplit(self.path)
            event = {
                "rawPath": url.path,
                "rawQueryString": url.query,
                "cookies": [self.headers.get("Cookie", "")],
                "headers": dict(self.headers),
                "requestContext": {"http": {"method": self.command}},
            }
            event["body"] = self.rfile.read(
                min(int(self.headers.get("Content-Length", "0")), 2049)
            ).decode()
            result = (auth if url.path.startswith("/auth/") else app).handle(
                event, datetime.now(UTC)
            )
            self.send_response(result["statusCode"])
            for key, value in result["headers"].items():
                self.send_header(key, value)
            for value in result["cookies"]:
                # Only this loopback harness relaxes Secure for HTTP development.
                self.send_header("Set-Cookie", value.replace("__Host-", "").replace("; Secure", ""))
            self.end_headers()
            body = result["body"]
            if "text/html" in result["headers"].get("content-type", ""):
                body = body.replace(
                    "<h1>",
                    '<p class="warning">LOCAL MOCK · '
                    "実Discord認証・実運用状態ではありません</p><h1>",
                    1,
                )
            self.wfile.write(body.encode())

    # Translate local cookie names only at the local request boundary.
    original = Handler.serve

    def serve_local(self: Handler) -> None:
        raw = self.headers.get("Cookie", "")
        if raw:
            del self.headers["Cookie"]
            self.headers["Cookie"] = raw.replace("wishicraft", "__Host-wishicraft")
        original(self)

    Handler.serve = serve_local  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    origin = f"http://127.0.0.1:{server.server_port}"
    auth.origin = origin
    app.origin = origin
    (root / "local.json").write_text(
        json.dumps({"origin": origin, "scenario": args.scenario, "fake_auth": True})
    )
    print(f"LOCAL FAKE AUTH ONLY: {origin} | evidence: {root}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
