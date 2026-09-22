"""Admin-only short policy transactions; no runtime dispatch or implicit migration."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any

from wishicraft.artifacts import whitelist_policy as model
from wishicraft.operation import (
    AdmissionConflict,
    OperationAdmissionRepository,
    OperationRequest,
    OperationType,
    RequestSource,
    WebOperationContext,
    _attribute_map,
    _is_transaction_cancelled,
)
from wishicraft.system_state import utc_timestamp


def validate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"action", "player", "revision"}:
        raise ValueError("invalid whitelist fields")
    if type(value["revision"]) is not int or not 0 <= value["revision"] < 2**53:
        raise ValueError("invalid policy revision")
    action, player = value["action"], value["player"]
    if action == "add":
        model.player_name(player)
    elif action == "remove":
        if not isinstance(player, str) or re.fullmatch(r"[0-9a-f]{24}", player) is None:
            raise ValueError("invalid player reference")
    elif action != "save" or player is not None:
        raise ValueError("invalid policy action")
    return dict(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def resolve(name: str) -> tuple[str, str]:
    """One bounded official lookup. Failure never invents an identity or changes policy."""
    name = model.player_name(name)
    request = urllib.request.Request(
        "https://api.mojang.com/users/profiles/minecraft/" + name,
        headers={"Accept": "application/json", "User-Agent": "Wishicraft/whitelist"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=3) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError("profile unavailable")
            value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("id"), str)
            or re.fullmatch(r"[0-9a-fA-F]{32}", value["id"]) is None
            or model.player_name(value.get("name")).casefold() != name.casefold()
        ):
            raise ValueError("profile unavailable")
        return str(uuid.UUID(value["id"])), value["name"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("profile unavailable") from None


def mutate(
    repository: OperationAdmissionRepository,
    *,
    value: object,
    game: str | None,
    key: str,
    actor: WebOperationContext,
    now: datetime,
) -> dict[str, object]:
    payload = validate(value)
    identity = hashlib.sha256(("wishicraft-whitelist-v1|" + key).encode()).hexdigest()
    request = OperationRequest(
        operation_id="op-" + identity,
        operation_type=OperationType.WHITELIST,
        idempotency_key=key,
        requested_by=RequestSource.WEB,
        requested_at=now,
        timeout_at=None,
        target_game_id=game,
        web=actor,
    )
    prior = repository.existing(request)
    if prior:
        return result(prior.operation_id, False)
    common = model.read(repository._api, repository._games, None)
    before = common if game is None else model.read(repository._api, repository._games, game)
    if before["revision"] != payload["revision"]:
        raise AdmissionConflict("policy changed")
    players = dict(before["members"])
    changed_player = None
    if payload["action"] == "add":
        identity, name = resolve(payload["player"])
        players[identity] = name
        changed_player = {"uuid": identity, "name": name}
    elif payload["action"] == "remove":
        selected = next((p for p in players if model.player_key(p) == payload["player"]), None)
        if selected is None:
            raise ValueError("unknown player")
        changed_player = {"uuid": selected, "name": players[selected]}
        del players[selected]
    after = model.policy(
        {
            "revision": before["revision"] + (players != before["members"]),
            "members": players,
        }
    )
    op = repository._operation_put(request, None)
    put = op["Put"]
    assert isinstance(put, dict) and isinstance(put["Item"], dict)
    put["Item"].update(
        _attribute_map(
            {
                "status": "SUCCEEDED",
                "current_step": "WHITELIST_SAVED",
                "started_at": utc_timestamp(now),
                "completed_at": utc_timestamp(now),
                "result": {"revision": after["revision"], "application": "NEXT_START"},
                "whitelist_change": {
                    "action": payload["action"],
                    "player": changed_player,
                    "before_digest": model.digest(before),
                    "after_digest": model.digest(after),
                },
            }
        )
    )
    policy_put: dict[str, Any] = {
        "TableName": repository._games,
        "Item": {
            "game_id": {"S": model.policy_key(game)},
            "policy_json": {"S": model.encoded(after)},
        },
        "ConditionExpression": "policy_json = :before",
        "ExpressionAttributeValues": {":before": {"S": model.encoded(before)}},
    }
    if game is not None and before == model.empty():
        policy_put["ConditionExpression"] += " OR attribute_not_exists(game_id)"
    from wishicraft.maintenance import admission_check

    transaction = [
        admission_check(table=repository._system_state, system_id=repository._system_id),
        repository._idempotency_put(request),
        op,
        {"Put": policy_put},
        {
            "ConditionCheck": {
                "TableName": repository._locks,
                "Key": {"lock_name": {"S": repository._lock_name}},
                "ConditionExpression": "attribute_not_exists(lock_name)",
            }
        },
    ]
    if game is not None:
        transaction.append(
            {
                "ConditionCheck": {
                    "TableName": repository._games,
                    "Key": {"game_id": {"S": game}},
                    "ConditionExpression": "lifecycle_state = :active",
                    "ExpressionAttributeValues": {":active": {"S": "ACTIVE"}},
                }
            }
        )
    try:
        repository._api.transact_write_items(TransactItems=transaction)
    except Exception as error:
        prior = repository.existing(request)
        if prior:
            return result(prior.operation_id, False)
        if _is_transaction_cancelled(error):
            raise AdmissionConflict("policy changed or lifecycle busy") from error
        raise
    return result(request.operation_id, True)


def result(operation: str, created: bool) -> dict[str, object]:
    return {"schema_version": 1, "operation_id": operation, "created": created, "lease_id": None}
