from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import boto3  # type: ignore[import-untyped]
import pytest
from botocore.exceptions import ClientError, ReadTimeoutError  # type: ignore[import-untyped]

from infrastructure.retention_iam import shared_delete_policy
from tests.unit.test_retention_daily import NOW
from tests.unit.test_retention_execution import CANARY, PROOF
from tests.unit.test_retention_execution_boundaries import Dynamo, initial_record, repository
from wishicraft.retention import DeleteRequestOutcome, RetentionContext
from wishicraft.retention_authority import _authority, reviewed_failure
from wishicraft.retention_delete_adapter import Ec2DeleteAdapter, delete_client
from wishicraft.retention_execution import DeleteObservation
from wishicraft.retention_recovery import Quiescence, RecoveryRead, resume
from wishicraft.retention_release import RetentionRelease, load_retention_release

ROOT = Path(__file__).resolve().parents[2]


def client() -> Any:
    session = boto3.Session(aws_access_key_id="synthetic", aws_secret_access_key="synthetic")
    return delete_client(session, region="ap-northeast-1")


def test_real_sdk_never_retries_transport_send(monkeypatch: Any, capsys: Any) -> None:
    api = client()
    count = 0

    def send(*a: Any, **kw: Any) -> Any:
        nonlocal count
        count += 1
        raise ReadTimeoutError(endpoint_url=CANARY)

    monkeypatch.setattr(api._endpoint.http_session, "send", send)
    result = Ec2DeleteAdapter(api, region="ap-northeast-1").delete_once(
        snapshot_id="snap-0123456789abcdef0"
    )
    assert result == DeleteRequestOutcome.OUTCOME_UNKNOWN and count == 1
    assert CANARY not in str(result) + str(capsys.readouterr())
    assert api.meta.config.retries == {"mode": "standard", "total_max_attempts": 1}


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, "EXPLICIT_SUCCESS"),
        ("AccessDenied", "EXPLICIT_ACCESS_DENIED"),
        ("UnauthorizedOperation", "EXPLICIT_ACCESS_DENIED"),
        ("InvalidSnapshot.NotFound", "OUTCOME_UNKNOWN"),
        ("InternalError", "OUTCOME_UNKNOWN"),
        ("transport", "OUTCOME_UNKNOWN"),
    ],
)
def test_adapter_outcomes(code: str | None, expected: str, capsys: Any) -> None:
    class Api:
        meta = SimpleNamespace(
            region_name="ap-northeast-1",
            config=SimpleNamespace(retries={"total_max_attempts": 1, "mode": "standard"}),
        )
        count = 0

        def delete_snapshot(self, **kw: Any) -> dict[str, Any]:
            self.count += 1
            assert kw == {"SnapshotId": "snap-0123456789abcdef0"}
            if code == "transport":
                raise RuntimeError(CANARY)
            if code:
                raise ClientError({"Error": {"Code": code, "Message": CANARY}}, "DeleteSnapshot")
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    api = Api()
    assert (
        Ec2DeleteAdapter(api, region="ap-northeast-1")
        .delete_once(snapshot_id="snap-0123456789abcdef0")
        .value
        == expected
    )
    assert api.count == 1 and CANARY not in str(capsys.readouterr())


def case() -> tuple[dict[str, Any], dict[str, Any]]:
    a = _authority()
    expected = a["operations"][0]
    row = {k: v for k, v in expected.items() if k != "error_code"}
    row.update(
        workflow_execution_name=row["operation_id"],
        error={
            "code": expected["error_code"],
            "message": None,
            "detail_ref": None,
            "retryable": None,
        },
    )
    args = dict(
        context=RetentionContext(
            "wishicraft", "dev", "game-vanilla-main", a["volume"], a["account"], shared_volume=True
        ),
        region=a["region"],
        system=a["system"],
        snapshots=[],
        provenance=[],
        references=[],
    )
    return row, args


def test_exact_authority_does_not_change_raw_finding() -> None:
    row, args = case()
    before = deepcopy(row)
    assert reviewed_failure(row, **args)
    assert row == before and row["status"] == "FAILED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested_at", "2026-09-07T08:38:30Z"),
        ("completed_at", "2026-09-07T08:38:40Z"),
        ("operation_type", "RETENTION"),
        ("error", {"code": "NEW_ERROR"}),
        ("workflow_execution_arn", "other"),
        ("target_game_id", "game-other"),
        ("status", "RUNNING"),
        ("operation_id", "op-new-failed"),
        ("backup_snapshot_id", "snap-0123456789abcdef0"),
        ("result", {"unknown": True}),
    ],
)
def test_authority_mismatch_blocks(field: str, value: Any) -> None:
    row, args = case()
    row[field] = value
    assert not reviewed_failure(row, **args)


