from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from tests.unit.test_retention_inventory import (
    ACCOUNT,
    CANARY,
    CONTEXT,
    NOW,
    OP,
    SID,
    VOLUME,
    data,
    journal,
    manifest,
    proof,
    wire,
)
from tools.retention_inventory import report
from wishicraft.backup_recovery import shared_tags
from wishicraft.retention_deletion import DeletionPhase, DeletionRecord
from wishicraft.retention_execution_inventory import validate_inventory


def fixture() -> dict[str, Any]:
    p = proof()
    env_hash = hashlib.sha256(CANARY.encode()).hexdigest()
    recovery = json.dumps(
        dict(
            schema_version=1,
            source_volume_id=VOLUME,
            games={
                "game-vanilla-main": dict(
                    game_id="game-vanilla-main",
                    data_source="/srv/minecraft/games/game-vanilla-main/server",
                )
            },
            runtime=dict(
                runtime_env=CANARY,
                compose_yaml=CANARY,
                manifest_json=json.dumps(
                    dict(
                        games=["game-vanilla-main"],
                        compose_sha256=env_hash,
                        runtime_env_sha256=env_hash,
                    )
                ),
            ),
        )
    )
    p = replace(
        p,
        schema_version=2,
        recovery_json=recovery,
        metadata=shared_tags({**p.metadata, "WishicraftSchemaVersion": "2"}, recovery),
    )
    rows = [p.snapshot_item(), p.operation_item()]
    return dict(
        context=CONTEXT,
        region="ap-northeast-1",
        system_id="wishicraft-main",
        operation_id="op-retention-test",
        now=NOW + timedelta(days=30),
        snapshots=[
            dict(
                SnapshotId=SID,
                VolumeId=VOLUME,
                OwnerId=ACCOUNT,
                State="completed",
                Encrypted=True,
                StorageTier="standard",
                StartTime=NOW,
                Description="Wishicraft backup " + OP,
                Tags=[{"Key": k, "Value": v} for k, v in p.metadata.items()],
            )
        ],
        provenance_wire=[wire(r) for r in rows],
        provenance_rows=rows,
        state=dict(
            system_id="wishicraft-main",
            current_operation_id="op-retention-test",
            backup_protection={"schema_version": 1},
        ),
        journals=[],
        games=[dict(game_id="game-vanilla-main")],
        operations=[],
        special_holds={},
        hold_revision="reviewed-server-binding",
        aws_revision="aws-checked",
        read_issues=(),
    )


def test_original_recovery_validated_in_memory_and_revision_avoids_private_payload() -> None:
    f = fixture()
    inv = validate_inventory(**f)
    assert not inv.issues
    identity = inv.identity(f["now"])
    assert len(identity) == 64 and not inv.policy(f["now"]).candidate_ids
    assert CANARY not in repr(inv)
    assert hashlib.sha256(CANARY.encode()).hexdigest() not in repr(inv)
    f["provenance_rows"][0]["recovery_json"] += " "
    # Identity of immutable record as well as digest/canonical body is checked.
    f["provenance_wire"] = [wire(r) for r in f["provenance_rows"]]
    assert validate_inventory(**f).issues


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "volume",
        "encrypted",
        "tag",
        "proof",
        "pair",
        "pending",
        "hold",
        "journal",
        "missing",
        "maintenance",
    ],
)
def test_unconfirmed_domains_fail_closed(mutation: str) -> None:
    f = fixture()
    if mutation in {"owner", "volume", "encrypted"}:
        field, value = {
            "owner": ("OwnerId", "111111111111"),
            "volume": ("VolumeId", "vol-fffffffffffffffff"),
            "encrypted": ("Encrypted", False),
        }[mutation]
        f["snapshots"][0][field] = value
    elif mutation == "tag":
        f["snapshots"][0]["Tags"][0]["Value"] = "foreign"
    elif mutation == "proof":
        f["provenance_rows"][0]["operation_id"] = "op-other"
    elif mutation == "pair":
        f["provenance_rows"].pop()
    elif mutation == "pending":
        f["operations"] = [dict(operation_id="op-other", operation_type="BACKUP", status="PENDING")]
    elif mutation == "hold":
        f["special_holds"] = {"snap-fffffffffffffffff": ("migration-anchor",)}
    elif mutation == "journal":
        f["journals"] = [{**journal(), "revision": None}]
    elif mutation == "missing":
        f["snapshots"] = []
    elif mutation == "maintenance":
        f["state"]["maintenance"] = {"status": "ACTIVE"}
    f["provenance_wire"] = [wire(r) for r in f["provenance_rows"]]
    inv = validate_inventory(**f)
    assert inv.issues
    with pytest.raises(ValueError):
        inv.identity(f["now"])


@pytest.mark.parametrize("phase", ["PLANNED", "PREPARED", "COMMITTED", "ROLLED_BACK"])
def test_multiple_holds_and_journal_revision_are_independent(phase: str) -> None:
    f = fixture()
    f["journals"] = [journal(phase)]
    f["special_holds"] = {SID: ("migration-anchor",)}
    inv = validate_inventory(**f)
    assert not inv.issues and len(inv.holds[SID]) == 3
    f["journals"][0]["revision"] += 1
    assert validate_inventory(**f).reference_revision != inv.reference_revision
    f["special_holds"] = {}
    assert len(validate_inventory(**f).holds[SID]) == 2
    assert f["provenance_rows"][0]["snapshot_id"] == SID


