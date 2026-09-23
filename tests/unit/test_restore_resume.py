from __future__ import annotations

import copy
import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.test_restore_repository import NOW, setup
from wishicraft import restore_operator
from wishicraft.maintenance import new_lease


class Ssm:
    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self.results: dict[str, dict[str, Any]] = {}
        self.lose_reply = False

    def send_command(self, **kwargs: Any) -> dict[str, Any]:
        command = {**kwargs, "CommandId": str(len(self.commands) + 1)}
        self.commands.append(command)
        self.results[command["CommandId"]] = {
            "CommandId": command["CommandId"],
            "Status": "Failed",
            "ResponseCode": 1,
        }
        if self.lose_reply:
            raise TimeoutError("response lost")
        return {"Command": command}

    def get_paginator(self, name: str) -> Any:
        return SimpleNamespace(paginate=lambda **kw: [{"Commands": self.commands}])

    def get_command_invocation(self, **kwargs: Any) -> dict[str, Any]:
        return self.results[kwargs["CommandId"]]


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch) -> Any:
    db, repo, lease, record = setup()
    record["plan"].update(project="wishicraft", source_volume_id="vol-source")
    record.update(phase="COMMITTED", host_receipt={"previous_tree": {"tree_sha256": "old"}})
    record["pre_restore_backup"].update(config_digest="digest")
    db.rows[record["system_id"]] = record
    op: Any = restore_operator.Operator.__new__(restore_operator.Operator)
    op.repo, op.ec2, op.ssm = repo, object(), Ssm()
    op.target, op.env = "i-test", {"SYSTEM_STATE_TABLE": "state"}
    op.cfg = SimpleNamespace(stage=SimpleNamespace(availability_zone="az"))
    context = {"lease": lease, "actual": "running", "revision": 7}
    monkeypatch.setattr(op, "preflight", lambda **kw: (context["lease"], context["actual"]))
    monkeypatch.setattr(op, "idle_host", lambda: (context["lease"], context["actual"]))
    monkeypatch.setattr(op, "state", lambda: {"desired_revision": context["revision"]})
    monkeypatch.setattr(restore_operator, "datetime", SimpleNamespace(now=lambda tz: NOW))
    return op, context, db


def test_failed_rollback_check_can_retry_without_manual_journal_edit(operator: Any) -> None:
    op, context, _ = operator
    op.ssm.lose_reply = True
    with pytest.raises(TimeoutError):
        op.action("check-rollback", "op-test")
    # Lost response is matched by exact payload; definite failure permits a new attempt.
    op.action("retry-rollback", "op-test")
    op.ssm.lose_reply = False
    row = op.action("check-rollback", "op-test")
    assert row["rollback_command_id"] == "2"
    assert row["rollback_history"][0]["command_id"] == "1"
    assert len(op.ssm.commands) == 2


@pytest.mark.parametrize(
    "status,code", [("InProgress", -1), ("TimedOut", -1), ("Cancelled", -1), ("Failed", -1)]
)
def test_unknown_rollback_never_resends(operator: Any, status: str, code: int) -> None:
    op, _, _ = operator
    row = op.action("check-rollback", "op-test")
    op.ssm.results[row["rollback_command_id"]].update(Status=status, ResponseCode=code)
    with pytest.raises(ValueError, match="RETRY_NOT_SAFE"):
        op.action("retry-rollback", "op-test")
    assert len(op.ssm.commands) == 1


@pytest.mark.parametrize("ambiguous", ["absent", "duplicate", "wrong-payload"])
def test_dispatch_reconciliation_rejects_ambiguity(operator: Any, ambiguous: str) -> None:
    op, _, _ = operator
    op.action("check-rollback", "op-test")
    if ambiguous == "absent":
        op.ssm.commands.clear()
    elif ambiguous == "duplicate":
        op.ssm.commands.append({**op.ssm.commands[0], "CommandId": "foreign"})
    else:
        op.ssm.commands[0]["Parameters"] = {"commands": ["wrong"]}
    with pytest.raises(ValueError, match="CHECK_UNKNOWN"):
        op.action("retry-rollback", "op-test")


def test_expired_proof_is_collected_then_reverified_in_new_lease(operator: Any) -> None:
    op, context, _ = operator
    row = op.action("check-rollback", "op-test")
    proof = {
        "operation_id": "op-test",
        "rollback_verified": True,
        "previous_tree": row["host_receipt"]["previous_tree"],
        "maintenance_id": context["lease"]["id"],
    }
    op.ssm.results["1"].update(
        Status="Success", ResponseCode=0, StandardOutputContent=json.dumps(proof)
    )
    context["lease"] = new_lease(
        lease_id="new-lease",
        actor="operator",
        reason="recovery",
        stage="dev",
        duration=3600,
        now=NOW,
    )
    op.action("collect-rollback", "op-test")
    context["actual"] = "stopped"
    with pytest.raises(ValueError, match="PROOF_REQUIRED"):
        op.action("rollback", "op-test")
    context["actual"] = "running"
    op.action("retry-rollback", "op-test")
    row = op.action("check-rollback", "op-test")
    proof["maintenance_id"] = "new-lease"
    op.ssm.results["2"].update(
        Status="Success", ResponseCode=0, StandardOutputContent=json.dumps(proof)
    )
    op.action("collect-rollback", "op-test")
    context["actual"] = "stopped"
    assert op.action("rollback", "op-test")["phase"] == "ROLLED_BACK"


