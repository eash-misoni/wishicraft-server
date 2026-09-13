"""Snapshot-time recovery description frozen in the existing Operation, then provenance."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, cast

from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.world_reference import data_source

SHARED_TAG_KEYS = frozenset({"WishicraftBackupScope", "WishicraftRecoveryDigest"})


def recovery_digest(value: str) -> str:
    document = json.loads(value)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "source_volume_id", "games", "runtime"}
        or document["schema_version"] not in (1, 2)
    ):
        raise ValueError("invalid recovery description")
    if (
        not isinstance(document["source_volume_id"], str)
        or re.fullmatch(r"vol-[0-9a-f]{8,17}", document["source_volume_id"]) is None
    ):
        raise ValueError("invalid recovery volume")
    games = document["games"]
    if not isinstance(games, dict):
        raise ValueError("invalid recovery Games")
    catalog = RuntimeCatalog.parse(json.dumps(list(games)))
    for game_id, record in games.items():
        world = record.get("world", {}) if isinstance(record, dict) else {}
        if not isinstance(world, dict) or (
            "current_id" in world and not isinstance(world["current_id"], str)
        ):
            raise ValueError("invalid recovery world reference")
        if (
            not isinstance(record, dict)
            or record.get("data_source")
            != data_source(game_id, record.get("world", {}).get("current_id"))
            or record.get("game_id") != game_id
        ):
            raise ValueError("recovery data binding mismatch")
    runtime = document["runtime"]
    required = {"manifest_json", "runtime_env", "compose_yaml"}
    if document["schema_version"] == 2:
        required.add("creation_config")
    if not isinstance(runtime, dict) or set(runtime) != required:
        raise ValueError("invalid recovery runtime")
    manifest = json.loads(runtime["manifest_json"])
    if (
        (
            set(manifest["games"]) != set(catalog.game_ids)
            if document["schema_version"] == 1
            else not set(manifest["games"]).issubset(catalog.game_ids)
        )
        or manifest["compose_sha256"]
        != hashlib.sha256(runtime["compose_yaml"].encode()).hexdigest()
        or manifest["runtime_env_sha256"]
        != hashlib.sha256(runtime["runtime_env"].encode()).hexdigest()
    ):
        raise ValueError("recovery runtime mismatch")
    if document["schema_version"] == 2:
        digest = hashlib.sha256(runtime["manifest_json"].encode()).hexdigest()
        for game_id, record in games.items():
            if game_id in manifest["games"]:
                continue
            creation = record.get("creation", {})
            if (
                creation.get("config_digest") != digest
                or creation.get("operation_id") != "op-" + game_id[5:]
                or record.get("materialization_state") not in {"UNMATERIALIZED", "MATERIALIZED"}
                or type(record.get("world", {}).get("seed")) is not int
            ):
                raise ValueError("invalid dynamic Game recovery")
    return hashlib.sha256(value.encode()).hexdigest()


def shared_tags(tags: dict[str, str], recovery_json: str) -> dict[str, str]:
    return {
        **tags,
        "WishicraftSchemaVersion": "2",
        "WishicraftBackupScope": "shared-volume",
        "WishicraftRecoveryDigest": recovery_digest(recovery_json),
    }


class RecoveryRepository:
    def __init__(self, api: Any, operations: str, games: str) -> None:
        self.api, self.operations, self.games = api, operations, games

    def operation(self, operation_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.api.get_item(
                TableName=self.operations,
                Key={"operation_id": {"S": operation_id}},
                ConsistentRead=True,
            )["Item"],
        )

    def read(self, operation_id: str) -> str:
        value = self.operation(operation_id)["backup_recovery_json"]["S"]
        recovery_digest(value)
        return str(value)

    def freeze(
        self,
        *,
        operation_id: str,
        lease_id: str,
        catalog: RuntimeCatalog,
        volume: str,
        runtime_json: str,
    ) -> str:
        import importlib

        raw = self.operation(operation_id)
        if "backup_recovery_json" in raw:
            return self.read(operation_id)
        deserialize = importlib.import_module("boto3.dynamodb.types").TypeDeserializer().deserialize
        records = {}
        for game_id in catalog.game_ids:
            item = self.api.get_item(
                TableName=self.games, Key={"game_id": {"S": game_id}}, ConsistentRead=True
            )["Item"]
            record = {k: deserialize(v) for k, v in item.items()}
            if (
                record.get("game_id") != game_id
                or record.get("lifecycle_state") != "ACTIVE"
                or (
                    record.get("materialization_state") != "MATERIALIZED"
                    and not (
                        "creation" in record
                        and record.get("materialization_state") == "UNMATERIALIZED"
                    )
                )
            ):
                raise ValueError("backup Game is not materialized")
            allowed = {
                "game_id",
                "schema_version",
                "version",
                "display_name",
                "normalized_display_name",
                "lifecycle_state",
                "materialization_state",
                "created_from",
                "package",
                "runtime",
                "world",
                "created_at",
                "updated_at",
                "last_started_at",
                "last_backup_at",
            }
            if "creation" in record:
                allowed.add("creation")
            if set(record) != allowed:
                raise ValueError("unknown Game schema cannot be snapshotted as known configuration")
            records[game_id] = dict(record)
            records[game_id]["data_source"] = data_source(
                game_id, record["world"].get("current_id")
            )
        from decimal import Decimal

        def number(value: Any) -> int:
            if not isinstance(value, Decimal) or value != value.to_integral_value():
                raise ValueError("invalid Game configuration number")
            return int(value)

        value = json.dumps(
            {
                "schema_version": 2 if "creation_config" in json.loads(runtime_json) else 1,
                "source_volume_id": volume,
                "games": records,
                "runtime": json.loads(runtime_json),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=number,
        )
        recovery_digest(value)
        try:
            self.api.update_item(
                TableName=self.operations,
                Key={"operation_id": {"S": operation_id}},
                UpdateExpression="SET backup_recovery_json = :recovery",
                ConditionExpression="lease_id = :lease AND operation_type = :backup "
                "AND #s IN (:pending, :running) AND attribute_not_exists(backup_recovery_json) "
                "AND attribute_not_exists(backup_create_intent)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":recovery": {"S": value},
                    ":lease": {"S": lease_id},
                    ":backup": {"S": "BACKUP"},
                    ":pending": {"S": "PENDING"},
                    ":running": {"S": "RUNNING"},
                },
            )
        except Exception:
            if self.read(operation_id) != value:
                raise ValueError("backup recovery freeze conflict") from None
        return self.read(operation_id)
