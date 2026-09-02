"""Phase 8A stopped-only EBS backup domain and narrow EC2 adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast

from wishicraft.operation import LeaseProof, LeaseRepository


class BackupErrorCode(StrEnum):
    PRECONDITION_FAILED = "BACKUP_PRECONDITION_FAILED"
    SOURCE_VOLUME_MISMATCH = "BACKUP_SOURCE_VOLUME_MISMATCH"
    SNAPSHOT_CREATE_FAILED = "BACKUP_SNAPSHOT_CREATE_FAILED"
    SNAPSHOT_FAILED = "BACKUP_SNAPSHOT_FAILED"
    SNAPSHOT_TIMEOUT = "BACKUP_SNAPSHOT_TIMEOUT"
    SNAPSHOT_VERIFICATION_FAILED = "BACKUP_SNAPSHOT_VERIFICATION_FAILED"
    OBSERVATION_FAILED = "OBSERVATION_FAILED"


class BackupWorkflowError(RuntimeError):
    def __init__(self, code: BackupErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class BackupObservation:
    desired_state: str
    ec2_state: str
    health: str
    discrepancies: tuple[str, ...]
    observation_errors: tuple[str, ...]

    @classmethod
    def from_item(cls, item: dict[str, object]) -> BackupObservation:
        observation = item.get("observation")
        discrepancies = item.get("discrepancies")
        errors = item.get("observation_errors")
        if not isinstance(observation, dict):
            raise BackupWorkflowError(BackupErrorCode.OBSERVATION_FAILED)
        if not isinstance(discrepancies, list) or not all(
            isinstance(value, str) for value in discrepancies
        ):
            raise BackupWorkflowError(BackupErrorCode.OBSERVATION_FAILED)
        if not isinstance(errors, list) or not all(isinstance(value, str) for value in errors):
            raise BackupWorkflowError(BackupErrorCode.OBSERVATION_FAILED)
        desired = item.get("desired_state")
        ec2_state = observation.get("ec2_state")
        health = item.get("health")
        if not all(isinstance(value, str) for value in (desired, ec2_state, health)):
            raise BackupWorkflowError(BackupErrorCode.OBSERVATION_FAILED)
        return cls(
            cast(str, desired),
            cast(str, ec2_state),
            cast(str, health),
            tuple(discrepancies),
            tuple(errors),
        )

    def validate(self) -> None:
        if self.observation_errors:
            raise BackupWorkflowError(BackupErrorCode.OBSERVATION_FAILED)
        if (
            self.desired_state != "STOPPED"
            or self.ec2_state != "stopped"
            or self.health != "HEALTHY"
            or self.discrepancies
        ):
            raise BackupWorkflowError(BackupErrorCode.PRECONDITION_FAILED)


class Ec2SnapshotApi(Protocol):
    def describe_volumes(self, **kwargs: object) -> object: ...
    def create_snapshot(self, **kwargs: object) -> object: ...
    def describe_snapshots(self, **kwargs: object) -> object: ...


REQUIRED_TAG_KEYS = frozenset(
    {
        "Project",
        "Stage",
        "WishicraftCategory",
        "WishicraftGameId",
        "WishicraftOperationId",
        "WishicraftSourceVolumeId",
        "WishicraftSchemaVersion",
        "WishicraftProtected",
        "WishicraftCreatedAt",
    }
)


@dataclass(frozen=True)
class SnapshotRecord:
    snapshot_id: str
    source_volume_id: str
    state: str
    tags: dict[str, str]
    owner_id: str


class SnapshotAdapter:
    """One-attempt snapshot creation; callers must never retry create after ambiguity."""

    def __init__(self, api: Ec2SnapshotApi, *, account_id: str) -> None:
        self._api = api
        self._account_id = account_id

    def validate_source(self, *, volume_id: str, availability_zone: str) -> None:
        response = self._api.describe_volumes(VolumeIds=[volume_id])
        volumes = response.get("Volumes") if isinstance(response, dict) else None
        if not isinstance(volumes, list) or len(volumes) != 1:
            raise BackupWorkflowError(BackupErrorCode.SOURCE_VOLUME_MISMATCH)
        volume = volumes[0]
        if not isinstance(volume, dict):
            raise BackupWorkflowError(BackupErrorCode.SOURCE_VOLUME_MISMATCH)
        if (
            volume.get("VolumeId") != volume_id
            or volume.get("AvailabilityZone") != availability_zone
            or volume.get("Encrypted") is not True
        ):
            raise BackupWorkflowError(BackupErrorCode.SOURCE_VOLUME_MISMATCH)

    def create_once(self, *, volume_id: str, tags: dict[str, str]) -> SnapshotRecord:
        if set(tags) != REQUIRED_TAG_KEYS:
            raise ValueError("invalid backup tag contract")
        response = self._api.create_snapshot(
            VolumeId=volume_id,
            Description=f"Wishicraft backup {tags['WishicraftOperationId']}",
            TagSpecifications=[
                {
                    "ResourceType": "snapshot",
                    "Tags": [{"Key": key, "Value": value} for key, value in sorted(tags.items())],
                }
            ],
        )
        return self._parse_snapshot(response)

    def describe(self, snapshot_id: str) -> SnapshotRecord:
        _validate_snapshot_id(snapshot_id)
        response = self._api.describe_snapshots(
            SnapshotIds=[snapshot_id], OwnerIds=[self._account_id]
        )
        snapshots = response.get("Snapshots") if isinstance(response, dict) else None
        if not isinstance(snapshots, list) or len(snapshots) != 1:
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        record = self._parse_snapshot(snapshots[0])
        if record.owner_id != self._account_id:
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        return record

    @staticmethod
    def _parse_snapshot(value: object) -> SnapshotRecord:
        if not isinstance(value, dict):
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_CREATE_FAILED)
        snapshot_id = value.get("SnapshotId")
        volume_id = value.get("VolumeId")
        state = value.get("State")
        owner_id = value.get("OwnerId")
        raw_tags = value.get("Tags", [])
        if not isinstance(snapshot_id, str) or not isinstance(volume_id, str):
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_CREATE_FAILED)
        _validate_snapshot_id(snapshot_id)
        if (
            not isinstance(state, str)
            or not isinstance(owner_id, str)
            or not isinstance(raw_tags, list)
        ):
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        tags: dict[str, str] = {}
        for tag in raw_tags:
            if (
                not isinstance(tag, dict)
                or not isinstance(tag.get("Key"), str)
                or not isinstance(tag.get("Value"), str)
            ):
                raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
            tags[cast(str, tag["Key"])] = cast(str, tag["Value"])
        return SnapshotRecord(snapshot_id, volume_id, state, tags, owner_id)


@dataclass
class BackupCoordinator:
    leases: LeaseRepository
    snapshots: SnapshotAdapter
    expected_volume_id: str
    availability_zone: str
    project: str
    stage: str
    game_id: str
    lease_seconds: int

    def preflight(self, *, proof: LeaseProof, state: dict[str, object], now: datetime) -> None:
        self.leases.verify_owned(proof, now=now)
        BackupObservation.from_item(state).validate()
        self.snapshots.validate_source(
            volume_id=self.expected_volume_id, availability_zone=self.availability_zone
        )

    def tags(self, *, operation_id: str, requested_at: str) -> dict[str, str]:
        return {
            "Project": self.project,
            "Stage": self.stage,
            "WishicraftCategory": "backup",
            "WishicraftGameId": self.game_id,
            "WishicraftOperationId": operation_id,
            "WishicraftSourceVolumeId": self.expected_volume_id,
            "WishicraftSchemaVersion": "1",
            "WishicraftProtected": "false",
            "WishicraftCreatedAt": requested_at,
        }

    def verify_completed(self, record: SnapshotRecord, *, expected_tags: dict[str, str]) -> None:
        if record.state == "error":
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_FAILED)
        if record.state != "completed":
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
        if record.source_volume_id != self.expected_volume_id or record.tags != expected_tags:
            raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)

    def renew(self, proof: LeaseProof, *, now: datetime) -> LeaseProof:
        return self.leases.renew(proof, now=now, lease_seconds=self.lease_seconds)


def select_retention_candidates(
    records: list[SnapshotRecord], *, game_id: str, source_volume_id: str
) -> list[str]:
    """Pure Phase 8A policy selector; no deletion side effect is implemented."""
    eligible = [
        record
        for record in records
        if record.tags.get("WishicraftCategory") == "backup"
        and record.tags.get("WishicraftGameId") == game_id
        and record.tags.get("WishicraftProtected") == "false"
        and record.source_volume_id == source_volume_id
        and record.tags.get("WishicraftSourceVolumeId") == source_volume_id
    ]
    eligible.sort(key=lambda item: item.tags.get("WishicraftCreatedAt", ""), reverse=True)
    return [record.snapshot_id for record in eligible[7:]]


def _validate_snapshot_id(value: str) -> None:
    if re.fullmatch(r"snap-[0-9a-f]{8,17}", value) is None:
        raise BackupWorkflowError(BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED)
