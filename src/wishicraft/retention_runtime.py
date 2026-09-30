"""Future server-owned formal RETENTION binding. Canonical deletion remains disabled."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from wishicraft.dynamodb_read import item
from wishicraft.operation import LeaseProof
from wishicraft.retention_authority import HOLD_REVISION, REVISION
from wishicraft.retention_delete_adapter import Ec2DeleteAdapter, delete_client
from wishicraft.retention_deletion_repository import DeletionRepository
from wishicraft.retention_execution import RetentionExecution
from wishicraft.retention_execution_reads import ExecutionReads
from wishicraft.retention_release import environment_release as environment_release


def bind(runtime: Any, proof: LeaseProof, session: Any) -> tuple[RetentionExecution, str]:
    release = environment_release()
    if not release.provision:
        raise ValueError("RETENTION_NOT_PROVISIONED")
    region = os.environ["AWS_REGION"]
    account = runtime.context.owner_id
    now = datetime.now(UTC)
    runtime.leases.verify_owned(proof, now=now)
    op = item(
        runtime.dynamodb, os.environ["OPERATIONS_TABLE"], "operation_id", proof.owner_operation_id
    )
    execution = (
        f"arn:aws:states:{region}:{account}:execution:"
        f"{os.environ['RETENTION_WORKFLOW_NAME']}:{proof.owner_operation_id}"
    )
    if (
        op.get("operation_id") != proof.owner_operation_id
        or op.get("operation_type") != "RETENTION"
        or op.get("requested_by") not in {"ADMIN", "CLI"}
        or op.get("status") not in {"PENDING", "RUNNING"}
        or op.get("lease_id") != proof.lease_id
        or op.get("workflow_execution_arn") != execution
        or not runtime.context.shared_volume
    ):
        raise ValueError("FORMAL_RETENTION_IDENTITY_REQUIRED")
    fn = os.environ["AWS_LAMBDA_FUNCTION_NAME"]
    config = session.client("lambda", region_name=region).get_function_configuration(
        FunctionName=fn
    )
    arn = f"arn:aws:lambda:{region}:{account}:function:{fn}"
    if (
        config.get("FunctionArn") != arn
        or config.get("Handler") != "wishicraft.retention_workflow_lambda.handler"
    ):
        raise ValueError("DISPATCHER_IDENTITY_UNKNOWN")
    journal = DeletionRepository(
        runtime.dynamodb,
        backups_table=runtime.backups_table,
        locks_table=os.environ["LOCKS_TABLE"],
        state_table=os.environ["SYSTEM_STATE_TABLE"],
        operations_table=os.environ["OPERATIONS_TABLE"],
        lock_name=os.environ["GLOBAL_LOCK_NAME"],
    )
    reads = ExecutionReads(
        ec2=runtime.ec2,
        rbin=runtime.recycle_bin,
        dynamodb=runtime.dynamodb,
        sts=session.client("sts", region_name=region),
        context=runtime.context,
        region=region,
        system_id=runtime.system_id,
        operation_id=proof.owner_operation_id,
        tables={
            "state": os.environ["SYSTEM_STATE_TABLE"],
            "operations": os.environ["OPERATIONS_TABLE"],
            "games": os.environ["GAMES_TABLE"],
            "backups": runtime.backups_table,
        },
        holds={},
        hold_revision=HOLD_REVISION + ":" + REVISION,
        clock=lambda: datetime.now(UTC),
        historical_authority=True,
    )
    engine = RetentionExecution(
        reads=reads,
        leases=runtime.leases,
        journal=journal,
        clock=lambda: datetime.now(UTC),
        adapter=Ec2DeleteAdapter(delete_client(session, region=region), region=region)
        if release.enabled
        else None,
        dispatcher=(execution, arn, config["RevisionId"], config["Timeout"]),
    )

    return engine, op["requested_by"]