def deleted_fixture() -> tuple[dict[str, Any], DeletionRecord]:
    f = fixture()
    p = validate_inventory(**f).proofs[SID]
    assert p.recovery_digest
    requested = NOW + timedelta(days=29)
    r = DeletionRecord(
        ACCOUNT,
        "ap-northeast-1",
        "wishicraft-main",
        "dev",
        VOLUME,
        SID,
        OP,
        "op-retention-test",
        NOW.isoformat(),
        p.recovery_digest,
        "a" * 64,
        requested.isoformat(),
        "ADMIN",
        phase=DeletionPhase.FORMALLY_DELETED,
        request_outcome="EXPLICIT_SUCCESS",
        reconciliation="ACTIVE_ABSENT",
        first_absent_at=(requested + timedelta(seconds=10)).isoformat(),
        last_observed_at=(requested + timedelta(seconds=25)).isoformat(),
        confirmed_at=(requested + timedelta(seconds=25)).isoformat(),
        revision=4,
    )
    return f, r


@pytest.mark.parametrize("change", ["", "unknown", "missing-reverse", "mismatch", "held"])
def test_collector_formal_deletion_exact_pair_only_and_always_no_delete(change: str) -> None:
    f, r = deleted_fixture()
    if change == "unknown":
        r = replace(
            r,
            phase=DeletionPhase.RESPONSE_RECORDED,
            request_outcome="OUTCOME_UNKNOWN",
            confirmed_at=None,
        )
    elif change == "mismatch":
        r = replace(r, backup_operation_id="op-other")
    rows = [*f["provenance_rows"], r.item()]
    if change != "missing-reverse":
        rows.append(
            dict(
                provenance_key="RETENTION#" + r.retention_operation_id,
                record_type="RETENTION_DELETION_UNIQUENESS",
                retention_operation_id=r.retention_operation_id,
                snapshot_id=SID,
            )
        )
    payload = data()
    payload["backups"] = [wire(row) for row in rows]
    payload["games"] = [wire(dict(game_id="game-vanilla-main"))]
    payload["state"] = [wire(journal())] if change == "held" else []
    original = deepcopy(payload)
    output = report(
        payload,
        context=CONTEXT,
        region="ap-northeast-1",
        system="wishicraft-main",
        now=f["now"],
        manifest={**manifest(), "holds": []},
        audit=[],
        comparisons=[],
    )
    assert output["status"] == "NO_DELETE"
    assert output["deletion_authorized"] is False and output["planned_delete_ids"] == []
    assert output["delete_action_count"] == 0 and payload == original
    final = [h for h in output["deletion_history"] if h["classification"] == "FORMALLY_DELETED"]
    assert bool(final) == (change == "")
    assert CANARY not in json.dumps(output)


def test_fresh_read_adapter_validates_all_table_bindings_and_pages() -> None:
    from types import SimpleNamespace

    from tests.unit.test_retention_execution_boundaries import AwsReads
    from wishicraft.retention_execution_reads import ExecutionReads

    f = fixture()

    class Api(AwsReads):
        meta = SimpleNamespace(region_name="ap-northeast-1")
        tables = {"s": [f["state"]], "g": f["games"], "b": f["provenance_rows"], "o": []}
        scans: list[str] = []

        def get_caller_identity(self) -> dict[str, str]:
            return {"Account": ACCOUNT}

        def describe_table(self, **kw: Any) -> dict[str, Any]:
            return {
                "Table": {
                    "TableArn": f"arn:aws:dynamodb:ap-northeast-1:{ACCOUNT}:table/"
                    + kw["TableName"]
                }
            }

        def scan(self, **kw: Any) -> dict[str, Any]:
            assert kw["ConsistentRead"] is True
            self.scans.append(kw["TableName"])
            return {"Items": [wire(r) for r in self.tables[kw["TableName"]]]}

        def describe_snapshots(self, **kw: Any) -> dict[str, Any]:
            assert kw["OwnerIds"] == [ACCOUNT]
            return {"Snapshots": f["snapshots"]}

    api = Api()
    reads = ExecutionReads(
        ec2=api,
        rbin=api,
        dynamodb=api,
        sts=api,
        context=CONTEXT,
        region="ap-northeast-1",
        system_id="wishicraft-main",
        operation_id="op-retention-test",
        tables=dict(state="s", games="g", backups="b", operations="o"),
        holds={},
        hold_revision="reviewed-server-binding",
        clock=lambda: f["now"],
    )
    inv = reads.inventory()
    assert not inv.issues and set(api.scans) == {"s", "g", "b", "o"}
    assert inv.proofs[SID].operation_id == OP
    reads.holds = {SID: ("reviewed-special-hold",)}
    api.images = [{"ImageId": "ami-held-anchor"}]
    held = reads.inventory()
    assert not held.issues and SID in held.holds
    assert len(api.calls) == 5  # no extra AMI/lock checks for the held asset
    # A repeated identity from a changing scan is not a consistent inventory.
    api.tables["g"] = [*f["games"], *f["games"]]
    with pytest.raises(ValueError, match="FRESH_READ_UNCONFIRMED"):
        reads.inventory()
