"""Offline preparation only: verify captured D-090 evidence and render an isolated stack."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from wishicraft.backup import SnapshotAdapter
from wishicraft.backup_provenance import (
    BackupOperationEvidence,
    BackupProvenanceRepository,
    build_verified_provenance,
)
from wishicraft.config import load_configuration
from wishicraft.operation import OperationRepository
from wishicraft.retention import parse_rfc3339


class EvidenceStore:
    def __init__(self, evidence: dict[str, Any]) -> None:
        self.tables = {"backups": evidence["provenance"], "operations": evidence["operations"]}

    def get_item(self, **kwargs: Any) -> Any:
        assert kwargs.get("ConsistentRead") is True
        key = kwargs["Key"]
        matches = [
            item
            for item in self.tables[kwargs["TableName"]]
            if all(item.get(k) == v for k, v in key.items())
        ]
        if len(matches) != 1:
            raise ValueError("missing or duplicate captured evidence")
        return {"Item": matches[0]}

    def transact_write_items(self, **kwargs: Any) -> Any:
        raise RuntimeError("offline evidence is read-only")

    def update_item(self, **kwargs: Any) -> Any:
        raise RuntimeError("offline evidence is read-only")

    def delete_item(self, **kwargs: Any) -> Any:
        raise RuntimeError("offline evidence is read-only")


def verify_source(evidence: dict[str, Any], snapshot_id: str, root: Path) -> dict[str, Any]:
    config = load_configuration(root, "dev")
    snapshots = [s for s in evidence["snapshots"] if s["SnapshotId"] == snapshot_id]
    if len(snapshots) != 1:
        raise ValueError("snapshot identity is not unique")
    raw = dict(snapshots[0])
    if (
        raw.get("Encrypted") is not True
        or raw.get("VolumeSize") != config.stage.data_volume_size_gib
    ):
        raise ValueError("source encryption/size differs from dev binding")
    if isinstance(raw.get("StartTime"), str):
        raw["StartTime"] = datetime.fromisoformat(raw["StartTime"])
    snapshot = SnapshotAdapter._parse_snapshot(raw)
    store = EvidenceStore(evidence)
    operation_id = snapshot.tags.get("WishicraftOperationId", "")
    operations = OperationRepository(
        store,
        operations_table="operations",
        locks_table="locks",
        system_state_table="state",
        system_id=config.project.system_id,
        lock_name=config.stage.global_lock_name,
    )
    operation = operations.load_backup_evidence(operation_id)
    provenance = BackupProvenanceRepository(store, table_name="backups")
    recorded_at = provenance.existing_recorded_at(snapshot_id, operation_id)
    if recorded_at is None or not isinstance(operation["result"], dict):
        raise ValueError("verified provenance and successful Operation are required")
    recovery_json = None
    game_id = config.project.initial_game_id
    if snapshot.tags.get("WishicraftSchemaVersion") == "2":
        from wishicraft.runtime_catalog import RuntimeCatalog

        raw_operation = store.get_item(
            TableName="operations", Key={"operation_id": {"S": operation_id}}, ConsistentRead=True
        )["Item"]
        recovery_json = raw_operation["backup_recovery_json"]["S"]
        game_id = snapshot.tags["WishicraftGameId"]
        RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text()).data_source(game_id)
    record = build_verified_provenance(
        snapshot=snapshot,
        operation=BackupOperationEvidence(
            operation_id=operation_id,
            operation_type=str(operation["operation_type"]),
            status=str(operation["status"]),
            requested_at=parse_rfc3339(str(operation["requested_at"])),
            result=operation["result"],
        ),
        project=config.project.project_slug,
        stage="dev",
        game_id=game_id,
        recovery_json=recovery_json,
        source_volume_id=str(
            config.stage.host_runtime_value("target_host.existing_data_volume_id")
        ),
        owner_id=config.stage.aws_account_id,
        provenance_recorded_at=recorded_at,
    )
    if not provenance.exact_match(record):
        raise ValueError("captured provenance differs from Snapshot/Operation")
    return {
        "snapshot_id": snapshot_id,
        "operation_id": operation_id,
        "source_volume_id": record.source_volume_id,
        "owner_id": record.verified_owner_id,
        "snapshot_start_time": record.snapshot_start_time.isoformat(),
        "game_id": record.game_id,
        "source_size_gib": raw["VolumeSize"],
        "source_kms_key_id": raw.get("KmsKeyId"),
        "provenance_verified": True,
        "runtime_reconstruction": "repository configuration; not a Snapshot-time manifest",
        "restore_test_completed": False,
        **(
            {
                "recovery_description": json.loads(recovery_json),
                "runtime_reconstruction": (
                    "Snapshot-time recovery description verified against Operation "
                    "and provenance; secrets excluded"
                ),
            }
            if recovery_json is not None
            else {}
        ),
    }


def isolated_template(source: dict[str, Any], root: Path) -> dict[str, Any]:
    config = load_configuration(root, "dev")
    stage = config.stage
    if source.get("provenance_verified") is not True:
        raise ValueError("source must be evidence-verified before rendering")
    tags = [
        {"Key": "Project", "Value": "wishicraft-restore-test"},
        {"Key": "Stage", "Value": "restore-test"},
        {"Key": "Purpose", "Value": "isolated-restore"},
    ]
    resources: dict[str, Any] = {
        "SecurityGroup": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupDescription": "Isolated restore: no inbound; HTTPS egress only",
                "VpcId": stage.host_runtime_value("target_host.vpc_id"),
                "SecurityGroupIngress": [],
                "SecurityGroupEgress": [
                    {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIp": "0.0.0.0/0"}
                ],
                "Tags": tags,
            },
        },
        "Role": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "AssumeRolePolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "ec2.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                },
                "Policies": [
                    {
                        "PolicyName": "IsolatedSsmOnly",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "ssm:UpdateInstanceInformation",
                                        "ssmmessages:CreateControlChannel",
                                        "ssmmessages:CreateDataChannel",
                                        "ssmmessages:OpenControlChannel",
                                        "ssmmessages:OpenDataChannel",
                                    ],
                                    "Resource": "*",
                                },
                                {
                                    "Effect": "Deny",
                                    "Action": [
                                        "dynamodb:*",
                                        "route53:*",
                                        "ec2:*",
                                        "ssm:GetParameter*",
                                        "secretsmanager:*",
                                        "lambda:*",
                                        "states:*",
                                    ],
                                    "Resource": "*",
                                },
                            ],
                        },
                    }
                ],
            },
        },
        "Profile": {
            "Type": "AWS::IAM::InstanceProfile",
            "Properties": {"Roles": [{"Ref": "Role"}]},
        },
        "Host": {
            "Type": "AWS::EC2::Instance",
            "Properties": {
                "ImageId": stage.host_runtime_value("platform.ami_id"),
                "InstanceType": "t3a.medium",
                "IamInstanceProfile": {"Ref": "Profile"},
                "MetadataOptions": {
                    "HttpTokens": "required",
                    "HttpPutResponseHopLimit": 1,
                    "InstanceMetadataTags": "disabled",
                },
                "CreditSpecification": {"CPUCredits": "standard"},
                "NetworkInterfaces": [
                    {
                        "DeviceIndex": "0",
                        "AssociatePublicIpAddress": True,
                        "SubnetId": stage.host_runtime_value("target_host.subnet_id"),
                        "GroupSet": [{"Ref": "SecurityGroup"}],
                    }
                ],
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "VolumeType": "gp3",
                            "VolumeSize": 16,
                            "Encrypted": True,
                            "DeleteOnTermination": False,
                        },
                    }
                ],
                "Tags": tags,
            },
        },
        "Copy": {
            "Type": "AWS::EC2::Volume",
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "AvailabilityZone": stage.availability_zone,
                "SnapshotId": source["snapshot_id"],
                "VolumeType": "gp3",
                "Encrypted": True,
                "Tags": tags,
            },
        },
        "Attachment": {
            "Type": "AWS::EC2::VolumeAttachment",
            "Properties": {
                "InstanceId": {"Ref": "Host"},
                "VolumeId": {"Ref": "Copy"},
                "Device": "/dev/sdf",
            },
        },
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Operator-approved isolated restore test; no production integration",
        "Resources": resources,
        "Outputs": {
            name: {"Value": {"Ref": name}}
            for name in ("Host", "Copy", "SecurityGroup", "Role", "Profile")
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = verify_source(json.loads(args.evidence.read_text()), args.snapshot_id, root)
    template = isolated_template(source, root)
    args.output_root.mkdir(parents=False, exist_ok=False)
    for name, value in (("source.json", source), ("isolated-stack.json", template)):
        with (args.output_root / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
    print("PREPARED_ONLY: no AWS calls; restore test not executed")


if __name__ == "__main__":
    main()
