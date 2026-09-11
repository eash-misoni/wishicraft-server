"""Fixed second-Game declaration and explicit operator registration; no active-pointer edits."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wishicraft.config import load_configuration
from wishicraft.game import _attribute_map
from wishicraft.game_admin import initial_game
from wishicraft.runtime_catalog import RuntimeCatalog


def declaration(root: Path, *, now: datetime) -> dict[str, Any]:
    configuration = load_configuration(root, "dev")
    catalog = RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text())
    game = replace(
        initial_game(root, "dev", now=now),
        game_id=catalog.game_ids[1],
        display_name="Wishicraft Vanilla B",
        normalized_display_name="wishicraft-vanilla-b",
    )
    files = {
        "server.properties": "level-name=world\nonline-mode=true\n"
        "white-list=true\nenforce-whitelist=true\n",
        "whitelist.json": json.dumps(
            [
                {
                    "uuid": configuration.project.initial_minecraft_profile_uuid_hyphenated,
                    "name": configuration.project.initial_minecraft_profile_name,
                }
            ],
            sort_keys=True,
        )
        + "\n",
    }
    commands = json.loads((root / "config/discord/commands.v1.json").read_text())
    game_option = {
        "type": 3,
        "name": "game",
        "description": "Game to start",
        "choices": [{"name": name, "value": name} for name in catalog.game_ids],
    }
    for option in commands[0]["options"]:
        if option["name"] == "start":
            option["options"] = [game_option]
    commands[0]["options"].append(
        {
            "type": 1,
            "name": "switch",
            "description": "Admin: save/stop the empty current Game and start another",
            "options": [
                {**game_option, "required": True},
                {
                    "type": 5,
                    "name": "confirm",
                    "description": "Confirm stopping the current Game",
                    "required": True,
                },
            ],
        }
    )
    return {
        "schema_version": 1,
        "game": game.to_item(),
        "materialization": {"game_id": game.game_id, "files": files},
        "discord_commands": commands,
    }


def register(api: Any, document: dict[str, Any], proof: dict[str, Any]) -> None:
    game = document["game"]
    game_id = game["game_id"]
    expected = {
        "schema_version": 1,
        "game_id": game_id,
        "data_source": f"/srv/minecraft/games/{game_id}/server",
        "files": {
            k: hashlib.sha256(v.encode()).hexdigest()
            for k, v in document["materialization"]["files"].items()
        },
    }
    if proof != expected:
        raise ValueError("materialization evidence mismatch")
    item = _attribute_map(game)
    # The reviewed declaration is retained across interruption; changed timestamps are not replay.
    current = api.get_item(
        TableName="wc-dev-games", Key={"game_id": {"S": game_id}}, ConsistentRead=True
    ).get("Item")
    if current is not None:
        if current != item:
            raise ValueError("existing Game differs from declaration")
        return
    try:
        api.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": "wc-dev-locks",
                        "Key": {"lock_name": {"S": "minecraft-control"}},
                        "ConditionExpression": "attribute_not_exists(lock_name)",
                    }
                },
                {
                    "ConditionCheck": {
                        "TableName": "wc-dev-system-state",
                        "Key": {"system_id": {"S": "wishicraft-main"}},
                        "ConditionExpression": "desired_state = :stopped AND "
                        "(attribute_not_exists(current_operation_id) "
                        "OR current_operation_id = :null)",
                        "ExpressionAttributeValues": {
                            ":stopped": {"S": "STOPPED"},
                            ":null": {"NULL": True},
                        },
                    }
                },
                {
                    "Put": {
                        "TableName": "wc-dev-games",
                        "Item": item,
                        "ConditionExpression": "attribute_not_exists(game_id)",
                    }
                },
            ]
        )
    except Exception:
        actual = api.get_item(
            TableName="wc-dev-games", Key={"game_id": {"S": game_id}}, ConsistentRead=True
        ).get("Item")
        if actual != item:
            raise ValueError("Game registration outcome unresolved") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--execute-registration", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not args.execute_registration:
        with args.declaration.open("x") as stream:
            json.dump(declaration(root, now=datetime.now(UTC)), stream, indent=2)
        return
    if args.proof is None:
        parser.error("registration requires exact host materialization evidence")
    configuration = load_configuration(root, "dev")
    document = json.loads(args.declaration.read_text())
    expected = declaration(
        root, now=datetime.fromisoformat(document["game"]["created_at"].replace("Z", "+00:00"))
    )
    if expected != document:
        raise ValueError("unapproved second-Game declaration")
    session = importlib.import_module("boto3").Session(
        profile_name="wishicraft-dev", region_name=configuration.stage.aws_region
    )
    if session.client("sts").get_caller_identity()["Account"] != configuration.stage.aws_account_id:
        raise ValueError("canonical caller mismatch")
    register(session.client("dynamodb"), document, json.loads(args.proof.read_text()))


if __name__ == "__main__":
    main()
