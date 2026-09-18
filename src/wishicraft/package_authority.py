"""Read immutable Game registration, independently of host version claims.

Package edits are not an application operation. Introducing one requires a new
run/version authority contract; it must not silently mutate this authority.
"""

from __future__ import annotations

import json
from typing import Any

from wishicraft.artifacts import game_package
from wishicraft.operation import _decode_attribute
from wishicraft.runtime_contract import validate_target


def legacy_package() -> dict[str, Any]:
    return game_package.select(
        game_package.load(), {"package_id": "vanilla", "package_version": "initial-fixed-version"}
    )


def registered_package(
    api: Any,
    table: str,
    game_id: str,
    *,
    legacy_ids: tuple[str, ...],
    runtime_digest: str | None = None,
) -> dict[str, Any]:
    raw = api.get_item(TableName=table, Key={"game_id": {"S": game_id}}, ConsistentRead=True)[
        "Item"
    ]
    game = {key: _decode_attribute(value) for key, value in raw.items()}
    if (
        game.get("game_id") != game_id
        or game.get("schema_version") != 1
        or game.get("lifecycle_state") != "ACTIVE"
    ):
        raise ValueError("package authority Game identity mismatch")
    creation = game.get("creation")
    # config_digest belongs to common runtime provenance, not the package digest.
    # Host/Operation target compatibility remains checked by the existing layers.
    config = creation["config_digest"] if isinstance(creation, dict) else ""
    package = game_package.registered(
        game,
        {"packages": game_package.load(), "games": legacy_ids},
        config if runtime_digest is None else runtime_digest,
    )
    return package


class GamePackageAuthority:
    def __init__(self, api: Any, table: str, legacy_ids: tuple[str, ...]) -> None:
        self.api, self.table, self.legacy_ids = api, table, legacy_ids

    def expected_version(self, stdout: str) -> str | None:
        document = json.loads(stdout)
        if document["container"]["state"] != "running":
            return None
        target = validate_target(document["execution"]["target"])
        if (
            target["instance_id"] != document["identity"]["instance_id"]
            or target["game_id"] != document["active_game"]["game_id"]
        ):
            raise ValueError("package observation identity mismatch")
        package = registered_package(
            self.api,
            self.table,
            target["game_id"],
            legacy_ids=self.legacy_ids,
            runtime_digest=target["config_digest"],
        )
        return str(package["minecraft_version"])