@pytest.mark.parametrize("phase", ["PLANNED", "VOLUME_CREATED", "PREPARE_DISPATCH", "PREPARED"])
def test_new_start_invalidates_protection_before_any_forward_write(
    operator: Any, phase: str
) -> None:
    op, context, db = operator
    db.rows["restore#op-test"]["phase"] = phase
    context["revision"] = 9  # START/STOP can change bytes without changing world.current_id.
    before = copy.deepcopy(db.rows)
    with pytest.raises(ValueError, match="PROTECTION_STALE"):
        op.action("volume" if phase == "PLANNED" else "commit", "op-test")
    assert db.rows == before and not op.ssm.commands


@pytest.mark.parametrize("status", ["ACTIVE", "INCIDENT"])
def test_recovery_transaction_keeps_admission_closed_and_archives_previous(status: str) -> None:
    from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

    from tests.unit.test_operation import FakeDynamo
    from wishicraft.maintenance_repository import transition

    _, _, old, record = setup()
    old.update(
        status=status,
        started_at=int((NOW - timedelta(hours=2)).timestamp()),
        expires_at=int((NOW - timedelta(hours=1)).timestamp()),
    )
    new = new_lease(
        lease_id="recovery-new",
        actor="operator",
        reason="restore-recovery",
        stage="dev",
        duration=3600,
        now=NOW,
    )
    new.update(previous_maintenance_id=old["id"], restore_operation_id="op-test")
    state = {
        "maintenance": old,
        "desired_state": "STOPPED",
        "desired_revision": 7,
        "observed_at": NOW.isoformat(),
    }
    api = FakeDynamo()
    transition(
        api,
        table="state",
        locks_table="locks",
        system_id="system",
        lock_name="global",
        state=state,
        lease=new,
        event="recover-restore",
        now=NOW,
        restore_record=record,
    )
    tx: Any = api.transactions[-1]["TransactItems"]
    assert "maintenance = :previous" in tx[0]["Update"]["ConditionExpression"]
    assert "attribute_not_exists(lock_name)" == tx[2]["ConditionCheck"]["ConditionExpression"]
    audit = {k: TypeDeserializer().deserialize(v) for k, v in tx[1]["Put"]["Item"].items()}
    assert audit["previous_maintenance"] == old and audit["maintenance"] == new


@pytest.mark.parametrize("phase", ["VOLUME_CREATED", "PREPARE_DISPATCH", "PREPARED", "COMMITTED"])
@pytest.mark.parametrize("actual", ["stopped", "running"])
def test_formal_recovery_can_replace_expired_lease_without_cleanup_deadlock(
    operator: Any, monkeypatch: pytest.MonkeyPatch, phase: str, actual: str
) -> None:
    from tests.unit.test_maintenance import planned
    from wishicraft.maintenance_repository import transition

    op, _, db = operator
    row = db.rows["restore#op-test"]
    row["phase"] = phase
    state = planned()["state"]
    old = state["maintenance"]
    old["id"] = row["maintenance_id"]
    old.update(
        started_at=int((NOW - timedelta(hours=2)).timestamp()),
        expires_at=int((NOW - timedelta(hours=1)).timestamp()),
    )
    state.update(observed_at=NOW.isoformat(), desired_revision=7, target_instance_id=op.target)
    state["observation"].update(instance_id=op.target, ec2_state=actual)
    if actual == "stopped":
        state.update(health="HEALTHY", discrepancies=[])
    op.cfg = SimpleNamespace(
        project=SimpleNamespace(system_id="system"),
        stage=SimpleNamespace(global_lock_name="global"),
    )
    op.env.update(LOCKS_TABLE="locks")
    op.stage, op.prefix, op.maintenance_id = "dev", "wc-dev-", "new-recovery"
    op.ddb, op.functions = db, object()
    op.session = SimpleNamespace(
        client=lambda name: SimpleNamespace(get_caller_identity=lambda: {"Arn": "operator"})
    )
    op.ec2 = SimpleNamespace(
        describe_instances=lambda **kw: {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": op.target,
                            "State": {"Name": actual},
                            "LaunchTime": NOW - timedelta(minutes=10),
                        }
                    ]
                }
            ]
        }
    )
    monkeypatch.setattr(op, "state", lambda: state)
    monkeypatch.setattr(restore_operator, "item", lambda *args: {})
    monkeypatch.setattr(restore_operator, "no_external_work", lambda *args, **kw: None)
    monkeypatch.setattr(restore_operator, "invoke", lambda *args: {})

    def apply(api: Any, **kw: Any) -> None:
        transition(api, **kw)
        state["maintenance"] = kw["lease"]

    monkeypatch.setattr(restore_operator, "transition", apply)
    result = op.recover_maintenance("op-test", old["id"], 3600)
    assert result["phase"] == phase
    assert state["maintenance"]["id"] == "new-recovery"
    assert db.rows["restore#op-test"]["phase"] == phase
    assert db.rows["restore#op-test"]["last_maintenance_id"] == "new-recovery"
    # No intervening RESTORE action is necessary: issuance durably advances the binding.
    state["maintenance"]["status"] = "INCIDENT"
    op.maintenance_id = "next-recovery"
    op.recover_maintenance("op-test", "new-recovery", 3600)
    assert db.rows["restore#op-test"]["last_maintenance_id"] == "next-recovery"


