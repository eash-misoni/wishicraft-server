"""Metadata-only CREATE, with a durable request identity and atomic registry membership."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from wishicraft.game import Game, GameLifecycle, MaterializationState
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

REGISTRY_KEY = "registry-game-creation-v1"


def complete_materialization(runtime: Any, proof: Any, now: datetime) -> None:
    """Called after exact READY observation, while the existing workflow still owns its lease."""
    import os

    api = runtime.targets.api
    table = os.environ["GAMES_TABLE"]
    raw = api.get_item(
        TableName=table, Key={"game_id": {"S": runtime.game_id}}, ConsistentRead=True
    )["Item"]
    if "creation" not in raw or raw["materialization_state"] == {"S": "MATERIALIZED"}:
        return
    runtime.coordinator.leases.verify_owned(proof, now=now)
    api.transact_write_items(
        TransactItems=[
            {
                "ConditionCheck": {
                    "TableName": os.environ["LOCKS_TABLE"],
                    "Key": {"lock_name": {"S": os.environ["GLOBAL_LOCK_NAME"]}},
                    "ConditionExpression": (
                        "owner_operation_id = :op AND lease_id = :lease AND lease_expires_at > :now"
                    ),
                    "ExpressionAttributeValues": {
                        ":op": {"S": proof.owner_operation_id},
                        ":lease": {"S": proof.lease_id},
                        ":now": {"N": str(int(now.timestamp()))},
                    },
                }
            },
            {
                "Update": {
                    "TableName": table,
                    "Key": {"game_id": {"S": runtime.game_id}},
                    "UpdateExpression": (
                        "SET materialization_state = :ready, updated_at = :now, "
                        "last_started_at = :now"
                    ),
                    "ConditionExpression": (
                        "materialization_state = :never AND creation = :creation"
                    ),
                    "ExpressionAttributeValues": {
                        ":ready": {"S": "MATERIALIZED"},
                        ":never": {"S": "UNMATERIALIZED"},
                        ":creation": raw["creation"],
                        ":now": {"S": utc_timestamp(now)},
                    },
                }
            },
        ]
    )


def validate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"display_name", "seed", "reset"}:
        raise ValueError("invalid creation fields")
    name, seed, reset = value["display_name"], value["seed"], value["reset"]
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 80
        or name != name.strip()
        or unicodedata.normalize("NFC", name) != name
        or any(unicodedata.category(c).startswith("C") or c in "<>/\\" for c in name)
    ):
        raise ValueError("invalid display name")
    # Strings preserve the full Java long range across browser JSON / JavaScript.
    if seed is not None and (
        not isinstance(seed, str)
        or re.fullmatch(r"-?(?:0|[1-9][0-9]{0,18})", seed) is None
        or not -(2**63) <= int(seed) < 2**63
    ):
        raise ValueError("invalid numeric seed")
    if type(reset) is not bool:
        raise ValueError("invalid reset capability")
    return dict(value)


def registry_ids(api: Any, table: str, legacy: tuple[str, ...]) -> tuple[str, ...]:
    item = api.get_item(
        TableName=table, Key={"game_id": {"S": REGISTRY_KEY}}, ConsistentRead=True
    ).get("Item", {})
    if not item:
        return legacy
    if set(item) != {"game_id", "registered_ids"}:
        raise ValueError("invalid Game registry")
    ids = item["registered_ids"].get("SS")
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(g, str) or re.fullmatch(r"game-[0-9a-f]{64}", g) is None for g in ids)
    ):
        raise ValueError("invalid registered Game identity")
    return tuple(dict.fromkeys((*legacy, *sorted(ids))))


def create(
    repository: OperationAdmissionRepository,
    *,
    value: object,
    key: str,
    actor: WebOperationContext,
    now: datetime,
    defaults: dict[str, Any],
) -> dict[str, object]:
    payload = validate(value)
    identity = hashlib.sha256(("wishicraft-create-v1|" + key).encode()).hexdigest()
    game_id, operation_id = "game-" + identity, "op-" + identity
    request = OperationRequest(
        operation_id=operation_id,
        operation_type=OperationType.CREATE,
        idempotency_key=key,
        requested_by=RequestSource.WEB,
        requested_at=now,
        timeout_at=None,
        target_game_id=game_id,
        web=actor,
    )
    existing = repository.existing(request)
    if existing:
        return {
            "schema_version": 1,
            "operation_id": existing.operation_id,
            "created": False,
            "lease_id": None,
        }
    seed = (
        int(payload["seed"])
        if payload["seed"] is not None
        else int.from_bytes(
            hashlib.sha256(("initial-seed|" + identity).encode()).digest()[:8], "big", signed=True
        )
    )
    game = Game(
        game_id=game_id,
        display_name=payload["display_name"],
        normalized_display_name=payload["display_name"].casefold(),
        lifecycle_state=GameLifecycle.ACTIVE,
        materialization_state=MaterializationState.UNMATERIALIZED,
        package_id=defaults["package"]["package_id"],
        package_version=defaults["package"]["package_version"],
        runtime_class=defaults["runtime"]["class"],
        idle_shutdown_minutes=defaults["runtime"]["idle_shutdown_minutes"],
        world_generation=1,
        created_at=now,
        updated_at=now,
    ).to_item()
    world = game["world"]
    assert isinstance(world, dict)
    world["seed"] = seed
    game["creation"] = {
        "operation_id": operation_id,
        "actor_id": actor.user_id,
        "config_digest": defaults["config_digest"],
        "reset_policy": {"fixed_seed": seed, "retain_previous": 3, "minimum_free_bytes": 4294967296}
        if payload["reset"]
        else None,
    }
    op = repository._operation_put(request, None)
    put = op["Put"]
    assert isinstance(put, dict) and isinstance(put["Item"], dict)
    put["Item"].update(
        _attribute_map(
            {
                "status": "SUCCEEDED",
                "current_step": "GAME_REGISTERED",
                "started_at": utc_timestamp(now),
                "completed_at": utc_timestamp(now),
                "result": {"game_id": game_id, "materialization_state": "UNMATERIALIZED"},
                "creation_payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            }
        )
    )
    transaction = [
        repository._idempotency_put(request),
        op,
        {
            "Put": {
                "TableName": repository._games,
                "Item": _attribute_map(game),
                "ConditionExpression": "attribute_not_exists(game_id)",
            }
        },
        {
            "Update": {
                "TableName": repository._games,
                "Key": {"game_id": {"S": REGISTRY_KEY}},
                "UpdateExpression": "ADD registered_ids :game",
                "ExpressionAttributeValues": {":game": {"SS": [game_id]}},
            }
        },
        {
            # Registration is serialized against snapshot-time descriptor capture, not runtime work.
            "ConditionCheck": {
                "TableName": repository._locks,
                "Key": {"lock_name": {"S": repository._lock_name}},
                "ConditionExpression": "attribute_not_exists(lock_name) OR "
                "operation_type IN (:start, :stop, :switch, :reset, :retention)",
                "ExpressionAttributeValues": {
                    ":" + kind.lower(): {"S": kind}
                    for kind in ("START", "STOP", "SWITCH", "RESET", "RETENTION")
                },
            }
        },
    ]
    try:
        repository._api.transact_write_items(TransactItems=transaction)
    except Exception as error:
        prior = repository.existing(request)
        if prior is None:
            if _is_transaction_cancelled(error):
                raise AdmissionConflict("Game registration conflict") from error
            raise
        return {
            "schema_version": 1,
            "operation_id": prior.operation_id,
            "created": False,
            "lease_id": None,
        }
    return {"schema_version": 1, "operation_id": operation_id, "created": True, "lease_id": None}
