"""Read-only RESTORE admission evidence. Snapshot metadata never replaces current policy."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from wishicraft.artifacts import game_package
from wishicraft.backup import BackupWorkflowError, SnapshotAdapter
from wishicraft.backup_provenance import BackupProvenanceRecord
from wishicraft.backup_recovery import recovery_digest
from wishicraft.retention import parse_rfc3339
from wishicraft.world_reference import data_source


def verified_snapshot(
    raw: dict[str, Any],
    provenance: dict[str, Any],
    reverse: dict[str, Any],
    *,
    project: str,
    stage: str,
    account: str,
    volume: str,
) -> dict[str, Any]:
    """Use the durable uniqueness pair even after the original Operation's TTL expires."""
    p = provenance
    if p.get("schema_version") != 2:
        raise ValueError("RESTORE_REQUIRES_SHARED_PROVENANCE")
    fields: dict[str, Any] = {
        **{
            k: p[k]
            for k in (
                "snapshot_id",
                "operation_id",
                "game_id",
                "source_volume_id",
                "stage",
                "project",
                "category",
                "protected",
                "verified_owner_id",
                "metadata",
                "schema_version",
                "recovery_json",
            )
        },
        **{
            k: parse_rfc3339(p[k])
            for k in (
                "snapshot_start_time",
                "operation_requested_at",
                "wishicraft_created_at",
                "provenance_recorded_at",
            )
        },
    }
    record = BackupProvenanceRecord(**fields)
    if p != record.snapshot_item() or reverse != record.operation_item():
        raise ValueError("RESTORE_PROVENANCE_PAIR")
    snapshot_raw = dict(raw)
    if isinstance(snapshot_raw.get("StartTime"), str):
        snapshot_raw["StartTime"] = parse_rfc3339(snapshot_raw["StartTime"])
    try:
        snapshot = SnapshotAdapter._parse_snapshot(snapshot_raw)
    except BackupWorkflowError as error:
        raise ValueError("RESTORE_SNAPSHOT_IDENTITY") from error
    if (
        record.project != project
        or record.stage != stage
        or record.verified_owner_id != account
        or record.source_volume_id != volume
        or snapshot.snapshot_id != record.snapshot_id
        or snapshot.owner_id != account
        or snapshot.source_volume_id != volume
        or snapshot.state != "completed"
        or snapshot.storage_tier != "standard"
        or snapshot.start_time != record.snapshot_start_time
        or snapshot.tags != record.metadata
        or snapshot.description != "Wishicraft backup " + record.operation_id
        or raw.get("Encrypted") is not True
    ):
        raise ValueError("RESTORE_SNAPSHOT_IDENTITY")
    recovery_digest(p["recovery_json"])
    return dict(json.loads(p["recovery_json"]))


def package_identity(game: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if "packages" in manifest:
        return game_package.registered(game, manifest, game_package.digest(manifest))
    # Historical shared snapshots predate the package catalog. Only their explicit
    # fixed Vanilla binding is reconstructible; never infer a missing mod package.
    if (
        game["game_id"] not in manifest.get("games", [])
        or game.get("package")
        != {"package_id": "vanilla", "package_version": "initial-fixed-version"}
        or manifest.get("server_type") != "VANILLA"
    ):
        raise ValueError("RESTORE_UNKNOWN_PACKAGE")
    return game_package.validate(
        {
            **game["package"],
            "minecraft_version": manifest["minecraft_version"],
            "loader": {"type": "vanilla"},
            "mods": [],
        }
    )


def request_operation(system_id: str, stage: str, request_id: str) -> str:
    if not isinstance(request_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id) is None:
        raise ValueError("RESTORE_REQUEST_ID")
    return (
        "op-" + hashlib.sha256((system_id + "\0" + stage + "\0" + request_id).encode()).hexdigest()
    )


def make_plan(
    *,
    game: dict[str, Any],
    current_manifest: dict[str, Any],
    recovery: dict[str, Any],
    provenance: dict[str, Any],
    request_id: str,
    system_id: str,
    now: datetime,
) -> dict[str, Any]:
    operation = request_operation(system_id, provenance["stage"], request_id)
    game_id = game["game_id"]
    source = recovery["games"].get(game_id)
    if (
        source is None
        or source.get("game_id") != game_id
        or source.get("lifecycle_state") != "ACTIVE"
        or source.get("materialization_state") != "MATERIALIZED"
        or game.get("lifecycle_state") != "ACTIVE"
        or game.get("materialization_state") != "MATERIALIZED"
    ):
        raise ValueError("RESTORE_GAME_IDENTITY")
    package = package_identity(game, current_manifest)
    if package_identity(source, json.loads(recovery["runtime"]["manifest_json"])) != package:
        raise ValueError("RESTORE_PACKAGE_MISMATCH")
    for record in (game, source):
        if type(record["world"].get("generation")) is not int or record["world"]["generation"] < 1:
            raise ValueError("RESTORE_GENERATION")
        counter = record["world"].get("generation_counter", record["world"]["generation"])
        if type(counter) is not int or counter < record["world"]["generation"]:
            raise ValueError("RESTORE_GENERATION_COUNTER")
    source_path = data_source(game_id, source["world"].get("current_id"))
    if source.get("data_source") != source_path:
        raise ValueError("RESTORE_SOURCE_PATH")
    return {
        "schema_version": 1,
        "kind": "RESTORE",
        "operation_id": operation,
        "request_id": request_id,
        "system_id": system_id,
        "stage": provenance["stage"],
        "project": provenance["project"],
        "game_id": game_id,
        "package": package,
        "package_digest": game_package.digest(package),
        "source_snapshot_id": provenance["snapshot_id"],
        "source_backup_operation": provenance["operation_id"],
        "source_backup_timestamp": provenance["snapshot_start_time"],
        "source_volume_id": provenance["source_volume_id"],
        "source_generation": source["world"]["generation"],
        "source_world": source["world"],
        "source_creation": source.get("creation"),
        "source_data_source": source_path,
        "previous_world": game["world"],
        "previous_data_source": data_source(game_id, game["world"].get("current_id")),
        "target_generation": max(
            game["world"]["generation"], game["world"].get("generation_counter", 0)
        )
        + 1,
        "target_data_source": data_source(game_id, operation),
        "created_at": now.isoformat(),
    }
