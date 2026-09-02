from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from wishicraft.backup import (
    BackupCoordinator,
    BackupErrorCode,
    BackupObservation,
    BackupWorkflowError,
    SnapshotAdapter,
    SnapshotRecord,
    select_retention_candidates,
)
from wishicraft.operation import LeaseRepository


class Ec2:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.volume: object = {
            "Volumes": [
                {
                    "VolumeId": "vol-03ac9f534326c345c",
                    "AvailabilityZone": "ap-northeast-1a",
                    "Encrypted": True,
                }
            ]
        }
        self.snapshot: object = {
            "Snapshots": [
                {
                    "SnapshotId": "snap-0123456789abcdef0",
                    "VolumeId": "vol-03ac9f534326c345c",
                    "State": "completed",
                    "OwnerId": "123456789012",
                    "Tags": [],
                }
            ]
        }

    def describe_volumes(self, **kwargs: object) -> object:
        return self.volume

    def create_snapshot(self, **kwargs: object) -> object:
        self.created.append(kwargs)
        tags = kwargs["TagSpecifications"]
        assert isinstance(tags, list)
        return {
            "SnapshotId": "snap-0123456789abcdef0",
            "VolumeId": kwargs["VolumeId"],
            "State": "pending",
            "OwnerId": "123456789012",
            "Tags": tags[0]["Tags"],
        }

    def describe_snapshots(self, **kwargs: object) -> object:
        return self.snapshot


def stopped_state(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "desired_state": "STOPPED",
        "health": "HEALTHY",
        "discrepancies": [],
        "observation_errors": [],
        "observation": {"ec2_state": "stopped"},
    }
    value.update(overrides)
    return value


def test_stopped_healthy_observation_is_allowed() -> None:
    BackupObservation.from_item(stopped_state()).validate()


@pytest.mark.parametrize(
    "change",
    [
        {"desired_state": "RUNNING"},
        {"health": "DEGRADED"},
        {"health": "UNKNOWN"},
        {"discrepancies": ["desired-actual-mismatch"]},
        {"observation": {"ec2_state": "running"}},
        {"observation": {"ec2_state": "stopping"}},
        {"observation": {"ec2_state": "pending"}},
    ],
)
def test_non_stopped_or_unhealthy_observation_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(BackupWorkflowError) as failure:
        BackupObservation.from_item(stopped_state(**change)).validate()
    assert failure.value.code is BackupErrorCode.PRECONDITION_FAILED


def test_observation_error_is_not_treated_as_stopped() -> None:
    with pytest.raises(BackupWorkflowError) as failure:
        BackupObservation.from_item(stopped_state(observation_errors=["ec2-api-failed"])).validate()
    assert failure.value.code is BackupErrorCode.OBSERVATION_FAILED


def test_source_volume_identity_is_exact_and_encrypted() -> None:
    ec2 = Ec2()
    adapter = SnapshotAdapter(ec2, account_id="123456789012")
    adapter.validate_source(volume_id="vol-03ac9f534326c345c", availability_zone="ap-northeast-1a")
    assert ec2.created == []
    ec2.volume = {"Volumes": [{"VolumeId": "vol-wrong", "Encrypted": True}]}
    with pytest.raises(BackupWorkflowError) as failure:
        adapter.validate_source(
            volume_id="vol-03ac9f534326c345c", availability_zone="ap-northeast-1a"
        )
    assert failure.value.code is BackupErrorCode.SOURCE_VOLUME_MISMATCH


def backup_tags(created: str = "2026-09-02T00:00:00Z") -> dict[str, str]:
    return {
        "Project": "wishicraft",
        "Stage": "dev",
        "WishicraftCategory": "backup",
        "WishicraftGameId": "game-vanilla-main",
        "WishicraftOperationId": "op-01234567-89ab-cdef-0123-456789abcdef",
        "WishicraftSourceVolumeId": "vol-03ac9f534326c345c",
        "WishicraftSchemaVersion": "1",
        "WishicraftProtected": "false",
        "WishicraftCreatedAt": created,
    }