@pytest.mark.parametrize("domain", ["snapshots", "provenance", "references"])
def test_new_side_effect_blocks(domain: str) -> None:
    row, args = case()
    op = row["operation_id"]
    args[domain] = (
        [{"Tags": [{"Key": "WishicraftOperationId", "Value": op}]}]
        if domain == "snapshots"
        else [{"operation_id": op}]
    )
    assert not reviewed_failure(row, **args)


def test_missing_authority_or_id_only_blocks(monkeypatch: Any) -> None:
    row, args = case()
    assert not reviewed_failure({"operation_id": row["operation_id"]}, **args)
    import wishicraft.retention_authority as module

    monkeypatch.setattr(module, "REVISION", "unknown")
    assert not reviewed_failure(row, **args)


@pytest.mark.parametrize("provision,enabled", [(False, False), (True, False), (True, True)])
def test_release_flags(provision: bool, enabled: bool) -> None:
    assert RetentionRelease.parse(
        dict(schema_version=1, provision=provision, enabled=enabled)
    ) == RetentionRelease(provision, enabled)


@pytest.mark.parametrize("provision,enabled", [(False, True), (1, False), (True, "false")])
def test_invalid_flags(provision: Any, enabled: Any) -> None:
    with pytest.raises(ValueError):
        RetentionRelease(provision, enabled)


def test_canonical_disabled_and_absent_defaults(tmp_path: Path) -> None:
    assert load_retention_release(ROOT, "dev") == RetentionRelease()
    assert load_retention_release(tmp_path, "dev") == RetentionRelease()


def recovery() -> RecoveryRead:
    r = initial_record()
    arn = (
        f"arn:aws:states:{r.region}:{r.account}:execution:wc-dev-retention:"
        f"{r.retention_operation_id}"
    )
    fn = f"arn:aws:lambda:{r.region}:{r.account}:function:wc-dev-retention-task"
    r = replace(
        r,
        execution_arn=arn,
        dispatcher_arn=fn,
        dispatcher_revision="revision-1",
        dispatcher_timeout=120,
        dispatcher_lease_id=PROOF.lease_id,
    )
    now = NOW + timedelta(seconds=2000)
    q = Quiescence(
        arn,
        "FAILED",
        NOW + timedelta(seconds=300),
        NOW + timedelta(seconds=120),
        now,
        fn,
        "revision-1",
        120,
        True,
        True,
        0,
        "history-1",
    )
    return RecoveryRead(
        r,
        PROOF,
        r.snapshot_id,
        DeleteObservation(r.snapshot_id, r.account, r.region, now, True, False),
        "refs-1",
        "holds-1",
        True,
        False,
        True,
        q,
    )


def test_recovery_same_op_only_no_dispatch_unknown_absent_not_success() -> None:
    read = recovery()
    read = replace(read, observation=replace(read.observation, active=False))
    api = Dynamo()
    api.rows["SNAPSHOT#immutable"] = {"immutable": True}
    proof = resume(
        read,
        read,
        new_lease_id="lease-recovery",
        now=read.observation.observed_at,
        repository=repository(api),
    )
    assert proof.owner_operation_id == PROOF.owner_operation_id
    tx = api.transactions[0]
    assert len(tx) == 5
    assert "retention_delete_pending = :snapshot" in tx[0]["Update"]["ConditionExpression"]
    assert "REMOVE" not in json.dumps(tx)
    row = api.rows["DELETION#" + read.record.snapshot_id]
    assert row["request_outcome"] == "OUTCOME_UNKNOWN"
    assert row["phase"] == "RESPONSE_RECORDED" and row["confirmed_at"] is None
    assert row["attempt"] == 1 and api.rows["SNAPSHOT#immutable"] == {"immutable": True}


@pytest.mark.parametrize(
    "change",
    ["nonterminal", "too_early", "ref", "lock", "record", "redrive", "unknown", "identity"],
)
def test_recovery_denies_unproven(change: str) -> None:
    first = recovery()
    fresh = first
    if change == "nonterminal":
        fresh = replace(first, quiescence=replace(first.quiescence, status="RUNNING"))
    if change == "too_early":
        fresh = replace(
            first,
            quiescence=replace(
                first.quiescence, terminal_at=first.observation.observed_at - timedelta(seconds=100)
            ),
        )
    if change == "ref":
        fresh = replace(first, currently_referenced=True)
    if change == "lock":
        fresh = replace(first, pending_snapshot="snap-fffffffffffffffff")
    if change == "record":
        fresh = replace(first, record=replace(first.record, revision=2))
    if change == "redrive":
        fresh = replace(first, quiescence=replace(first.quiescence, redrive_count=1))
    if change == "unknown":
        fresh = replace(first, observation=replace(first.observation, active=None))
    if change == "identity":
        fresh = replace(first, quiescence=replace(first.quiescence, dispatcher_revision="other"))
    api = Dynamo()
    with pytest.raises(ValueError):
        resume(
            first,
            fresh,
            new_lease_id="new",
            now=first.observation.observed_at,
            repository=repository(api),
        )
    assert not api.transactions


