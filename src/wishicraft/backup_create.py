"""One-way create reservation on the existing BACKUP Operation (not exactly-once)."""

from __future__ import annotations

from datetime import datetime

from wishicraft.operation import DynamoApi, LeaseProof
from wishicraft.system_state import utc_timestamp


class BackupCreateOutcomeUnknown(RuntimeError):
    """Creation may have happened; observation is required before any new request."""


class BackupCreateRejected(RuntimeError):
    """EC2 explicitly rejected this single create attempt."""


class BackupProvenanceOutcomeUnknown(RuntimeError):
    """A snapshot exists but successful provenance commit is not established."""


class BackupCreateGuard:
    def __init__(
        self, api: DynamoApi, *, operations_table: str, locks_table: str, lock_name: str
    ) -> None:
        self.api = api
        self.operations_table = operations_table
        self.locks_table = locks_table
        self.lock_name = lock_name

    def reserve(self, *, proof: LeaseProof, tags: dict[str, str], now: datetime) -> None:
        # Do not supply a stable ClientRequestToken across handler invocations.
        # The SDK may generate one per call; a new invocation must check the marker,
        # not receive an idempotent success for an earlier invocation's reservation.
        try:
            self.api.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.locks_table,
                            "Key": {"lock_name": {"S": self.lock_name}},
                            "ConditionExpression": (
                                "resource_id = :system AND owner_operation_id = :op "
                                "AND lease_id = :lease AND lease_expires_at >= :now"
                            ),
                            "ExpressionAttributeValues": {
                                ":system": {"S": proof.resource_id},
                                ":op": {"S": proof.owner_operation_id},
                                ":lease": {"S": proof.lease_id},
                                ":now": {"N": str(int(now.timestamp()))},
                            },
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.operations_table,
                            "Key": {"operation_id": {"S": proof.owner_operation_id}},
                            "UpdateExpression": "SET backup_create_intent = :intent",
                            "ConditionExpression": (
                                "operation_type = :backup AND #status = :running "
                                "AND lease_id = :lease AND target_game_id = :game "
                                "AND timeout_at > :now "
                                "AND attribute_not_exists(backup_create_intent)"
                            ),
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                ":backup": {"S": "BACKUP"},
                                ":running": {"S": "RUNNING"},
                                ":lease": {"S": proof.lease_id},
                                ":game": {"S": tags["WishicraftGameId"]},
                                ":now": {"S": utc_timestamp(now)},
                                ":intent": {"M": {k: {"S": v} for k, v in tags.items()}},
                            },
                        }
                    },
                ]
            )
        except Exception:
            raise BackupCreateOutcomeUnknown("create reservation not newly acknowledged") from None

    def record_snapshot(self, *, proof: LeaseProof, snapshot_id: str, tags: dict[str, str]) -> None:
        try:
            self.api.update_item(
                TableName=self.operations_table,
                Key={"operation_id": {"S": proof.owner_operation_id}},
                UpdateExpression="SET backup_snapshot_id = :snapshot",
                ConditionExpression=(
                    "operation_type = :backup AND lease_id = :lease "
                    "AND backup_create_intent = :intent "
                    "AND (attribute_not_exists(backup_snapshot_id) "
                    "OR backup_snapshot_id = :snapshot)"
                ),
                ExpressionAttributeValues={
                    ":backup": {"S": "BACKUP"},
                    ":lease": {"S": proof.lease_id},
                    ":snapshot": {"S": snapshot_id},
                    ":intent": {"M": {k: {"S": v} for k, v in tags.items()}},
                },
            )
        except Exception:
            raise BackupCreateOutcomeUnknown("snapshot response persistence unknown") from None
