"""Offline migration planning. Never reads a live host or writes AWS."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from wishicraft.artifacts import whitelist_policy as model


def persisted(value: object) -> dict[str, str]:
    if not isinstance(value, list) or len(value) > model.LIMIT:
        raise ValueError("invalid persisted whitelist")
    result = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"uuid", "name"}:
            raise ValueError("ambiguous persisted whitelist")
        identity = str(uuid.UUID(entry["uuid"]))
        if identity in result:
            raise ValueError("duplicate persisted identity requires review")
        result[identity] = model.player_name(entry["name"])
    return model.members(result)


def plan(values: Mapping[str, object]) -> dict[str, Any]:
    if len(values) < 2:
        raise ValueError("migration requires every existing materialized Game")
    lists = {game: persisted(value) for game, value in values.items()}
    for game in lists:
        model.policy_key(game)
    # Shared legacy membership does not establish access to future Games.
    names_by_identity: dict[str, str] = {}
    for players in lists.values():
        for identity, name in players.items():
            if identity in names_by_identity and names_by_identity[identity] != name:
                raise ValueError("inconsistent last-known name requires review")
            names_by_identity[identity] = name
    common: dict[str, str] = {}
    policies: dict[str, Any] = {
        "common": {"revision": 1, "members": model.members(common)},
        "games": {
            game: {
                "revision": 1,
                "members": dict(players),
            }
            for game, players in lists.items()
        },
    }
    model.recovery(policies, set(lists))
    proof = {}
    for game, before in lists.items():
        after = model.effective(policies["common"], policies["games"][game])
        if before != after:
            raise ValueError("migration changes effective membership")
        proof[game] = {
            "count": len(before),
            "digest": model.digest(before),
            "specific_count": len(policies["games"][game]["members"]),
        }
    return {"policy": policies, "proof": proof, "common_count": len(common)}


def transaction(
    planned: dict[str, Any],
    records: dict[str, dict[str, Any]],
    *,
    games_table: str,
    locks_table: str,
    lock_name: str,
) -> dict[str, Any]:
    """Generate a reviewable one-time transaction; caller must have captured source file proofs."""
    policy = model.recovery(planned["policy"], set(records))
    actions: list[dict[str, Any]] = []
    for game, value in [(None, policy["common"]), *policy["games"].items()]:
        actions.append(
            {
                "Put": {
                    "TableName": games_table,
                    "Item": {
                        "game_id": {"S": model.policy_key(game)},
                        "policy_json": {"S": model.encoded(value)},
                    },
                    "ConditionExpression": "attribute_not_exists(game_id)",
                }
            }
        )
    for game, record in records.items():
        if record.get("game_id") != {"S": game} or "creation" in record:
            raise ValueError("migration expects unchanged legacy registry")
        actions.append(
            {
                "ConditionCheck": {
                    "TableName": games_table,
                    "Key": {"game_id": {"S": game}},
                    "ConditionExpression": "world = :world AND #v = :version "
                    "AND lifecycle_state = :active "
                    "AND materialization_state = :ready AND attribute_not_exists(creation)",
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {
                        ":world": record["world"],
                        ":version": record["version"],
                        ":active": {"S": "ACTIVE"},
                        ":ready": {"S": "MATERIALIZED"},
                    },
                }
            }
        )
    actions.extend(
        [
            {
                "ConditionCheck": {
                    "TableName": locks_table,
                    "Key": {"lock_name": {"S": lock_name}},
                    "ConditionExpression": "attribute_not_exists(lock_name)",
                }
            },
            {
                "ConditionCheck": {
                    "TableName": games_table,
                    "Key": {"game_id": {"S": "registry-game-creation-v1"}},
                    "ConditionExpression": "attribute_not_exists(game_id)",
                }
            },
        ]
    )
    return {"TransactItems": actions}


def host_bundle(root: Path, output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Exact D-105 predecessor; same inactive-only installer, no data/runtime config migration."""
    import hashlib
    import subprocess

    from wishicraft.game_creation_migration import prepare

    output.mkdir(mode=0o700, exist_ok=False)
    prepare(root, output / "creation-reference", receipt)
    reference = json.loads((output / "creation-reference/install.json").read_text())
    previous_config = (output / "creation-reference/0.artifact").read_text()
    evidence = json.loads(
        (root / "docs/evidence/minimal_game_creation_production_2026-09-13.json").read_text()
    )
    # The caller reviews this plan against the tracked production evidence. The baseline wrapper
    # is fetched from the exact release commit, never inferred from the current working tree.
    expected = {
        entry["destination"]: entry["sha256"] for entry in evidence["host_upgrade"]["plan"]["files"]
    }
    wrapper = subprocess.run(
        ["git", "show", "e75f825:src/wishicraft/artifacts/targeted_runtime.py"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    config = json.loads(previous_config)
    config["whitelist_management"] = True
    entries = []
    changes = [
        (
            "/etc/wishicraft/runtime-contract.json",
            json.dumps(config, sort_keys=True),
            0o600,
            hashlib.sha256(previous_config.encode()).hexdigest(),
        ),
        (
            "/usr/local/libexec/wishicraft/operation-v2",
            "#!/usr/bin/env python3\n"
            + (root / "src/wishicraft/artifacts/targeted_runtime.py").read_text(),
            0o755,
            hashlib.sha256(b"#!/usr/bin/env python3\n" + wrapper).hexdigest(),
        ),
        (
            "/usr/local/libexec/wishicraft/whitelist_policy.py",
            (root / "src/wishicraft/artifacts/whitelist_policy.py").read_text(),
            0o644,
            None,
        ),
    ]
    for index, (destination, content, mode, predecessor) in enumerate(changes):
        if predecessor is not None and expected.get(destination) != predecessor:
            raise ValueError("D-105 predecessor evidence mismatch")
        source = str(index) + ".artifact"
        (output / source).write_text(content)
        entries.append(
            {
                "destination": destination,
                "source": source,
                "mode": mode,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "predecessor": predecessor,
            }
        )
    result = {**reference, "files": entries, "backup_namespace": "whitelist-v1"}
    (output / "install.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    installer = (
        (root / "src/wishicraft/artifacts/runtime_install.py")
        .read_text()
        .replace("/var/tmp/wishicraft-targeted-runtime-v1", "/var/tmp/wishicraft-whitelist-v1")
        .replace('namespace != "two-game-v1"', 'namespace != "whitelist-v1"')
    )
    (output / "install.py").write_text(installer)
    return result
