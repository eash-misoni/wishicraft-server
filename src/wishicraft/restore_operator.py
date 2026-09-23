"""Operator-only RESTORE checkpoints. Every mutation requires an active planned maintenance lease.

Use the existing maintenance operator to begin/end; use normal Admission for BACKUP/START/STOP.
This entrypoint never starts a Step Functions execution or grants application EBS permissions.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shlex
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from wishicraft.config import load_configuration
from wishicraft.endpoint import DnsState, Route53Observer
from wishicraft.game_creation import registry_ids
from wishicraft.maintenance import lease_active, maintenance_metrics, new_lease
from wishicraft.maintenance_operator import invoke, item, no_external_work, safe_state
from wishicraft.maintenance_repository import transition
from wishicraft.reconcile import TargetResolver
from wishicraft.restore_repository import RestoreRepository
from wishicraft.restore_source import make_plan, request_operation, verified_snapshot
from wishicraft.restore_volume import RestoreVolume
from wishicraft.retention import parse_rfc3339


def normalized(value: Any) -> Any:
    return json.loads(json.dumps(value, default=int))


def lifecycle(
    state: dict[str, Any], lock: dict[str, Any], *, maintenance_id: str, stage: str, now: datetime
) -> dict[str, Any]:
    lease = state.get("maintenance", {})
    if (
        not lease_active(lease, now=now)
        or lease.get("id") != maintenance_id
        or lease.get("stage") != stage
    ):
        raise ValueError("RESTORE_REQUIRES_PLANNED_MAINTENANCE")
    if (
        state.get("desired_state") != "STOPPED"
        or state.get("current_operation_id") is not None
        or lock
    ):
        raise ValueError("RESTORE_ACTIVE_OPERATION_OR_LOCK")
    return dict(lease)


def host_command(envelope: dict[str, Any]) -> str:
    artifacts = Path(__file__).with_name("artifacts")
    envelope = {
        **envelope,
        "helper_updates": {
            name: (artifacts / name).read_text() for name in ("reset_worlds.py", "world_import.py")
        },
    }
    tree = (artifacts / "restore_tree.py").read_text()
    source = (artifacts / "restore_host.py").read_text()
    source = source.replace("from wishicraft.artifacts import restore_tree", "")
    source = source.replace("from wishicraft.artifacts import targeted_runtime as host", "")
    source = source.replace("from __future__ import annotations", "")
    bootstrap = (
        "import sys,types,importlib.machinery,json\n"
        "sys.path.insert(0,'/usr/local/libexec/wishicraft')\n"
        "host=importlib.machinery.SourceFileLoader('restore_runtime',"
        "'/usr/local/libexec/wishicraft/operation-v2').load_module()\n"
        "restore_tree=types.ModuleType('restore_tree')\n"
        "exec("
        + repr(tree)
        + ",restore_tree.__dict__)\n"
        + source
        + "\nprint(json.dumps(run("
        + repr(envelope)
        + ")))\n"
    )
    encoded = base64.b64encode(zlib.compress(bootstrap.encode())).decode()
    return "python3 -c " + shlex.quote(
        "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(encoded) + ")))"
    )


class Operator:
    def __init__(self, session: Any, *, root: Path, stage: str, maintenance_id: str) -> None:
        self.cfg = load_configuration(root, stage)
        self.session, self.stage, self.maintenance_id = session, stage, maintenance_id
        self.now = datetime.now(UTC)
        identity = session.client("sts").get_caller_identity()
        if identity["Account"] != self.cfg.stage.aws_account_id:
            raise ValueError("RESTORE_CALLER_ACCOUNT")
        self.ec2 = session.client("ec2", config=Config(retries={"total_max_attempts": 1}))
        self.ddb, self.functions = session.client("dynamodb"), session.client("lambda")
        self.ssm = session.client("ssm", config=Config(retries={"total_max_attempts": 1}))
        self.prefix = self.cfg.project.resource_prefix + "-" + stage + "-"
        self.env = self.functions.get_function_configuration(
            FunctionName=self.prefix + "admission"
        )["Environment"]["Variables"]
        if (
            self.env.get("SYSTEM_ID") != self.cfg.project.system_id
            or self.env.get("MAINTENANCE_SCHEMA_VERSION") != "1"
        ):
            raise ValueError("RESTORE_DEPLOYED_FENCE")
        self.target = TargetResolver(
            self.ec2, project=self.cfg.project.project_slug, stage=stage
        ).resolve()
        runtime_env = self.functions.get_function_configuration(
            FunctionName=self.prefix + "start-task"
        )["Environment"]["Variables"]
        if runtime_env.get("SYSTEM_ID") != self.cfg.project.system_id:
            raise ValueError("RESTORE_RUNTIME_SYSTEM")
        self.runtime_digest = runtime_env["RUNTIME_CONFIG_DIGEST"]
        self.repo = RestoreRepository(
            self.ddb,
            state_table=self.env["SYSTEM_STATE_TABLE"],
            games_table=self.env["GAMES_TABLE"],
            locks_table=self.env["LOCKS_TABLE"],
            system_id=self.cfg.project.system_id,
            lock_name=self.cfg.stage.global_lock_name,
        )

    def state(self) -> dict[str, Any]:
        return dict(
            normalized(
                item(
                    self.ddb,
                    self.env["SYSTEM_STATE_TABLE"],
                    "system_id",
                    self.cfg.project.system_id,
                )
            )
        )

    def preflight(self, *, external_work: bool = False) -> tuple[dict[str, Any], str]:
        state = self.state()
        self.now = datetime.now(UTC)
        lease = lifecycle(
            state,
            item(self.ddb, self.env["LOCKS_TABLE"], "lock_name", self.cfg.stage.global_lock_name),
            maintenance_id=self.maintenance_id,
            stage=self.stage,
            now=self.now,
        )
        if not external_work:
            no_external_work(
                self.session,
                stack="WishicraftControlPlaneStack-" + self.stage,
                instance_id=self.target,
            )
        actual = self.ec2.describe_instances(InstanceIds=[self.target])["Reservations"][0][
            "Instances"
        ][0]
        if actual["Placement"]["AvailabilityZone"] != self.cfg.stage.availability_zone:
            raise ValueError("RESTORE_HOST_AZ")
        if (
            Route53Observer(
                self.session.client("route53"),
                hosted_zone_id=self.cfg.stage.route53_hosted_zone_id,
                record_name=self.cfg.stage.route53_record_name,
            )
            .observe()
            .state
            is not DnsState.ABSENT
        ):
            raise ValueError("RESTORE_DNS_PRESENT")
        return lease, str(actual["State"]["Name"])

    def idle_host(self) -> tuple[dict[str, Any], str]:
        lease, actual = self.preflight()
        invoke(self.functions, self.prefix + "reconcile")
        state = self.state()
        now = datetime.now(UTC)
        if actual == "stopped":
            safe_state(state, instance_id=self.target, actual=actual, now=now)
        elif actual == "running":
            obs = state.get("observation", {})
            expected = {
                "instance_id": self.target,
                "ec2_state": "running",
                "ssm_state": "online",
                "docker_state": "active",
                "mount_state": "expected",
                "container_state": "not-found",
                "host_runtime_state": "not-running",
                "minecraft_service_state": "not-running",
                "minecraft_protocol_state": "not-applicable",
                "runtime_ready": False,
                "observed_active_game_id": None,
                "dns_state": "absent",
            }
            if (
                state.get("observation_errors") != []
                or state.get("discrepancies") != ["dns-missing-when-required"]
                or any(obs.get(k) != v for k, v in expected.items())
                or not 0 <= (now - parse_rfc3339(state["observed_at"])).total_seconds() <= 120
            ):
                raise ValueError("RESTORE_HOST_NOT_IDLE")
        else:
            raise ValueError("RESTORE_HOST_TRANSITION")
        return lease, actual

    def snapshot(self, snapshot_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        p = normalized(
            item(self.ddb, self.prefix + "backups", "provenance_key", "SNAPSHOT#" + snapshot_id)
        )
        if not p:
            raise ValueError("RESTORE_UNKNOWN_SNAPSHOT")
        reverse = normalized(
            item(
                self.ddb,
                self.prefix + "backups",
                "provenance_key",
                "OPERATION#" + p["operation_id"],
            )
        )
        snapshots = self.ec2.describe_snapshots(SnapshotIds=[snapshot_id])["Snapshots"]
        if len(snapshots) != 1:
            raise ValueError("RESTORE_SNAPSHOT_NOT_UNIQUE")
        description = verified_snapshot(
            snapshots[0],
            p,
            reverse,
            project=self.cfg.project.project_slug,
            stage=self.stage,
            account=self.cfg.stage.aws_account_id,
            volume=str(self.cfg.stage.host_runtime_value("target_host.existing_data_volume_id")),
        )
        return p, description

    def plan(
        self, *, game_id: str, snapshot_id: str, protection_id: str, request_id: str
    ) -> dict[str, Any]:
        existing = normalized(
            self.repo.read(request_operation(self.cfg.project.system_id, self.stage, request_id))
        )
        if existing:
            if (
                existing["plan"]["game_id"] != game_id
                or existing["plan"]["source_snapshot_id"] != snapshot_id
            ):
                raise ValueError("RESTORE_IDEMPOTENCY_CONFLICT")
            return dict(existing)
        lease, actual = self.idle_host()
        if actual != "stopped":
            raise ValueError("RESTORE_PLAN_REQUIRES_STOPPED_EC2")
        game = normalized(item(self.ddb, self.env["GAMES_TABLE"], "game_id", game_id))
        p, source = self.snapshot(snapshot_id)
        protection, protected = self.snapshot(protection_id)
        captured = parse_rfc3339(protection["snapshot_start_time"])
        state = self.state()
        if (
            captured < parse_rfc3339(state["desired_updated_at"])
            or not 0 <= (self.now - captured).total_seconds() <= 3600
            or protected["games"].get(game_id, {}).get("world") != game["world"]
            or protected["games"].get(game_id, {}).get("package") != game["package"]
        ):
            raise ValueError("RESTORE_FRESH_PRE_BACKUP_REQUIRED")
        manifest_text = protected["runtime"]["manifest_json"]
        if hashlib.sha256(manifest_text.encode()).hexdigest() != self.runtime_digest:
            raise ValueError("RESTORE_CURRENT_RUNTIME_MISMATCH")
        manifest = json.loads(manifest_text)
        if game_id not in registry_ids(self.ddb, self.env["GAMES_TABLE"], tuple(manifest["games"])):
            raise ValueError("RESTORE_GAME_NOT_REGISTERED")
        plan = make_plan(
            game=game,
            current_manifest=manifest,
            recovery=source,
            provenance=p,
            request_id=request_id,
            system_id=self.cfg.project.system_id,
            now=self.now,
        )
        return self.repo.create(
            plan,
            lease=lease,
            now=self.now,
            current_package=game["package"],
            protection={
                "snapshot_id": protection_id,
                "operation_id": protection["operation_id"],
                "captured_at": protection["snapshot_start_time"],
                "config_digest": self.runtime_digest,
                "desired_revision": state["desired_revision"],
            },
        )

    def recover_maintenance(
        self, operation: str, previous_id: str, duration: int
    ) -> dict[str, Any]:
        """Explicitly approved replacement lease for this RESTORE; never renew an old lease."""
        record = normalized(self.repo.read(operation))
        if not record or record["plan"]["system_id"] != self.cfg.project.system_id:
            raise ValueError("RESTORE_UNKNOWN_REQUEST")
        no_external_work(
            self.session, stack="WishicraftControlPlaneStack-" + self.stage, instance_id=self.target
        )
        invoke(self.functions, self.prefix + "reconcile")
        state = self.state()
        previous = state.get("maintenance", {})
        now = datetime.now(UTC)
        if (
            previous.get("id") != previous_id
            or previous.get("stage") != self.stage
            or previous.get("status") not in {"ACTIVE", "INCIDENT"}
            or lease_active(previous, now=now)
            or previous_id == self.maintenance_id
            or state.get("current_operation_id") is not None
        ):
            raise ValueError("RESTORE_RECOVERY_LEASE_CONFLICT")
        lock = item(self.ddb, self.env["LOCKS_TABLE"], "lock_name", self.cfg.stage.global_lock_name)
        actual = self.ec2.describe_instances(InstanceIds=[self.target])["Reservations"][0][
            "Instances"
        ][0]
        lease = new_lease(
            lease_id=self.maintenance_id,
            actor=self.session.client("sts").get_caller_identity()["Arn"],
            reason="restore-recovery",
            stage=self.stage,
            duration=duration,
            now=now,
        )
        lease.update(previous_maintenance_id=previous_id, restore_operation_id=operation)
        metrics = maintenance_metrics(
            state={**state, "maintenance": lease},
            lock=lock,
            instance=actual,
            now=now,
            freshness_seconds=120,
        )
        if metrics["MaintenanceSuppressionEligible"] != 1:
            raise ValueError("RESTORE_RECOVERY_HOST_NOT_QUIESCENT")
        if actual["State"]["Name"] == "running":
            # A timed-out shell may outlive its SSM transport; stopped EC2 proves it cannot.
            for page in self.ssm.get_paginator("list_commands").paginate(InstanceId=self.target):
                for command in page["Commands"]:
                    if operation in command.get("Comment", "") and command["Status"] not in {
                        "Success",
                        "Failed",
                    }:
                        raise ValueError("RESTORE_RECOVERY_COMMAND_UNKNOWN_STOP_HOST_FIRST")
        transition(
            self.ddb,
            table=self.env["SYSTEM_STATE_TABLE"],
            locks_table=self.env["LOCKS_TABLE"],
            system_id=self.cfg.project.system_id,
            lock_name=self.cfg.stage.global_lock_name,
            state=state,
            lease=lease,
            event="recover-restore",
            now=now,
        )
        if self.state().get("maintenance") != lease:
            raise ValueError("RESTORE_RECOVERY_READBACK")
        return {"maintenance": lease, "phase": record["phase"]}

    def rollback_command(self, record: dict[str, Any]) -> dict[str, Any]:
        excluded = {c["command_id"] for c in record.get("rollback_history", [])}
        commands = [
            c
            for page in self.ssm.get_paginator("list_commands").paginate(InstanceId=self.target)
            for c in page["Commands"]
            if c.get("Comment") == "Wishicraft rollback " + record["plan"]["operation_id"]
            and c["CommandId"] not in excluded
        ]
        if (
            len(commands) != 1
            or commands[0].get("Parameters", {}).get("commands") != [record["rollback_dispatch"]]
            or commands[0].get("InstanceIds") != [self.target]
            or record.get("rollback_command_id") not in (None, commands[0]["CommandId"])
        ):
            raise ValueError("RESTORE_ROLLBACK_CHECK_UNKNOWN")
        return dict(
            self.ssm.get_command_invocation(
                CommandId=commands[0]["CommandId"], InstanceId=self.target
            )
        )

    def envelope(self, record: dict[str, Any], lease: dict[str, Any]) -> dict[str, Any]:
        return {
            "plan": record["plan"],
            "instance_id": self.target,
            "expires_at": int(lease["expires_at"]),
            "maintenance_id": lease["id"],
            "maintenance": lease,
            "system_state_table": self.env["SYSTEM_STATE_TABLE"],
            "protection_revision": record["pre_restore_backup"].get("desired_revision"),
            "config_digest": record["pre_restore_backup"]["config_digest"],
        }

    def action(self, action: str, operation: str) -> dict[str, Any]:
        record = normalized(self.repo.read(operation))
        if not record:
            raise ValueError("RESTORE_UNKNOWN_REQUEST")
        if action == "status":
            return dict(record)
        lease, actual = self.preflight(external_work=action in {"collect", "collect-rollback"})
        plan = record["plan"]
        if (
            action in {"volume", "attach", "prepare", "retry-prepare", "commit"}
            and record["phase"] != "COMMITTED"
        ):
            expected = record["pre_restore_backup"].get("desired_revision")
            if expected is None or self.state().get("desired_revision") != expected:
                raise ValueError("RESTORE_PROTECTION_STALE_NEW_REQUEST_REQUIRED")
        volume = RestoreVolume(
            self.ec2, plan, az=self.cfg.stage.availability_zone, instance=self.target
        )

        def save(**changes: Any) -> dict[str, Any]:
            return self.repo.advance(record, lease=lease, now=datetime.now(UTC), **changes)

        if action == "check-rollback":
            self.idle_host()
            if (
                actual != "running"
                or record["phase"] != "COMMITTED"
                or record.get("rollback_dispatch")
            ):
                raise ValueError("RESTORE_ROLLBACK_CHECK_PHASE")
            command = host_command(
                {
                    **self.envelope(record, lease),
                    "action": "verify-rollback",
                    "previous_tree": record["host_receipt"]["previous_tree"],
                }
            )
            record = save(rollback_dispatch=command, rollback_maintenance_id=lease["id"])
            response = self.ssm.send_command(
                InstanceIds=[self.target],
                DocumentName="AWS-RunShellScript",
                Comment="Wishicraft rollback " + operation,
                Parameters={"commands": [command], "executionTimeout": ["900"]},
                TimeoutSeconds=60,
            )
            return save(rollback_command_id=response["Command"]["CommandId"])
        if action == "collect-rollback":
            if record["phase"] != "COMMITTED" or not record.get("rollback_dispatch"):
                raise ValueError("RESTORE_ROLLBACK_CHECK_PHASE")
            response = self.rollback_command(record)
            if response["Status"] != "Success" or response["ResponseCode"] != 0:
                raise ValueError("RESTORE_ROLLBACK_NOT_VERIFIED")
            proof = json.loads(response["StandardOutputContent"])
            if proof != {
                "operation_id": operation,
                "rollback_verified": True,
                "previous_tree": record["host_receipt"]["previous_tree"],
                "maintenance_id": record["rollback_maintenance_id"],
            }:
                raise ValueError("RESTORE_ROLLBACK_PROOF")
            return save(rollback_receipt=proof)

        if action == "retry-rollback":
            self.idle_host()
            if record["phase"] != "COMMITTED" or not record.get("rollback_dispatch"):
                raise ValueError("RESTORE_ROLLBACK_CHECK_PHASE")
            check_result = self.rollback_command(record)
            failed = check_result["Status"] == "Failed" and check_result["ResponseCode"] > 0
            quiesced = actual == "stopped" and check_result["Status"] in {"TimedOut", "Cancelled"}
            obsolete = (
                check_result["Status"] == "Success"
                and check_result["ResponseCode"] == 0
                and isinstance(record.get("rollback_maintenance_id"), str)
                and (record.get("rollback_receipt") or {}).get("rollback_verified") is True
                and (record.get("rollback_receipt") or {}).get("maintenance_id")
                == record.get("rollback_maintenance_id")
                and record.get("rollback_maintenance_id") != lease["id"]
            )
            if not (failed or obsolete or quiesced):
                raise ValueError("RESTORE_ROLLBACK_RETRY_NOT_SAFE")
            return save(
                rollback_history=[
                    *record.get("rollback_history", []),
                    {
                        "command_id": check_result["CommandId"],
                        "status": check_result["Status"],
                        "maintenance_id": record.get("rollback_maintenance_id"),
                    },
                ],
                rollback_dispatch=None,
                rollback_command_id=None,
                rollback_receipt=None,
            )

        if action == "volume":
            if record["phase"] not in {"PLANNED", "CREATE_INTENT", "VOLUME_CREATED"}:
                raise ValueError("RESTORE_VOLUME_PHASE")
            self.snapshot(plan["source_snapshot_id"])
            if record["phase"] == "PLANNED":
                record = save(phase="CREATE_INTENT")
            identity = record.get("volume_id") or volume.create()
            if volume.read(identity) is None:
                raise ValueError("RESTORE_VOLUME_MISSING")
            return save(phase="VOLUME_CREATED", volume_id=identity)
        if action == "attach":
            if actual != "running" or record["phase"] != "VOLUME_CREATED":
                raise ValueError("RESTORE_ATTACH_PHASE")
            self.idle_host()
            return save(attachment="ATTACHED" if volume.attach(record["volume_id"]) else "PENDING")
        if action == "prepare":
            self.idle_host()
            if (
                actual != "running"
                or record["phase"] != "VOLUME_CREATED"
                or not volume.attach(record["volume_id"])
            ):
                raise ValueError("RESTORE_PREPARE_PHASE")
            command = host_command(
                {
                    **self.envelope(record, lease),
                    "volume_id": record["volume_id"],
                }
            )
            record = save(phase="PREPARE_DISPATCH", host_command=command)
            response = self.ssm.send_command(
                InstanceIds=[self.target],
                DocumentName="AWS-RunShellScript",
                Comment="Wishicraft RESTORE " + operation,
                Parameters={"commands": [command], "executionTimeout": ["900"]},
                TimeoutSeconds=60,
            )
            return save(command_id=response["Command"]["CommandId"])
        if action == "retry-prepare":
            self.idle_host()
            if record["phase"] != "PREPARE_DISPATCH" or not record.get("command_id"):
                raise ValueError("RESTORE_RETRY_REQUIRES_KNOWN_COMMAND")
            failed = self.ssm.get_command_invocation(
                CommandId=record["command_id"], InstanceId=self.target
            )
            definite = failed["Status"] == "Failed" and failed["ResponseCode"] > 0
            quiesced = actual == "stopped" and failed["Status"] in {"TimedOut", "Cancelled"}
            if not (definite or quiesced):
                raise ValueError("RESTORE_RETRY_REQUIRES_DEFINITE_FAILURE")
            return save(
                phase="VOLUME_CREATED",
                command_id=None,
                previous_commands=[
                    *record.get("previous_commands", []),
                    {"command_id": record["command_id"], "response_code": failed["ResponseCode"]},
                ],
            )
        if action == "collect":
            if record["phase"] != "PREPARE_DISPATCH":
                raise ValueError("RESTORE_COLLECT_PHASE")
            command_id = record.get("command_id")
            if not command_id:
                commands = [
                    c
                    for page in self.ssm.get_paginator("list_commands").paginate(
                        InstanceId=self.target
                    )
                    for c in page["Commands"]
                    if c.get("Comment") == "Wishicraft RESTORE " + operation
                    and c["CommandId"]
                    not in {
                        previous["command_id"] for previous in record.get("previous_commands", [])
                    }
                ]
                if (
                    len(commands) != 1
                    or commands[0].get("Parameters", {}).get("commands") != [record["host_command"]]
                    or commands[0].get("InstanceIds") != [self.target]
                ):
                    raise ValueError("RESTORE_DISPATCH_OUTCOME_UNKNOWN_DO_NOT_RESEND")
                command_id = commands[0]["CommandId"]
            result = self.ssm.get_command_invocation(CommandId=command_id, InstanceId=self.target)
            if result["Status"] != "Success" or result["ResponseCode"] != 0:
                return save(command_id=command_id, command_status=result["Status"])
            receipt = json.loads(result["StandardOutputContent"])
            if (
                receipt.get("operation_id") != operation
                or receipt.get("volume_id") != record["volume_id"]
                or receipt.get("phase") != "prepared"
                or receipt.get("unmounted") is not True
            ):
                raise ValueError("RESTORE_HOST_RECEIPT")
            return save(phase="PREPARED", command_id=command_id, host_receipt=receipt)
        if action in {"commit", "rollback"}:
            self.idle_host()
            if actual != "stopped":
                raise ValueError("RESTORE_SELECTION_REQUIRES_STOPPED_EC2")
            if action == "rollback" and (
                (record.get("rollback_receipt") or {}).get("maintenance_id") != lease["id"]
                or record["rollback_receipt"].get("rollback_verified") is not True
            ):
                raise ValueError("RESTORE_ROLLBACK_PROOF_REQUIRED")
            return self.repo.select(
                record, lease=lease, now=datetime.now(UTC), rollback=action == "rollback"
            )
        if action == "cleanup":
            if actual != "stopped":
                raise ValueError("RESTORE_CLEANUP_REQUIRES_STOPPED_EC2")
            if not record.get("volume_id"):
                raise ValueError("RESTORE_VOLUME_DISCOVERY_REQUIRED")
            try:
                result = volume.cleanup(
                    record["volume_id"],
                    instance_stopped=True,
                    delete_intent=record.get("delete_intent") is True,
                )
                if result == "DELETE_INTENT_REQUIRED":
                    return save(delete_intent=True, cleanup="DELETE_INTENT")
                return save(cleanup=result)
            except Exception:
                save(cleanup="FAILED")
                raise
        raise ValueError("RESTORE_UNKNOWN_ACTION")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "plan",
            "recover-maintenance",
            "status",
            "volume",
            "attach",
            "prepare",
            "retry-prepare",
            "collect",
            "commit",
            "cleanup",
            "rollback",
            "check-rollback",
            "collect-rollback",
            "retry-rollback",
        ],
    )
    parser.add_argument("--stage", choices=["dev"], default="dev")
    parser.add_argument("--profile", default="wishicraft-dev")
    parser.add_argument("--maintenance-id", required=True)
    parser.add_argument("--operation-id")
    parser.add_argument("--previous-maintenance-id")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--game-id")
    parser.add_argument("--snapshot-id")
    parser.add_argument("--pre-backup-snapshot-id")
    parser.add_argument("--request-id")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.action != "status" and not args.execute:
        parser.error("mutation requires --execute and the formal maintenance lease")
    root = Path(__file__).resolve().parents[2]
    cfg = load_configuration(root, args.stage)
    operator = Operator(
        boto3.Session(profile_name=args.profile, region_name=cfg.stage.aws_region),
        root=root,
        stage=args.stage,
        maintenance_id=args.maintenance_id,
    )
    if args.action == "recover-maintenance":
        if not args.operation_id or not args.previous_maintenance_id:
            parser.error("recovery requires RESTORE operation and exact previous maintenance ID")
        result = operator.recover_maintenance(
            args.operation_id, args.previous_maintenance_id, args.duration_seconds
        )
    elif args.action == "plan":
        if not all((args.game_id, args.snapshot_id, args.pre_backup_snapshot_id, args.request_id)):
            parser.error(
                "plan requires Game, source snapshot, pre-backup snapshot and request identity"
            )
        result = operator.plan(
            game_id=args.game_id,
            snapshot_id=args.snapshot_id,
            protection_id=args.pre_backup_snapshot_id,
            request_id=args.request_id,
        )
    else:
        if not args.operation_id:
            parser.error("checkpoint requires --operation-id")
        result = operator.action(args.action, args.operation_id)
    # Fixed payload contains no credentials but is large; expose only its durable identity.
    result.pop("host_command", None)
    print(json.dumps(result, default=int, indent=2))


if __name__ == "__main__":
    main()