def test_future_iam_exact_snapshot_official_keys() -> None:
    p = shared_delete_policy(
        partition="aws",
        region="ap-northeast-1",
        account="123456789012",
        project="wishicraft",
        stage="dev",
        volume_id="vol-0123456789abcdef0",
        snapshot_id="snap-0123456789abcdef0",
    )
    assert p["Resource"] == "arn:aws:ec2:ap-northeast-1::snapshot/snap-0123456789abcdef0"
    conditions: Any = p["Condition"]
    assert (
        conditions["ArnEquals"]["ec2:ParentVolume"]
        == "arn:aws:ec2:ap-northeast-1:123456789012:volume/vol-0123456789abcdef0"
    )
    assert conditions["StringEquals"]["ec2:Owner"] == "123456789012"
    assert conditions["StringEquals"]["aws:ResourceTag/WishicraftBackupScope"] == "shared-volume"
    assert "GameId" not in json.dumps(p)


def test_sdk_http_retryable_response_is_one_send(monkeypatch: Any) -> None:
    from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]

    api = client()
    calls = []

    class Body:
        def stream(self, *a: Any, **kw: Any) -> Any:
            yield (
                b"<Response><Errors><Error><Code>InternalError</Code>"
                b"<Message>synthetic</Message></Error></Errors>"
                b"<RequestID>id</RequestID></Response>"
            )

    def send(request: Any) -> Any:
        calls.append(1)
        return AWSResponse(request.url, 500, {}, Body())

    monkeypatch.setattr(api._endpoint.http_session, "send", send)
    assert (
        Ec2DeleteAdapter(api, region="ap-northeast-1").delete_once(
            snapshot_id="snap-0123456789abcdef0"
        )
        == DeleteRequestOutcome.OUTCOME_UNKNOWN
    )
    assert calls == [1]


def test_quiescence_requires_complete_exact_task_history(capsys: Any) -> None:
    from wishicraft.retention_recovery_reads import read_quiescence

    read = recovery()
    r, q = read.record, read.quiescence

    class Api:
        corrupt = False

        def describe_execution(self, **kw: Any) -> dict[str, Any]:
            return dict(
                executionArn=r.execution_arn,
                name=r.retention_operation_id,
                stateMachineArn=str(r.execution_arn)
                .rsplit(":", 1)[0]
                .replace(":execution:", ":stateMachine:"),
                status="FAILED",
                stopDate=q.terminal_at,
                redriveCount=0,
            )

        def get_execution_history(self, **kw: Any) -> dict[str, Any]:
            if self.corrupt:
                raise RuntimeError(CANARY)
            return {
                "events": [
                    {
                        "id": 1,
                        "taskScheduledEventDetails": {
                            "resourceType": "lambda",
                            "resource": "invoke",
                            "parameters": json.dumps(
                                {
                                    "FunctionName": r.dispatcher_arn,
                                    "Payload": {
                                        "action": "run",
                                        "operation_id": r.retention_operation_id,
                                        "lease_id": r.dispatcher_lease_id,
                                    },
                                }
                            ),
                        },
                    },
                    {"id": 2, "type": "TaskStarted", "previousEventId": 1},
                    {
                        "id": 3,
                        "type": "TaskFailed",
                        "previousEventId": 2,
                        "timestamp": q.last_task_end,
                    },
                    {
                        "id": 4,
                        "type": "ExecutionFailed",
                        "previousEventId": 3,
                        "timestamp": q.terminal_at,
                    },
                ]
            }

        def get_function_configuration(self, **kw: Any) -> dict[str, Any]:
            return dict(
                FunctionArn=r.dispatcher_arn,
                RevisionId=r.dispatcher_revision,
                Timeout=r.dispatcher_timeout,
                Environment={"Variables": {"TOKEN": CANARY}},
            )

    api = Api()
    good = read_quiescence(api, api, r, q.observed_at)
    assert good.status == "FAILED" and CANARY not in str(good)
    api.corrupt = True
    with pytest.raises(ValueError, match="MANUAL_REVIEW_REQUIRED") as error:
        read_quiescence(api, api, r, q.observed_at)
    assert CANARY not in str(error.value) + str(capsys.readouterr())