def test_snapshot_create_has_inline_tags_and_one_intent() -> None:
    ec2 = Ec2()
    adapter = SnapshotAdapter(ec2, account_id="123456789012")
    record = adapter.create_once(volume_id="vol-03ac9f534326c345c", tags=backup_tags())
    assert record.state == "pending"
    assert record.tags == backup_tags()
    assert len(ec2.created) == 1


def test_snapshot_api_failure_is_not_reported_as_success() -> None:
    class FailedEc2(Ec2):
        def create_snapshot(self, **kwargs: object) -> object:
            raise RuntimeError("api unavailable")

    with pytest.raises(RuntimeError, match="api unavailable"):
        SnapshotAdapter(FailedEc2(), account_id="123456789012").create_once(
            volume_id="vol-03ac9f534326c345c", tags=backup_tags()
        )


def test_snapshot_poll_and_verification_reject_wrong_source_or_tags() -> None:
    ec2 = Ec2()
    ec2.snapshot = {
        "Snapshots": [
            {
                "SnapshotId": "snap-0123456789abcdef0",
                "VolumeId": "vol-wrong0000000000",
                "State": "completed",
                "OwnerId": "123456789012",
                "Tags": [{"Key": key, "Value": value} for key, value in backup_tags().items()],
            }
        ]
    }
    record = SnapshotAdapter(ec2, account_id="123456789012").describe("snap-0123456789abcdef0")
    coordinator = _coordinator(SnapshotAdapter(ec2, account_id="123456789012"))
    with pytest.raises(BackupWorkflowError) as failure:
        coordinator.verify_completed(record, expected_tags=backup_tags())
    assert failure.value.code is BackupErrorCode.SNAPSHOT_VERIFICATION_FAILED


class Leases:
    pass


def _coordinator(snapshots: SnapshotAdapter) -> BackupCoordinator:
    return BackupCoordinator(
        leases=cast(LeaseRepository, Leases()),
        snapshots=snapshots,
        expected_volume_id="vol-03ac9f534326c345c",
        availability_zone="ap-northeast-1a",
        project="wishicraft",
        stage="dev",
        game_id="game-vanilla-main",
        lease_seconds=900,
    )


@pytest.mark.parametrize("state", ["pending", "error", "recovering", "recoverable"])
def test_snapshot_must_be_completed(state: str) -> None:
    record = SnapshotRecord(
        "snap-0123456789abcdef0",
        "vol-03ac9f534326c345c",
        state,
        backup_tags(),
        "123456789012",
    )
    with pytest.raises(BackupWorkflowError):
        _coordinator(SnapshotAdapter(Ec2(), account_id="123456789012")).verify_completed(
            record, expected_tags=backup_tags()
        )


def test_retention_selects_only_unprotected_normal_backup_after_newest_seven() -> None:
    records = [
        SnapshotRecord(
            f"snap-{index:017x}",
            "vol-03ac9f534326c345c",
            "completed",
            backup_tags(datetime(2026, 9, index + 1, tzinfo=UTC).isoformat()),
            "123456789012",
        )
        for index in range(9)
    ]
    migration = SnapshotRecord(
        "snap-aaaaaaaaaaaaaaaaa",
        "vol-03ac9f534326c345c",
        "completed",
        {**backup_tags(), "WishicraftCategory": "migration"},
        "123456789012",
    )
    protected = SnapshotRecord(
        "snap-bbbbbbbbbbbbbbbbb",
        "vol-03ac9f534326c345c",
        "completed",
        {**backup_tags(), "WishicraftProtected": "true"},
        "123456789012",
    )
    other_game = SnapshotRecord(
        "snap-ccccccccccccccccc",
        "vol-03ac9f534326c345c",
        "completed",
        {**backup_tags(), "WishicraftGameId": "game-other"},
        "123456789012",
    )
    assert select_retention_candidates(
        [*records, migration, protected, other_game],
        game_id="game-vanilla-main",
        source_volume_id="vol-03ac9f534326c345c",
    ) == ["snap-00000000000000001", "snap-00000000000000000"]
