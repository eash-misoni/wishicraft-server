"""Temporary, operator-owned EBS lifecycle. No application role needs these permissions."""

from __future__ import annotations

from typing import Any


class RestoreVolume:
    def __init__(self, ec2: Any, plan: dict[str, Any], *, az: str, instance: str) -> None:
        self.ec2, self.plan, self.az, self.instance = ec2, plan, az, instance
        self.tags = {
            "Project": plan["project"],
            "Stage": plan["stage"],
            "WishicraftCategory": "temporary-restore",
            "WishicraftSystemId": plan["system_id"],
            "WishicraftOperationId": plan["operation_id"],
            "WishicraftSnapshotId": plan["source_snapshot_id"],
            "WishicraftGameId": plan["game_id"],
        }

    def verify(self, volume: dict[str, Any]) -> None:
        if (
            volume.get("VolumeId") == self.plan["source_volume_id"]
            or volume.get("SnapshotId") != self.plan["source_snapshot_id"]
            or volume.get("AvailabilityZone") != self.az
            or volume.get("Encrypted") is not True
            or volume.get("VolumeType") != "gp3"
            or {t["Key"]: t["Value"] for t in volume.get("Tags", [])} != self.tags
            or any(
                a.get("InstanceId") != self.instance or a.get("Device") != "/dev/sdg"
                for a in volume.get("Attachments", [])
            )
        ):
            raise ValueError("RESTORE_TEMP_VOLUME_IDENTITY")

    def read(self, volume_id: str) -> dict[str, Any] | None:
        try:
            rows = self.ec2.describe_volumes(VolumeIds=[volume_id])["Volumes"]
        except Exception as error:
            if (
                getattr(error, "response", {}).get("Error", {}).get("Code")
                == "InvalidVolume.NotFound"
            ):
                return None
            raise
        if len(rows) != 1 or rows[0]["VolumeId"] != volume_id:
            raise ValueError("RESTORE_TEMP_VOLUME_NOT_UNIQUE")
        self.verify(rows[0])
        return dict(rows[0])

    def create(self) -> str:
        # Caller journals CREATE_INTENT first. Inline tags permit recovery after response loss;
        # the stable token makes a retry the same request, never an unrelated replacement.
        matches = [
            v
            for page in self.ec2.get_paginator("describe_volumes").paginate(
                Filters=[
                    {"Name": "tag:WishicraftOperationId", "Values": [self.plan["operation_id"]]}
                ]
            )
            for v in page["Volumes"]
        ]
        if len(matches) > 1:
            raise ValueError("RESTORE_TEMP_VOLUME_DUPLICATE")
        if matches:
            self.verify(matches[0])
            return str(matches[0]["VolumeId"])
        result = self.ec2.create_volume(
            AvailabilityZone=self.az,
            SnapshotId=self.plan["source_snapshot_id"],
            VolumeType="gp3",
            Encrypted=True,
            ClientToken=self.plan["operation_id"][3:],
            TagSpecifications=[
                {
                    "ResourceType": "volume",
                    "Tags": [{"Key": k, "Value": v} for k, v in self.tags.items()],
                }
            ],
        )
        self.verify(result)
        return str(result["VolumeId"])

    def attach(self, volume_id: str) -> bool:
        volume = self.read(volume_id)
        if volume is None:
            raise ValueError("RESTORE_TEMP_VOLUME_MISSING")
        if volume["Attachments"]:
            return bool(volume["Attachments"][0]["State"] == "attached")
        if volume["State"] != "available":
            return False
        self.ec2.attach_volume(VolumeId=volume_id, InstanceId=self.instance, Device="/dev/sdg")
        return False

    def cleanup(self, volume_id: str, *, instance_stopped: bool, delete_intent: bool) -> str:
        # Stopped EC2 establishes that no process or filesystem can still use the attachment.
        if not instance_stopped:
            raise ValueError("RESTORE_CLEANUP_REQUIRES_STOPPED_HOST")
        volume = self.read(volume_id)
        if volume is None:
            if not delete_intent:
                raise ValueError("RESTORE_UNEXPLAINED_VOLUME_ABSENCE")
            return "DELETED"
        if volume["Attachments"]:
            if volume["Attachments"][0]["State"] == "attached":
                self.ec2.detach_volume(
                    VolumeId=volume_id, InstanceId=self.instance, Device="/dev/sdg", Force=False
                )
            return "DETACHING"
        if volume["State"] == "available":
            if not delete_intent:
                return "DELETE_INTENT_REQUIRED"
            self.ec2.delete_volume(VolumeId=volume_id)
        return "DELETING"