def test_expired_lease_alone_and_newly_expired_worker_are_not_quiescent() -> None:
    read = recovery()
    fresh = replace(
        read,
        old_lease=replace(
            read.old_lease, lease_expires_at=int(read.observation.observed_at.timestamp()) - 1
        ),
    )
    with pytest.raises(ValueError, match="MANUAL_REVIEW_REQUIRED"):
        fresh.verify(read.observation.observed_at)


def test_owner_wide_lock_and_bin_reads_distinguish_absence_from_not_found() -> None:
    from tests.unit.test_retention_execution_boundaries import AwsReads
    from wishicraft.retention_aws_checks import inspect_candidate

    class Api(AwsReads):
        def describe_locked_snapshots(self, **kw: Any) -> dict[str, Any]:
            assert "SnapshotIds" not in kw
            return {
                "Snapshots": [{"SnapshotId": "snap-fffffffffffffffff", "LockState": "compliance"}]
            }

        def list_snapshots_in_recycle_bin(self, **kw: Any) -> dict[str, Any]:
            assert "SnapshotIds" not in kw
            return {"Snapshots": [{"SnapshotId": "snap-fffffffffffffffff"}]}

    api = Api()
    assert not inspect_candidate(
        api, api, snapshot_id="snap-0123456789abcdef0", account="123456789012", tags={}
    ).issues


def test_bundle_evidence_digests_match_adopted_sources() -> None:
    import hashlib

    a = _authority()
    for name, expected in a["evidence"].items():
        assert hashlib.sha256((ROOT / "docs/evidence" / name).read_bytes()).hexdigest() == expected
    assert a["adoption_commit"] == "328937ddd8037d0c297089c9ae782b1c730b4bc6"


@pytest.mark.parametrize("provisioned", ["0", "1"])
def test_handler_disabled_never_constructs_runtime(monkeypatch: Any, provisioned: str) -> None:
    from tests.unit.test_retention_workflow_lambda import event
    from wishicraft import retention_workflow_lambda as task

    monkeypatch.setenv("RETENTION_PROVISIONED", provisioned)
    monkeypatch.setenv("RETENTION_DELETE_ENABLED", "0")

    def forbidden() -> Any:
        raise AssertionError("AWS client must not be created")

    monkeypatch.setattr(task, "_get_runtime", forbidden)
    value = task.handler({**event(), "execution_mode": "DELETE_ONE"}, None)
    assert value["status"] == "NO_DELETE" and value["delete_action_count"] == 0


def test_enabled_dry_run_stays_dry_run(monkeypatch: Any) -> None:
    from tests.unit.test_retention_workflow_lambda import Runtime, event
    from wishicraft import retention_runtime
    from wishicraft import retention_workflow_lambda as task

    monkeypatch.setenv("RETENTION_PROVISIONED", "1")
    monkeypatch.setenv("RETENTION_DELETE_ENABLED", "1")
    runtime = Runtime()
    monkeypatch.setattr(task, "_runtime", runtime)

    def forbidden(*a: Any, **kw: Any) -> Any:
        raise AssertionError("must stay dry-run")

    monkeypatch.setattr(retention_runtime, "bind", forbidden)
    assert task.handler(event(), None)["status"] == "SUCCEEDED"
    assert runtime.operations.completions[0]["result"]["delete_action_count"] == 0  # type: ignore[index]


@pytest.mark.parametrize("pending", [False, True])
def test_formal_future_handler_zero_or_pending(monkeypatch: Any, pending: bool) -> None:
    from tests.unit.test_retention_workflow_lambda import Runtime, event
    from wishicraft import retention_runtime
    from wishicraft import retention_workflow_lambda as task

    monkeypatch.setenv("RETENTION_PROVISIONED", "1")
    monkeypatch.setenv("RETENTION_DELETE_ENABLED", "1")
    runtime = Runtime()
    monkeypatch.setattr(task, "_runtime", runtime)

    class Engine:
        def prepare(self, proof: Any) -> Any:
            return "plan"

        def execute(self, plan: Any, proof: Any, **kw: Any) -> Any:
            assert kw["actor"] == "ADMIN" and kw["mode"] == "DELETE_ONE"
            return initial_record() if pending else None

    monkeypatch.setattr(retention_runtime, "bind", lambda *a: (Engine(), "ADMIN"))
    result = task.handler({**event(), "execution_mode": "DELETE_ONE"}, None)
    assert result["status"] == ("MANUAL_REVIEW_REQUIRED" if pending else "SUCCEEDED")
    assert len(runtime.operations.completions) == (0 if pending else 1)
