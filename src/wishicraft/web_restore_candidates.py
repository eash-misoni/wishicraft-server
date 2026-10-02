"""Bounded read projection of historical Backup provenance, never a restore verdict."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Any

from wishicraft.backup_provenance import BackupProvenanceRecord
from wishicraft.backup_recovery import recovery_digest
from wishicraft.retention import parse_rfc3339
from wishicraft.system_state import utc_timestamp
from wishicraft.web_operations import WebRejected, game_key
from wishicraft.web_status import decode, display_name

PAGE_LIMIT = 10


def encode_key(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")


def decode_key(token: str, *, snapshot: bool = False) -> str:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,300}", token):
        raise WebRejected("invalid_input")
    try:
        key = base64.b64decode(
            token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
        ).decode()
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise WebRejected("invalid_input") from error
    pattern = r"SNAPSHOT#snap-[0-9a-f]{8,17}" if snapshot else r"[A-Z_]+#[A-Za-z0-9._:-]{1,180}"
    if not re.fullmatch(pattern, key) or encode_key(key) != token:
        raise WebRejected("invalid_input")
    return key


def decoded(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("invalid provenance response")
    return {key: decode(value) for key, value in item.items()}


class Candidates:
    def __init__(self, api: Any, table: str, *, project: str, stage: str, owner: str) -> None:
        self.api, self.table = api, table
        self.project, self.stage, self.owner = project, stage, owner

    def get(self, key: str) -> dict[str, Any] | None:
        response = self.api.get_item(
            TableName=self.table, Key={"provenance_key": {"S": key}}, ConsistentRead=True
        )
        if not isinstance(response, dict):
            raise ValueError("invalid provenance response")
        return decoded(response["Item"]) if "Item" in response else None

    def project_record(self, item: dict[str, Any]) -> dict[str, Any]:
        if type(item.get("schema_version")) is not int or item.get("protected") is not False:
            raise ValueError("invalid provenance classification")
        record = BackupProvenanceRecord(
            snapshot_id=item["snapshot_id"],
            operation_id=item["operation_id"],
            game_id=item["game_id"],
            source_volume_id=item["source_volume_id"],
            stage=item["stage"],
            project=item["project"],
            category=item["category"],
            protected=item["protected"],
            verified_owner_id=item["verified_owner_id"],
            metadata=item["metadata"],
            schema_version=item["schema_version"],
            snapshot_start_time=parse_rfc3339(item["snapshot_start_time"]),
            operation_requested_at=parse_rfc3339(item["operation_requested_at"]),
            wishicraft_created_at=parse_rfc3339(item["wishicraft_created_at"]),
            provenance_recorded_at=parse_rfc3339(item["provenance_recorded_at"]),
            recovery_json=item.get("recovery_json"),
        )
        key = "SNAPSHOT#" + record.snapshot_id
        reverse = self.get("OPERATION#" + record.operation_id)
        if (
            not re.fullmatch(r"SNAPSHOT#snap-[0-9a-f]{8,17}", key)
            or item.get("provenance_key") != key
            or item.get("record_type") != "BACKUP_PROVENANCE"
            or item.get("verification_status") != "VERIFIED_BACKUP_SUCCEEDED"
            or item.get("metadata_fingerprint") != record.metadata_fingerprint
            or (record.project, record.stage, record.verified_owner_id)
            != (self.project, self.stage, self.owner)
            or reverse is None
            or type(reverse.get("schema_version")) is not int
            or reverse != record.operation_item()
        ):
            raise ValueError("inconsistent provenance")
        games = []
        if record.recovery_json is not None:
            if item.get("recovery_digest") != recovery_digest(record.recovery_json):
                raise ValueError("inconsistent recovery digest")
            recovery = json.loads(record.recovery_json)
            for game_id, game in sorted(recovery["games"].items()):
                generation = game.get("world", {}).get("generation")
                games.append(
                    {
                        "key": game_key(game_id),
                        "name": display_name(game.get("display_name")),
                        "generation": generation
                        if type(generation) is int and generation > 0
                        else None,
                        "materialization": game.get("materialization_state")
                        if game.get("materialization_state") in {"MATERIALIZED", "UNMATERIALIZED"}
                        else "unknown",
                    }
                )
        else:
            games.append(
                {
                    "key": game_key(record.game_id),
                    "name": None,
                    "generation": None,
                    "materialization": "unknown",
                }
            )
        return {
            "key": encode_key(key),
            "acquired_at": utc_timestamp(record.snapshot_start_time),
            "recorded_at": utc_timestamp(record.provenance_recorded_at),
            "provenance_version": record.schema_version,
            "coverage": "shared_volume" if record.schema_version == 2 else "legacy_unknown",
            "games": games,
            "snapshot_presence": "unknown",
            "restorability": "unknown",
        }

    def listing(self, cursor: str | None, now: datetime) -> dict[str, Any]:
        request: dict[str, Any] = {
            "TableName": self.table,
            "ConsistentRead": True,
            "Limit": PAGE_LIMIT,
            "FilterExpression": "record_type = :record_type",
            "ExpressionAttributeValues": {":record_type": {"S": "BACKUP_PROVENANCE"}},
        }
        if cursor is not None:
            request["ExclusiveStartKey"] = {"provenance_key": {"S": decode_key(cursor)}}
        response = self.api.scan(**request)
        if not isinstance(response, dict) or not isinstance(response.get("Items"), list):
            raise ValueError("invalid provenance response")
        if len(response["Items"]) > PAGE_LIMIT:
            raise ValueError("unbounded provenance response")
        items = [self.project_record(decoded(item)) for item in response["Items"]]
        token = response.get("LastEvaluatedKey")
        next_cursor = None
        if token is not None:
            if not isinstance(token, dict) or set(token) != {"provenance_key"}:
                raise ValueError("invalid provenance pagination")
            raw = decode(token["provenance_key"])
            if not isinstance(raw, str):
                raise ValueError("invalid provenance pagination")
            next_cursor = encode_key(raw)
            try:
                decode_key(next_cursor)
            except WebRejected as error:
                raise ValueError("invalid provenance pagination") from error
            if next_cursor == cursor:
                raise ValueError("repeated provenance pagination")
        return {
            "schema_version": 1,
            "generated_at": utc_timestamp(now),
            "items": sorted(items, key=lambda item: item["acquired_at"], reverse=True),
            "next_cursor": next_cursor,
            "order": "page_time_desc",
            "page_limit": PAGE_LIMIT,
        }

    def detail(self, token: str) -> dict[str, Any]:
        item = self.get(decode_key(token, snapshot=True))
        if item is None:
            raise WebRejected("not_found", 404)
        return {"schema_version": 1, "candidate": self.project_record(item)}
