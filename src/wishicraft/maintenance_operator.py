"""maintenance begin/status/end/incident; never starts or stops the host."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]
from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]

from wishicraft.config import load_configuration
from wishicraft.endpoint import DnsState, Route53Observer
from wishicraft.maintenance import lease_active, new_lease
from wishicraft.maintenance_repository import transition
from wishicraft.monitoring_telemetry import fresh
from wishicraft.naming import resource_name
from wishicraft.reconcile import TargetResolver


def item(api: Any, table: str, key: str, value: str) -> dict[str, Any]:
    raw = api.get_item(TableName=table, Key={key: {"S": value}}, ConsistentRead=True).get(
        "Item", {}
    )
    decoder = TypeDeserializer()
    return {k: decoder.deserialize(v) for k, v in raw.items()}


def invoke(api: Any, function: str) -> dict[str, Any]:
    response = api.invoke(
        FunctionName=function,
        InvocationType="RequestResponse",
        Payload=b'{"schema_version":1,"operation":"reconcile"}',
    )
    if response.get("FunctionError"):
        raise RuntimeError("maintenance Reconcile failed; inspect existing Lambda logs")
    value = json.loads(response["Payload"].read())
    if not isinstance(value, dict):
        raise ValueError("invalid Reconcile response")
    return value


def safe_state(state: dict[str, Any], *, instance_id: str, actual: str, now: datetime) -> None:
    observed = state.get("observation", {})
    if not (
        actual == "stopped"
        and state.get("target_instance_id") == instance_id
        and state.get("desired_state") == "STOPPED"
        and state.get("current_operation_id") is None
        and state.get("health") == "HEALTHY"
        and state.get("discrepancies") == []
        and state.get("observation_errors") == []
        and fresh(state.get("observed_at"), now, 120)
        and observed.get("instance_id") == instance_id
        and observed.get("ec2_state") == "stopped"
        and observed.get("dns_state") == "absent"
        and observed.get("runtime_ready") is False
        and observed.get("host_runtime_state") == "not-running"
        and observed.get("observed_active_game_id") is None
    ):
        raise ValueError("maintenance requires fresh STOPPED/HEALTHY with DNS/runtime absent")


def no_external_work(session: Any, *, stack: str, instance_id: str) -> None:
    cf, sfn, ssm = (
        session.client(service) for service in ("cloudformation", "stepfunctions", "ssm")
    )
    machines = [
        r["PhysicalResourceId"]
        for page in cf.get_paginator("list_stack_resources").paginate(StackName=stack)
        for r in page["StackResourceSummaries"]
        if r["ResourceType"] == "AWS::StepFunctions::StateMachine"
    ]
    if not machines:
        raise ValueError("no deployed workflows resolved")
    for machine in machines:
        for page in sfn.get_paginator("list_executions").paginate(
            stateMachineArn=machine, statusFilter="RUNNING"
        ):
            if page["executions"]:
                raise ValueError("active workflow prevents maintenance transition")
    for page in ssm.get_paginator("list_commands").paginate(InstanceId=instance_id):
        if any(
            command["Status"] not in {"Success", "Failed", "Cancelled", "TimedOut"}
            for command in page["Commands"]
        ):
            raise ValueError("active or unknown SSM command prevents maintenance transition")
    for page in ssm.get_paginator("describe_sessions").paginate(
        State="Active", Filters=[{"key": "Target", "value": instance_id}]
    ):
        if page["Sessions"]:
            raise ValueError("active SSM session prevents maintenance transition")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("begin", "status", "end", "incident"))
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--id")
    parser.add_argument("--reason")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    config = load_configuration(Path(__file__).resolve().parents[2], args.stage)
    stage, project = config.stage, config.project
    session = boto3.Session(profile_name=args.profile, region_name=stage.aws_region)
    identity = session.client("sts").get_caller_identity()
    if identity["Account"] != stage.aws_account_id:
        raise ValueError("AWS caller account does not match canonical stage")
    function = resource_name(project.resource_prefix, stage.stage, "admission")
    api = session.client("lambda")
    env = api.get_function_configuration(FunctionName=function)["Environment"]["Variables"]
    if env.get("SYSTEM_ID") != project.system_id:
        raise ValueError("deployed System identity differs")
    ddb = session.client("dynamodb")
    state = item(ddb, env["SYSTEM_STATE_TABLE"], "system_id", project.system_id)
    now = datetime.now(UTC)
    if args.action == "status":
        print(
            json.dumps(
                {
                    "stage": stage.stage,
                    "maintenance": state.get("maintenance"),
                    "active": lease_active(state.get("maintenance"), now=now),
                    "admission_closed": state.get("maintenance", {}).get("status")
                    not in (None, "ENDED"),
                },
                default=int,
            )
        )
        return
    if not args.execute or not args.id or not args.evidence_root:
        parser.error("mutation requires --execute, --id and a new --evidence-root")
    if env.get("MAINTENANCE_SCHEMA_VERSION") != "1":
        raise ValueError("maintenance admission fence is not deployed")
    # Reserve a never-overwritten evidence directory before any external mutation.
    args.evidence_root.mkdir(parents=True, exist_ok=False)
    if args.action != "incident":
        ec2 = session.client("ec2")
        target = TargetResolver(ec2, project=project.project_slug, stage=stage.stage).resolve()
        no_external_work(
            session, stack=f"WishicraftControlPlaneStack-{stage.stage}", instance_id=target
        )
        if item(ddb, env["LOCKS_TABLE"], "lock_name", stage.global_lock_name):
            raise ValueError("Lock exists; automatic recovery is forbidden")
        invoke(api, resource_name(project.resource_prefix, stage.stage, "reconcile"))
        state = item(ddb, env["SYSTEM_STATE_TABLE"], "system_id", project.system_id)
        actual = ec2.describe_instances(InstanceIds=[target])["Reservations"][0]["Instances"][0]
        now = datetime.now(UTC)
        safe_state(state, instance_id=target, actual=actual["State"]["Name"], now=now)
        dns = Route53Observer(
            session.client("route53"),
            hosted_zone_id=stage.route53_hosted_zone_id,
            record_name=stage.route53_record_name,
        ).observe()
        if dns.state is not DnsState.ABSENT:
            raise ValueError("DNS must be absent")
        game_id = state.get("desired_game_id") or state["game_id"]
        game = item(ddb, env["GAMES_TABLE"], "game_id", game_id)
        if game.get("lifecycle_state") != "ACTIVE":
            raise ValueError("selected Game lifecycle is not safe")
    if args.action == "begin":
        lease = new_lease(
            lease_id=args.id,
            actor=identity["Arn"],
            reason=args.reason,
            stage=stage.stage,
            duration=args.duration_seconds,
            now=now,
        )
    else:
        previous = state.get("maintenance")
        if not isinstance(previous, dict) or previous.get("id") != args.id:
            raise ValueError("maintenance identity mismatch")
        lease = dict(previous)
        if args.action == "end":
            lease.update(status="ENDED", ended_at=int(now.timestamp()), ended_by=identity["Arn"])
        else:
            if not args.reason:
                raise ValueError("incident requires a reason")
            lease.update(
                status="INCIDENT",
                incident_at=int(now.timestamp()),
                incident_by=identity["Arn"],
                incident_reason=args.reason,
            )
    (args.evidence_root / "before.json").write_text(
        json.dumps(
            {"state": state, "requested": lease, "action": args.action}, default=int, indent=2
        )
        + "\n"
    )
    transition(
        ddb,
        table=env["SYSTEM_STATE_TABLE"],
        locks_table=env["LOCKS_TABLE"],
        system_id=project.system_id,
        lock_name=stage.global_lock_name,
        state=state,
        lease=lease,
        event=args.action,
        now=now,
    )
    after = item(ddb, env["SYSTEM_STATE_TABLE"], "system_id", project.system_id)
    if after.get("maintenance") != lease:
        raise RuntimeError("maintenance read-back differs; inspect audit before retry")
    (args.evidence_root / "after.json").write_text(json.dumps(lease, default=int, indent=2) + "\n")
    print(json.dumps({"stage": stage.stage, "maintenance": lease}, default=int))


if __name__ == "__main__":
    main()
