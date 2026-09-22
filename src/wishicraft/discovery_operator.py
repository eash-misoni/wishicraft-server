"""D-084 Guild command read-back/update; never bulk overwrite or recreate a command."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from wishicraft.discovery_commands import autocomplete
from wishicraft.reset_commands import extend
from wishicraft.two_game_admin import declaration


def canonical(root: Path) -> list[dict[str, Any]]:
    reset = json.loads((root / "config/reset-dev.json").read_text())
    return autocomplete(
        extend(declaration(root, now=datetime.now(UTC))["discord_commands"], tuple(reset))
    )


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def normalized(value: Any) -> Any:
    if isinstance(value, list):
        return [normalized(v) for v in value]
    if isinstance(value, dict):
        return {
            k: normalized(v)
            for k, v in value.items()
            if not (v is None or k in {"required", "autocomplete"} and v is False)
        }
    return value


def update_body(before: list[dict[str, Any]], expected: list[dict[str, Any]]) -> dict[str, Any]:
    if len(before) != 1 or before[0].get("name") != "mc":
        raise ValueError("unexpected Guild command inventory")
    transformed = autocomplete(before)
    fields = ("name", "description", "type", "options")
    if normalized({k: transformed[0][k] for k in fields}) != normalized(expected[0]):
        raise ValueError("live command differs from canonical contract")
    return {"options": transformed[0]["options"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "status", "update"))
    parser.add_argument("--stage", choices=("dev",), default="dev")
    parser.add_argument("--profile", default="wishicraft-dev")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--expected-command-id")
    parser.add_argument("--expected-definition-sha256")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    expected = canonical(root)
    if args.action == "render":
        print(json.dumps(expected, ensure_ascii=False, indent=2))
        return
    if args.evidence is None:
        parser.error("status/update require a new --evidence file")
    if args.evidence.exists():
        parser.error("evidence already exists")
    if args.action == "update" and not (
        args.expected_command_id and args.expected_definition_sha256
    ):
        parser.error("update requires reviewed command ID and definition digest")
    import boto3  # type: ignore[import-untyped]
    import yaml

    stage = yaml.safe_load((root / f"config/stages/{args.stage}.yaml").read_text())
    secrets = yaml.safe_load((root / "config/secrets.example.yaml").read_text())
    session = boto3.Session(profile_name=args.profile, region_name=stage["aws"]["region"])
    if session.client("sts").get_caller_identity()["Account"] != stage["aws"]["account_id"]:
        raise ValueError("caller account mismatch")
    parameter = secrets["secure_parameters"]["discord_bot_token"][args.stage + "_parameter_name"]
    token = session.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"][
        "Value"
    ]
    application, guild = stage["discord"]["application_id"], stage["discord"]["guild_id"]
    base = f"https://discord.com/api/v10/applications/{application}"

    def request(path: str, body: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = Request(
            base + path,
            data=payload,
            headers={
                "Authorization": "Bot " + token,
                "Content-Type": "application/json",
                "User-Agent": "Wishicraft-D084",
            },
            method="PATCH" if body is not None else "GET",
        )
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    scope = f"/guilds/{guild}/commands"
    before, globals_before = request(scope), request("/commands")
    if globals_before:
        raise ValueError("global commands must remain empty")
    body = update_body(before, expected)
    identity = before[0]["id"]
    snapshot = {
        "stage": args.stage,
        "observed_at": datetime.now(UTC).isoformat(),
        "command_id": identity,
        "definition_sha256": digest(before),
        "before": before,
        "global_count_before": 0,
        "candidate_patch": body,
    }
    # Persist before mutation so an interrupted read-back never loses its predecessor.
    with args.evidence.open("x") as output:
        json.dump(snapshot, output, ensure_ascii=False, indent=2)
    if args.action == "update":
        if (
            identity != args.expected_command_id
            or digest(before) != args.expected_definition_sha256
        ):
            raise ValueError("reviewed command changed; no update performed")
        request(scope + "/" + identity, body)
        after, global_after = request(scope), request("/commands")
        if len(after) != 1 or after[0]["id"] != identity or global_after:
            raise ValueError("command read-back identity/scope mismatch")

        def untouched(c: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in c.items() if k not in {"version", "options"}}

        if untouched(before[0]) != untouched(after[0]) or normalized(
            after[0]["options"]
        ) != normalized(body["options"]):
            raise ValueError("command read-back contract mismatch")
        snapshot.update(after=after, global_count_after=0)
        args.evidence.with_suffix(".after.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2)
        )
    print(
        json.dumps(
            {
                "command_id": identity,
                "definition_sha256": digest(before),
                "action": args.action,
                "evidence": str(args.evidence),
            }
        )
    )


if __name__ == "__main__":
    main()
