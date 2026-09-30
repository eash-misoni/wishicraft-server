"""Unwired read adapter for the future formal RETENTION execution.

Clients/tables/hold authority must be bound by a reviewed server-side factory. No SDK
client construction, CLI, file-supplied completeness flag, or mutation method exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from wishicraft.operation import _decode_attribute
from wishicraft.retention import RetentionContext, classify_inventory
from wishicraft.retention_aws_checks import inspect_candidate, pages
from wishicraft.retention_execution import DeleteObservation
from wishicraft.retention_execution_inventory import FreshInventory, digest, validate_inventory
from wishicraft.retention_workflow_lambda import _scan_all


class ExecutionReads:
    def __init__(
        self,
        *,
        ec2: Any,
        rbin: Any,
        dynamodb: Any,
        sts: Any,
        context: RetentionContext,
        region: str,
        system_id: str,
        operation_id: str,
        tables: dict[str, str],
        holds: dict[str, tuple[str, ...]],
        hold_revision: str,
        clock: Callable[[], datetime],
        historical_authority: bool = False,
    ) -> None:
        if (
            set(tables) != {"state", "games", "backups", "operations"}
            or len(set(tables.values())) != 4
        ):
            raise ValueError("INVALID_RETENTION_TABLE_BINDING")
        self.historical_authority = historical_authority
        self.ec2, self.rbin, self.ddb, self.sts = ec2, rbin, dynamodb, sts
        self.context, self.region, self.system = context, region, system_id
        self.operation, self.tables = operation_id, dict(tables)
        self.holds, self.hold_revision, self.clock = holds, hold_revision, clock

    def _identity(self) -> None:
        if self.sts.get_caller_identity().get("Account") != self.context.owner_id:
            raise ValueError("CALLER_MISMATCH")
        if any(api.meta.region_name != self.region for api in (self.ec2, self.rbin, self.ddb)):
            raise ValueError("REGION_MISMATCH")

    def inventory(self, *, recovery_snapshot_id: str | None = None) -> FreshInventory:
        try:
            started = self.clock()
            self._identity()
            raw: dict[str, list[dict[str, Any]]] = {}
            decoded: dict[str, list[dict[str, Any]]] = {}
            for name, table in self.tables.items():
                description = self.ddb.describe_table(TableName=table)["Table"]
                arn = description["TableArn"].split(":")
                if (
                    len(arn) != 6
                    or arn[2:5] != ["dynamodb", self.region, self.context.owner_id]
                    or arn[5] != "table/" + table
                ):
                    raise ValueError("TABLE_SCOPE_MISMATCH")
                raw[name] = _scan_all(self.ddb, table)
                decoded[name] = [
                    {k: _decode_attribute(v) for k, v in row.items()} for row in raw[name]
                ]
            for table, key in {
                "state": "system_id",
                "games": "game_id",
                "backups": "provenance_key",
                "operations": "operation_id",
            }.items():
                keys = [r.get(key) for r in decoded[table]]
                if any(not isinstance(k, str) or not k for k in keys) or len(set(keys)) != len(
                    keys
                ):
                    raise ValueError("DUPLICATE_OR_INVALID_TABLE_IDENTITY")
            states = [r for r in decoded["state"] if r.get("system_id") == self.system]
            if len(states) != 1:
                raise ValueError("SYSTEM_STATE_MISSING")
            snapshots = pages(
                self.ec2,
                "describe_snapshots",
                {
                    "OwnerIds": [self.context.owner_id],
                    "MaxResults": 1000,
                },
                "Snapshots",
                "SnapshotId",
            )
            # All owner pages are read. Other volumes are not deletion targets.
            owned_snapshots = snapshots
            snapshots = [s for s in snapshots if s.get("VolumeId") == self.context.source_volume_id]
            inventory = validate_inventory(
                context=self.context,
                region=self.region,
                system_id=self.system,
                operation_id=self.operation,
                now=started,
                snapshots=snapshots,
                provenance_wire=raw["backups"],
                provenance_rows=decoded["backups"],
                state=states[0],
                journals=decoded["state"],
                games=decoded["games"],
                operations=decoded["operations"],
                special_holds=self.holds,
                hold_revision=self.hold_revision,
                aws_revision="PENDING",
                read_issues=("aws-checks-pending",),
                historical_authority=self.historical_authority,
                recovery_snapshot_id=recovery_snapshot_id,
                authority_snapshots=owned_snapshots,
            )
            # Protected/legacy assets are not deletion targets. Still validate their
            # records above, but their legitimate AMI/lock holds must not consume or
            # block the normal cohort. The preliminary inventory is explicitly unknown.
            checks = [
                inspect_candidate(
                    self.ec2,
                    self.rbin,
                    snapshot_id=s.snapshot_id,
                    account=self.context.owner_id,
                    tags=s.tags,
                )
                for s in inventory.snapshots
                if s.snapshot_id not in inventory.holds
                and s.snapshot_id in inventory.proofs
                and inventory.proofs[s.snapshot_id].schema_version == 2
                and classify_inventory([s], inventory.proofs, context=self.context)[0].disposition
                == "KEEP"
            ]
            return replace(
                inventory,
                aws_revision=digest([c.revision for c in checks]),
                issues=tuple(i for i in inventory.issues if i != "aws-checks-pending")
                + tuple(i for c in checks for i in c.issues),
            )
        except Exception:
            raise ValueError("RETENTION_FRESH_READ_UNCONFIRMED") from None

    def observe(self, snapshot_id: str) -> DeleteObservation:
        try:
            self._identity()
            active = pages(
                self.ec2,
                "describe_snapshots",
                {
                    "OwnerIds": [self.context.owner_id],
                    "MaxResults": 1000,
                },
                "Snapshots",
                "SnapshotId",
            )
            binned = pages(
                self.ec2,
                "list_snapshots_in_recycle_bin",
                {
                    "MaxResults": 1000,
                },
                "Snapshots",
                "SnapshotId",
            )
            return DeleteObservation(
                snapshot_id,
                self.context.owner_id,
                self.region,
                self.clock(),
                any(r["SnapshotId"] == snapshot_id for r in active),
                any(r["SnapshotId"] == snapshot_id for r in binned),
            )
        except Exception:
            return DeleteObservation(
                snapshot_id, self.context.owner_id, self.region, self.clock(), None, None
            )
