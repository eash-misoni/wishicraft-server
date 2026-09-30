"""Standalone container driver: standard library + SDK + selected asset only.

Never imports tests, CLI modules, repository source, or developer dependencies.
Only external SDK boundaries are fake; application modules and readers are real.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import sys
import traceback
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

sys.path.insert(0, "/asset")


def network(event: str, args: Any) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("NETWORK_FORBIDDEN")


sys.addaudithook(network)
assert platform.system() == "Linux" and sys.version_info[:2] == (3, 12)
assert sys.flags.isolated and not any(k.startswith("AWS_") for k in os.environ)
assert importlib.util.find_spec("yaml") is None
assert importlib.util.find_spec("pytest") is None
assert importlib.util.find_spec("aws_cdk") is None
import boto3  # type: ignore[import-untyped]  # noqa: E402
import botocore  # type: ignore[import-untyped]  # noqa: E402
from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]  # noqa: E402

CLIENT_CALLS: list[str] = []


def forbidden_client(service: str, **kw: Any) -> Any:
    CLIENT_CALLS.append(service)
    raise AssertionError("UNEXPECTED_CLIENT")


boto3.client = forbidden_client
PAYLOAD = dict(
    schema_version=1,
    action="run",
    execution_mode="DELETE_ONE",
    operation_id="op-diagnostic-526cca31-87f1-46be-b717-59a40298ee0b",
    lease_id="lease-diagnostic-c57244c0-442b-4487-bbca-4c944cbe595f",
)


def wire(value: dict[str, Any]) -> dict[str, Any]:
    return {k: TypeSerializer().serialize(v) for k, v in value.items()}


def load_fixture() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            Path("/fixture/recovery.json").read_text(),
            object_hook=lambda v: (
                datetime.fromisoformat(v["$datetime"]) if set(v) == {"$datetime"} else v
            ),
        ),
    )


class Api:
    """Only explicitly modeled external responses; unknown methods fail immediately."""

    meta = SimpleNamespace(
        region_name="ap-northeast-1",
        config=SimpleNamespace(retries={"total_max_attempts": 1, "mode": "standard"}),
    )

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.f = fixture
        self.tables = deepcopy(fixture["tables"])
        self.writes: list[Any] = []

    def get_item(self, **kw: Any) -> Any:
        assert kw["ConsistentRead"] is True
        key = next(iter(kw["Key"].values()))["S"]
        row = self.tables[kw["TableName"]].get(key)
        return {"Item": deepcopy(row)} if row is not None else {}

    def scan(self, **kw: Any) -> Any:
        assert kw["ConsistentRead"] is True
        return {"Items": deepcopy(list(self.tables[kw["TableName"]].values()))}

    def describe_table(self, **kw: Any) -> Any:
        return {
            "Table": {
                "TableArn": "arn:aws:dynamodb:ap-northeast-1:"
                + self.f["record"]["account"]
                + ":table/"
                + kw["TableName"]
            }
        }

    def get_caller_identity(self, **kw: Any) -> Any:
        return {"Account": self.f["record"]["account"]}

    def describe_snapshots(self, **kw: Any) -> Any:
        return {"Snapshots": deepcopy(self.f["snapshots"])}

    def describe_images(self, **kw: Any) -> Any:
        return {"Images": []}

    def describe_snapshot_attribute(self, **kw: Any) -> Any:
        return {"SnapshotId": kw["SnapshotId"], "CreateVolumePermissions": []}

    def describe_locked_snapshots(self, **kw: Any) -> Any:
        return {"Snapshots": []}

    def list_snapshots_in_recycle_bin(self, **kw: Any) -> Any:
        return {"Snapshots": []}

    def list_rules(self, **kw: Any) -> Any:
        return {"Rules": []}

    def describe_execution(self, **kw: Any) -> Any:
        return deepcopy(self.f["execution"])

    def get_execution_history(self, **kw: Any) -> Any:
        return deepcopy(self.f["history"])

    def get_function_configuration(self, **kw: Any) -> Any:
        return deepcopy(self.f["function"])

    def describe_volumes(self, **kw: Any) -> Any:
        return {
            "Volumes": [
                dict(
                    VolumeId="vol-data",
                    AvailabilityZone="ap-northeast-1a",
                    Encrypted=True,
                    Attachments=[
                        dict(
                            InstanceId="i-target",
                            Device="/dev/sdf",
                            State="attached",
                            DeleteOnTermination=False,
                        )
                    ],
                )
            ]
        }

    def delete_item(self, **kw: Any) -> Any:
        raise AssertionError("unexpected direct delete")

    def update_item(self, **kw: Any) -> Any:
        self.writes.append(deepcopy(kw))
        return {}

    def transact_write_items(self, **kw: Any) -> Any:
        self.writes.append(deepcopy(kw))
        for action in kw["TransactItems"]:
            if "Put" in action:
                p = action["Put"]
                self.tables[p["TableName"]][p["Item"]["provenance_key"]["S"]] = deepcopy(p["Item"])
            if (
                "Update" in action
                and action["Update"].get("UpdateExpression") == "REMOVE retention_delete_pending"
            ):
                u = action["Update"]
                lock = self.tables["locks"]["minecraft-control"]
                v = u["ExpressionAttributeValues"]
                assert lock["retention_delete_pending"] == v[":snapshot"]
                assert lock["owner_operation_id"] == v[":operation"]
                assert lock["lease_id"] == v[":lease"]
                assert Decimal(lock["lease_expires_at"]["N"]) >= Decimal(v[":now"]["N"])
                del lock["retention_delete_pending"]
        return {}


def configure() -> None:
    os.environ.update(
        dict(
            AWS_REGION="ap-northeast-1",
            AWS_ACCOUNT_ID="123456789012",
            SYSTEM_ID="wishicraft-main",
            PROJECT="wishicraft",
            STAGE="dev",
            GAME_ID="game-vanilla-main",
            DATA_VOLUME_ID="vol-data",
            DATA_VOLUME_DEVICE="/dev/sdf",
            AVAILABILITY_ZONE="ap-northeast-1a",
            OPERATIONS_TABLE="operations",
            LOCKS_TABLE="locks",
            SYSTEM_STATE_TABLE="states",
            GAMES_TABLE="games",
            BACKUPS_TABLE="backups",
            GLOBAL_LOCK_NAME="minecraft-control",
            LOCK_LEASE_SECONDS="900",
            RETENTION_WORKFLOW_NAME="wc-dev-retention",
            AWS_LAMBDA_FUNCTION_NAME="wc-dev-retention-task",
        )
    )


def dry_run() -> None:
    from wishicraft import retention_workflow_lambda as module

    configure()
    f = load_fixture()
    f["snapshots"] = []
    api = Api(f)
    api.tables["backups"] = {}
    api.tables["locks"]["minecraft-control"] = wire(
        dict(
            resource_id="wishicraft-main",
            owner_operation_id="op-dry-test",
            lease_id="lease-test",
            lease_expires_at=int(datetime.now(UTC).timestamp()) + 900,
        )
    )

    def client(service: str, **kw: Any) -> Any:
        assert service in {"dynamodb", "ec2", "rbin"}
        CLIENT_CALLS.append(service)
        return api

    boto3.client = client
    observed = datetime.now(UTC).isoformat()
    event = dict(
        schema_version=1,
        action="run",
        operation_id="op-dry-test",
        lease_id="lease-test",
        state=dict(
            game_id="game-vanilla-main",
            health="HEALTHY",
            discrepancies=[],
            observation_errors=[],
            observed_at=observed,
            observation=dict(
                observed_at=observed,
                expected_game_id="game-vanilla-main",
                instance_id="i-target",
                ec2_state="stopped",
            ),
        ),
    )
    result = module.handler(event, None)
    assert result == {"status": "SUCCEEDED", "reason": "within-retention-limit"}, result
    assert set(CLIENT_CALLS) == {"dynamodb", "ec2", "rbin"}
    assert len(api.writes) == 3  # lease renewal, step, real completion transaction
    tx = api.writes[-1]["TransactItems"]
    assert tx[0]["Update"]["ExpressionAttributeValues"][":status"] == {"S": "SUCCEEDED"}
    assert "Delete" in tx[1]  # synthetic global Lock only; no EC2 mutation method exists


def recovery() -> None:
    from wishicraft.operation import LeaseProof, LeaseRepository
    from wishicraft.retention import RetentionContext
    from wishicraft.retention_deletion import DeletionPhase
    from wishicraft.retention_deletion_repository import DeletionRepository
    from wishicraft.retention_execution import RetentionExecution
    from wishicraft.retention_execution_reads import ExecutionReads
    from wishicraft.retention_recovery_reads import read_recovery
    from wishicraft.retention_runtime import bind

    configure()
    f = load_fixture()
    api = Api(f)
    now = f["now"]
    repo = DeletionRepository(
        api,
        backups_table="backups",
        locks_table="locks",
        state_table="states",
        operations_table="operations",
        lock_name="minecraft-control",
    )
    record = repo.read_operation(f["record"]["retention_operation_id"])
    assert record is not None and repo.read_snapshot(record.snapshot_id) == record
    assert type(record.dispatcher_timeout) is int and record.dispatcher_timeout == 120
    reads = ExecutionReads(
        ec2=api,
        rbin=api,
        dynamodb=api,
        sts=api,
        context=RetentionContext(**f["context"]),
        region=record.region,
        system_id=record.system_id,
        operation_id=record.retention_operation_id,
        tables=dict(state="states", games="games", backups="backups", operations="operations"),
        holds={},
        hold_revision="reviewed-live-holds",
        clock=lambda: now,
    )
    args = dict(
        record=record,
        reads=reads,
        dynamodb=api,
        locks_table="locks",
        lock_name="minecraft-control",
        states=api,
        functions=api,
        now=now,
        journal=repo,
    )
    before = deepcopy(api.tables)
    result = read_recovery(**args)
    result.verify(now)
    assert type(result.old_lease.lease_expires_at) is int and api.tables == before
    for bad in [{"N": "1.5"}, {"BOOL": True}, {"N": "NaN"}, {"N": str(int(now.timestamp()) + 1)}]:
        api.tables["locks"]["minecraft-control"]["lease_expires_at"] = bad
        try:
            read_recovery(**args)
        except ValueError as error:
            assert str(error) == "MANUAL_REVIEW_REQUIRED"
        else:
            raise AssertionError("unsafe lease accepted")
    api.tables = deepcopy(before)
    # Normal reconciliation uses the actual wire pair and real lease checks.
    record = record.advance(
        phase=DeletionPhase.RESPONSE_RECORDED,
        request_outcome="EXPLICIT_SUCCESS",
        reconciliation="OUTCOME_UNKNOWN",
    )
    api.tables["backups"]["DELETION#" + record.snapshot_id] = wire(record.item())
    f["snapshots"] = []
    lock = api.tables["locks"]["minecraft-control"]
    lock["lease_expires_at"] = {"N": str(int(now.timestamp()) + 900)}
    proof = LeaseProof(
        record.system_id,
        record.retention_operation_id,
        lock["lease_id"]["S"],
        int(now.timestamp()) + 900,
    )
    leases = LeaseRepository(api, table_name="locks", lock_name="minecraft-control")
    engine = RetentionExecution(reads=reads, leases=leases, journal=repo, clock=lambda: now)
    first = engine.reconcile(proof)
    assert first and first.phase == DeletionPhase.RESPONSE_RECORDED
    now += timedelta(seconds=11)
    final = engine.reconcile(proof)
    assert final and final.phase == DeletionPhase.FORMALLY_DELETED
    assert "retention_delete_pending" not in lock
    # Future factory actually executes its call-time imports and binding reads, no dispatch.
    runtime = SimpleNamespace(
        dynamodb=api,
        leases=leases,
        context=reads.context,
        ec2=api,
        recycle_bin=api,
        system_id=record.system_id,
        backups_table="backups",
    )
    lock["lease_expires_at"] = {"N": str(int(datetime.now(UTC).timestamp()) + 900)}
    api.tables["operations"][proof.owner_operation_id] = wire(
        dict(
            operation_id=proof.owner_operation_id,
            operation_type="RETENTION",
            requested_by="ADMIN",
            status="RUNNING",
            lease_id=proof.lease_id,
            workflow_execution_arn=record.execution_arn,
        )
    )

    class Session:
        def client(self, service: str, **kw: Any) -> Any:
            assert service in {"lambda", "sts", "ec2"}
            return api

    for enabled in ("0", "1"):
        os.environ.update(RETENTION_PROVISIONED="1", RETENTION_DELETE_ENABLED=enabled)
        bound, actor = bind(runtime, proof, Session())
        assert actor == "ADMIN" and (bound.adapter is not None) == (enabled == "1")


def main() -> None:
    mode = sys.argv[1]
    os.environ.update(RETENTION_PROVISIONED="1", RETENTION_DELETE_ENABLED="0")
    if mode == "imports":
        for handler_name in sys.argv[2:]:
            module_name, fn = handler_name.rsplit(".", 1)
            assert callable(getattr(importlib.import_module(module_name), fn))
    elif mode == "old":
        from wishicraft.retention_workflow_lambda import handler

        try:
            handler(PAYLOAD, None)
        except ModuleNotFoundError as error:
            assert error.name == "yaml"
        else:
            raise AssertionError("old artifact did not reproduce")
        assert not CLIENT_CALLS
    elif mode == "disabled":
        from wishicraft.retention_workflow_lambda import handler

        for provision in ("0", "1"):
            os.environ["RETENTION_PROVISIONED"] = provision
            assert handler(PAYLOAD, None) == dict(
                status="NO_DELETE",
                reason="DELETE_ONE_NOT_RELEASED",
                deletion_authorized=False,
                planned_delete_ids=[],
                delete_action_count=0,
            )
        for provision, enabled in [("0", "1"), ("x", "0"), ("1", "true")]:
            os.environ.update(RETENTION_PROVISIONED=provision, RETENTION_DELETE_ENABLED=enabled)
            try:
                handler(PAYLOAD, None)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid flags accepted")
        assert not CLIENT_CALLS and "wishicraft.retention_runtime" not in sys.modules
        assert "wishicraft.maintenance_operator" not in sys.modules
    elif mode == "dry-run":
        dry_run()
    elif mode == "recovery":
        recovery()
    else:
        raise AssertionError("unknown scenario")
    for name, module in tuple(sys.modules.items()):
        if name.startswith("wishicraft"):
            if module.__file__ is None:
                # Resource-only namespace packages have no __file__; every search
                # location must still be exclusively in this same selected asset.
                assert module.__spec__ is not None
                locations = module.__spec__.submodule_search_locations
                assert locations and all(Path(p).is_relative_to("/asset") for p in locations)
            else:
                assert Path(module.__file__).is_relative_to("/asset")
    if mode != "old":
        assert "wishicraft.maintenance_operator" not in sys.modules
        assert "wishicraft.config" not in sys.modules and "yaml" not in sys.modules
    print(
        json.dumps(
            dict(
                scenario=mode,
                status="PASS",
                python=platform.python_version(),
                os=platform.system(),
                architecture=platform.machine(),
                boto3=boto3.__version__,
                botocore=botocore.__version__,
                sdk_source=boto3.__file__,
                network="disabled",
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No raw exception/payload/env values in CI output.
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "scenario": sys.argv[1],
                    "location": [
                        [Path(f.filename).name, f.lineno]
                        for f in traceback.extract_tb(error.__traceback__)
                    ],
                }
            )
        )
        raise SystemExit(1) from None
