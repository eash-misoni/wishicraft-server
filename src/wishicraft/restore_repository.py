"""Operator RESTORE journal and selection CAS under the formal maintenance fence.

Uses existing SystemState audit storage, without TTL or application IAM changes.
The operator validates external observations immediately before these transactions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from wishicraft.maintenance import check_restore_lease, lease_active
from wishicraft.maintenance_operator import item
from wishicraft.maintenance_repository import encode


class RestoreRepository:
    def __init__(
        self,
        api: Any,
        *,
        state_table: str,
        games_table: str,
        locks_table: str,
        system_id: str,
        lock_name: str,
    ) -> None:
        self.api, self.state_table, self.games_table = api, state_table, games_table
        self.locks_table, self.system_id, self.lock_name = locks_table, system_id, lock_name

    def read(self, operation: str) -> dict[str, Any]:
        return item(self.api, self.state_table, "system_id", "restore#" + operation)

    def fences(self, lease: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        if not lease_active(lease, now=now):
            raise ValueError("RESTORE_MAINTENANCE_EXPIRED")
        return [
            {
                "ConditionCheck": {
                    "TableName": self.state_table,
                    "Key": encode({"system_id": self.system_id}),
                    "ConditionExpression": "maintenance = :lease AND desired_state = :stopped AND "
                    "(attribute_not_exists(current_operation_id) OR current_operation_id = :null)",
                    "ExpressionAttributeValues": encode(
                        {":lease": lease, ":stopped": "STOPPED", ":null": None}
                    ),
                }
            },
            {
                "ConditionCheck": {
                    "TableName": self.locks_table,
                    "Key": encode({"lock_name": self.lock_name}),
                    "ConditionExpression": "attribute_not_exists(lock_name)",
                }
            },
        ]

    def save(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        *,
        lease: dict[str, Any],
        now: datetime,
        extra: list[dict[str, Any]] | None = None,
    ) -> None:
        check_restore_lease(lease, after["plan"]["operation_id"])
        if after["system_id"] != "restore#" + after["plan"]["operation_id"]:
            raise ValueError("RESTORE_JOURNAL_IDENTITY")
        after["last_maintenance_id"] = lease["id"]
        # Whole journal replacement is safe only with exact prior revision and immutable plan.
        write: dict[str, Any] = {
            "TableName": self.state_table,
            "Item": encode(after),
            "ConditionExpression": "attribute_not_exists(system_id)",
        }
        if before:
            write.update(
                ConditionExpression="#revision = :revision AND #plan = :plan",
                ExpressionAttributeNames={"#revision": "revision", "#plan": "plan"},
                ExpressionAttributeValues=encode(
                    {":revision": before["revision"], ":plan": before["plan"]}
                ),
            )
        try:
            fences = self.fences(lease, now)
            if before.get("phase") == "PREPARED" and after["phase"] == "COMMITTED":
                revision = after["pre_restore_backup"].get("desired_revision")
                if revision is None:
                    raise ValueError("RESTORE_PROTECTION_REVISION_MISSING")
                check = fences[0]["ConditionCheck"]
                check["ConditionExpression"] += " AND desired_revision = :protection_revision"
                check["ExpressionAttributeValues"].update(
                    encode({":protection_revision": revision})
                )
            self.api.transact_write_items(TransactItems=[*fences, {"Put": write}, *(extra or [])])
        except Exception:
            if self.read(after["plan"]["operation_id"]) != after:
                raise

    def create(
        self,
        plan: dict[str, Any],
        *,
        lease: dict[str, Any],
        now: datetime,
        protection: dict[str, Any],
        current_package: dict[str, Any],
    ) -> dict[str, Any]:
        check_restore_lease(lease, plan["operation_id"])
        existing = self.read(plan["operation_id"])
        if existing:
            immutable = ("game_id", "source_snapshot_id", "request_id", "system_id", "stage")
            if any(existing["plan"][k] != plan[k] for k in immutable):
                raise ValueError("RESTORE_IDEMPOTENCY_CONFLICT")
            return existing
        record = {
            "system_id": "restore#" + plan["operation_id"],
            "record_type": "RESTORE",
            "plan": plan,
            "phase": "PLANNED",
            "revision": 1,
            "maintenance_id": lease["id"],
            "pre_restore_backup": protection,
            "actor": lease["actor"],
            "current_package": current_package,
        }
        self.save({}, record, lease=lease, now=now)
        return record

    def advance(
        self, record: dict[str, Any], *, lease: dict[str, Any], now: datetime, **changes: Any
    ) -> dict[str, Any]:
        if any(k in changes for k in ("plan", "system_id", "revision")):
            raise ValueError("RESTORE_IMMUTABLE_JOURNAL")
        result = {**record, **changes, "revision": record["revision"] + 1}
        self.save(record, result, lease=lease, now=now)
        return result

    def select(
        self,
        record: dict[str, Any],
        *,
        lease: dict[str, Any],
        now: datetime,
        rollback: bool = False,
    ) -> dict[str, Any]:
        plan = record["plan"]
        check_restore_lease(lease, plan["operation_id"])
        desired_phase = "ROLLED_BACK" if rollback else "COMMITTED"
        if record["phase"] == desired_phase:
            return record
        if record["phase"] != ("COMMITTED" if rollback else "PREPARED"):
            raise ValueError("RESTORE_COMMIT_PHASE")
        previous = plan["previous_world"]
        following = {
            **previous,
            "current_id": plan["operation_id"],
            "generation": plan["target_generation"],
            "generation_counter": plan["target_generation"],
        }
        old, new = (
            (following, {**previous, "generation_counter": plan["target_generation"]})
            if rollback
            else (previous, following)
        )
        expected_package = record["current_package"]
        update = {
            "Update": {
                "TableName": self.games_table,
                "Key": encode({"game_id": plan["game_id"]}),
                "UpdateExpression": "SET #world = :new",
                "ConditionExpression": "#world = :old AND #package = :package AND "
                "lifecycle_state = :active AND materialization_state = :ready",
                "ExpressionAttributeNames": {"#world": "world", "#package": "package"},
                "ExpressionAttributeValues": encode(
                    {
                        ":old": old,
                        ":new": new,
                        ":package": expected_package,
                        ":active": "ACTIVE",
                        ":ready": "MATERIALIZED",
                    }
                ),
            }
        }
        result = {
            **record,
            "phase": desired_phase,
            "revision": record["revision"] + 1,
            "selection_changed_at": now.isoformat(),
        }
        self.save(record, result, lease=lease, now=now, extra=[update])
        return result
