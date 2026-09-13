"""Bounded, UUID-keyed access policy shared by Admission, recovery and the host."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

COMMON = "policy-whitelist-common-v1"
LIMIT = 256
UID, GID = 993, 993


def policy_key(game: str | None) -> str:
    if game is None:
        return COMMON
    if re.fullmatch(r"game-[a-z0-9]+(?:-[a-z0-9]+)*", game) is None:
        raise ValueError("invalid policy Game")
    return "policy-whitelist-game-v1:" + game


def player_name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_]{3,16}", value) is None:
        raise ValueError("invalid Java player name")
    return value


def members(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > LIMIT:
        raise ValueError("invalid policy membership")
    result = {}
    for identity, name in value.items():
        if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
            raise ValueError("invalid player identity")
        result[identity] = player_name(name)
    return dict(sorted(result.items()))


def policy(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "members"}
        or type(value["revision"]) is not int
        or not 0 <= value["revision"] < 2**53
    ):
        raise ValueError("invalid whitelist policy")
    return {"revision": value["revision"], "members": members(value["members"])}


def empty() -> dict[str, Any]:
    return {"revision": 0, "members": {}}


def effective(common: object, specific: object) -> dict[str, str]:
    # UUID is identity. Common's last-known display name wins for duplicate membership.
    return dict(sorted({**policy(specific)["members"], **policy(common)["members"]}.items()))


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def player_key(identity: str) -> str:
    return hashlib.sha256(("whitelist-player-v1|" + identity).encode()).hexdigest()[:24]


def read(api: Any, table: str, game: str | None) -> dict[str, Any]:
    raw = api.get_item(
        TableName=table, Key={"game_id": {"S": policy_key(game)}}, ConsistentRead=True
    ).get("Item", {})
    return from_item(raw, game)


def from_item(raw: dict[str, Any], game: str | None) -> dict[str, Any]:
    if not raw:
        if game is None:
            raise ValueError("whitelist migration required")
        return empty()
    if set(raw) != {"game_id", "policy_json"} or raw["game_id"] != {"S": policy_key(game)}:
        raise ValueError("invalid whitelist record")
    return policy(json.loads(raw["policy_json"]["S"]))


def recovery(value: object, games: set[str]) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"common", "games"}
        or not isinstance(value["games"], dict)
        or set(value["games"]) != games
    ):
        raise ValueError("invalid whitelist recovery")
    return {
        "common": policy(value["common"]),
        "games": {game: policy(p) for game, p in value["games"].items()},
    }


def project(target: dict[str, str], common: object, specific: object, atomic: Any) -> str:
    """Called only after mount/owner preflight, under lifecycle lease and host flock, inactive."""
    import os
    import stat
    import tempfile
    from pathlib import Path

    players = effective(common, specific)
    source = Path(target["data_source"])
    properties = (source / "server.properties").read_text().splitlines()
    for key in ("online-mode", "white-list", "enforce-whitelist"):
        if [line for line in properties if line.startswith(key + "=")] != [key + "=true"]:
            raise ValueError("WHITELIST_ENFORCEMENT_REQUIRED")
    path = source / "whitelist.json"
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != UID
        or info.st_gid != GID
        or info.st_dev != source.stat().st_dev
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise ValueError("WHITELIST_FILE_IDENTITY")
    # Existing manual-file mode: no WHITELIST/WHITELIST_FILE/OPS env is introduced.
    value = encoded([{"uuid": identity, "name": name} for identity, name in players.items()]) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".whitelist-", dir=source)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchown(stream.fileno(), UID, GID)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(source, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest(players)
