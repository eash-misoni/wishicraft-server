from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer  # type: ignore[import-untyped]

from wishicraft.maintenance import new_lease
from wishicraft.restore_repository import RestoreRepository

NOW = datetime(2026, 9, 23, tzinfo=UTC)


class Database:
    """Transaction test double with independent changed-world/lease conflict injection."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[list[dict[str, Any]]] = []
        self.reject = False
        self.lose_reply = False

    def get_item(self, **kw: Any) -> dict[str, Any]:
        row = self.rows.get(kw["Key"]["system_id"]["S"])
        return {"Item": {k: TypeSerializer().serialize(v) for k, v in row.items()}} if row else {}

    def transact_write_items(self, **kw: Any) -> None:
        self.calls.append(kw["TransactItems"])
        if self.reject:
            raise ValueError("transaction condition rejected")
        for action in kw["TransactItems"]:
            if "Put" in action:
                row = {
                    k: TypeDeserializer().deserialize(v) for k, v in action["Put"]["Item"].items()
                }
                self.rows[row["system_id"]] = row
        if self.lose_reply:
            raise TimeoutError("committed response lost")


def setup() -> tuple[Database, RestoreRepository, dict[str, Any], dict[str, Any]]:
    db = Database()
    repo = RestoreRepository(
        db,
        state_table="state",
        games_table="games",
        locks_table="locks",
        system_id="system",
        lock_name="global",
    )
    lease = new_lease(
        lease_id="maintenance-test",
        actor="operator",
        reason="restore",
        stage="dev",
        duration=3600,
        now=NOW,
    )
    plan = {
        "operation_id": "op-test",
        "game_id": "game-test",
        "source_snapshot_id": "snap-test",
        "request_id": "request-test",
        "system_id": "system",
        "stage": "dev",
        "previous_world": {"generation": 3, "current_id": "op-previous"},
        "target_generation": 4,
    }
    record = repo.create(
        plan,
        lease=lease,
        now=NOW,
        protection={"snapshot_id": "snap-protection"},
        current_package={"package_id": "vanilla"},
    )
    return db, repo, lease, record


def test_durable_idempotency_not_operation_ttl() -> None:
    db, repo, lease, record = setup()
    assert "expires_at" not in record
    assert (
        repo.create(record["plan"], lease=lease, now=NOW, protection={}, current_package={})
        == record
    )
    assert len(db.calls) == 1
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        repo.create(
            {**record["plan"], "source_snapshot_id": "wrong"},
            lease=lease,
            now=NOW,
            protection={},
            current_package={},
        )


def test_commit_response_loss_and_explicit_rollback() -> None:
    db, repo, lease, record = setup()
    record = repo.advance(record, lease=lease, now=NOW, phase="PREPARED")
    before = copy.deepcopy(record)
    db.lose_reply = True
    committed = repo.select(record, lease=lease, now=NOW)
    assert committed["phase"] == "COMMITTED"
    writes = db.calls[-1]
    selection = writes[-1]["Update"]
    values = {
        k: TypeDeserializer().deserialize(v)
        for k, v in selection["ExpressionAttributeValues"].items()
    }
    assert values[":new"]["generation"] == 4 and values[":old"]["generation"] == 3
    assert values[":new"]["current_id"] == "op-test"
    assert "#world = :old" in selection["ConditionExpression"]
    assert "#package = :package" in selection["ConditionExpression"]
    assert "maintenance = :lease" in writes[0]["ConditionCheck"]["ConditionExpression"]
    assert writes[1]["ConditionCheck"]["ConditionExpression"] == "attribute_not_exists(lock_name)"
    assert repo.select(committed, lease=lease, now=NOW) == committed
    assert record == before
    rolled = repo.select(committed, lease=lease, now=NOW, rollback=True)
    assert rolled["phase"] == "ROLLED_BACK"
    world = TypeDeserializer().deserialize(
        db.calls[-1][-1]["Update"]["ExpressionAttributeValues"][":new"]
    )
    assert world == {"generation": 3, "current_id": "op-previous", "generation_counter": 4}


def test_changed_world_or_lease_refuses_commit_and_keeps_prepared_record() -> None:
    db, repo, lease, record = setup()
    record = repo.advance(record, lease=lease, now=NOW, phase="PREPARED")
    db.reject = True
    with pytest.raises(ValueError, match="condition rejected"):
        repo.select(record, lease=lease, now=NOW)
    assert repo.read("op-test")["phase"] == "PREPARED"
    with pytest.raises(ValueError, match="EXPIRED"):
        repo.select(record, lease=lease, now=NOW + timedelta(hours=1))


def test_unprepared_selection_is_rejected() -> None:
    db, repo, lease, record = setup()
    with pytest.raises(ValueError, match="COMMIT_PHASE"):
        repo.select(record, lease=lease, now=NOW)
    assert len(db.calls) == 1