@pytest.mark.parametrize("checkpoint", ["retry-prepare", "retry-rollback"])
def test_terminal_timeout_requires_stopped_ec2_before_retry(operator: Any, checkpoint: str) -> None:
    op, context, db = operator
    row = op.action("check-rollback", "op-test")
    op.ssm.results["1"].update(Status="TimedOut", ResponseCode=-1)
    if checkpoint == "retry-prepare":
        db.rows["restore#op-test"].update(phase="PREPARE_DISPATCH", command_id="1")
    with pytest.raises(ValueError):
        op.action(checkpoint, "op-test")
    context["actual"] = "stopped"
    row = op.action(checkpoint, "op-test")
    assert row["phase"] == ("VOLUME_CREATED" if checkpoint == "retry-prepare" else "COMMITTED")
    assert len(op.ssm.commands) == 1  # Retry authorization itself does not dispatch work.


def test_missing_legacy_lease_proof_is_not_an_obsolete_success(operator: Any) -> None:
    op, _, db = operator
    op.action("check-rollback", "op-test")
    db.rows["restore#op-test"].pop("rollback_maintenance_id")
    op.ssm.results["1"].update(Status="Success", ResponseCode=0)
    with pytest.raises(ValueError, match="RETRY_NOT_SAFE"):
        op.action("retry-rollback", "op-test")
    assert len(op.ssm.commands) == 1


@pytest.mark.parametrize(
    "action",
    [
        "volume",
        "attach",
        "prepare",
        "collect",
        "retry-prepare",
        "commit",
        "cleanup",
        "check-rollback",
        "collect-rollback",
        "retry-rollback",
        "rollback",
    ],
)
def test_foreign_recovery_lease_rejects_before_any_effect(operator: Any, action: str) -> None:
    op, context, db = operator
    context["lease"]["restore_operation_id"] = "op-other"
    before = copy.deepcopy(db.rows)
    calls = len(db.calls)
    with pytest.raises(ValueError, match="MAINTENANCE_SCOPE"):
        op.action(action, "op-test")
    assert db.rows == before and len(db.calls) == calls and not op.ssm.commands


def test_matching_recovery_lease_allows_rollback_check_and_retry(operator: Any) -> None:
    op, context, _ = operator
    context["lease"]["restore_operation_id"] = "op-test"
    op.action("check-rollback", "op-test")
    op.action("retry-rollback", "op-test")
    assert op.action("check-rollback", "op-test")["rollback_command_id"] == "2"


@pytest.mark.parametrize("foreign", ["ordinary", "scoped", "stage", "journal"])
def test_unrelated_recovery_rejected_before_reconcile(
    operator: Any, monkeypatch: pytest.MonkeyPatch, foreign: str
) -> None:
    op, context, db = operator
    op.cfg.project = SimpleNamespace(system_id="system")
    previous = copy.deepcopy(context["lease"])
    previous["status"] = "INCIDENT"
    if foreign == "ordinary":
        previous["id"] = "unrelated-maintenance"
    elif foreign == "scoped":
        previous["restore_operation_id"] = "op-other"
    elif foreign == "stage":
        previous["stage"] = "other-stage"
    else:
        db.rows["restore#op-test"]["plan"]["operation_id"] = "op-other"
    monkeypatch.setattr(op, "state", lambda: {"maintenance": previous})
    monkeypatch.setattr(restore_operator, "invoke", lambda *args: pytest.fail("invoked Reconcile"))
    before = copy.deepcopy(db.rows)
    with pytest.raises(ValueError, match="SCOPE|UNRELATED_LEASE"):
        op.recover_maintenance("op-test", previous["id"], 3600)
    assert db.rows == before and not op.ssm.commands


def test_scoped_lease_cannot_plan_another_restore_before_idle_probe(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    op, context, db = operator
    op.cfg.project = SimpleNamespace(system_id="system")
    op.stage = "dev"
    context["lease"]["restore_operation_id"] = "op-other"
    monkeypatch.setattr(op, "state", lambda: {"maintenance": context["lease"]})
    monkeypatch.setattr(op, "idle_host", lambda: pytest.fail("idle probe invoked"))
    before = copy.deepcopy(db.rows)
    with pytest.raises(ValueError, match="MAINTENANCE_SCOPE"):
        op.plan(
            game_id="game-test",
            snapshot_id="snap-test",
            protection_id="snap-new",
            request_id="new-request",
        )
    assert db.rows == before
