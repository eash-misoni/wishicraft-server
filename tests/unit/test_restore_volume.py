from __future__ import annotations

from typing import Any

import pytest

from wishicraft.restore_volume import RestoreVolume


class Ec2:
    def __init__(self) -> None:
        self.volumes: list[dict[str, Any]] = []
        self.creates = 0
        self.fail_delete = False
        self.lost_create = False

    def get_paginator(self, name: str) -> Ec2:
        assert name == "describe_volumes"
        return self

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"Volumes": self.volumes}]

    def create_volume(self, **kwargs: Any) -> dict[str, Any]:
        self.creates += 1
        assert kwargs["ClientToken"] == "restore"
        value = {k: v for k, v in kwargs.items() if k not in {"ClientToken", "TagSpecifications"}}
        value.update(
            VolumeId="vol-0123456789abcdef0",
            State="available",
            Attachments=[],
            Tags=kwargs["TagSpecifications"][0]["Tags"],
        )
        self.volumes.append(value)
        if self.lost_create:
            raise TimeoutError("response lost")
        return value

    def describe_volumes(self, **kwargs: Any) -> dict[str, Any]:
        return {"Volumes": self.volumes}

    def attach_volume(self, **kwargs: Any) -> None:
        self.volumes[0].update(State="in-use", Attachments=[{**kwargs, "State": "attached"}])

    def detach_volume(self, **kwargs: Any) -> None:
        assert kwargs["Force"] is False
        self.volumes[0].update(State="available", Attachments=[])

    def delete_volume(self, **kwargs: Any) -> None:
        if self.fail_delete:
            raise PermissionError("delete denied")
        self.volumes.clear()


def adapter(ec2: Ec2) -> RestoreVolume:
    return RestoreVolume(
        ec2,
        {
            "project": "wishicraft",
            "stage": "dev",
            "system_id": "test",
            "operation_id": "op-restore",
            "source_snapshot_id": "snap-0123456789abcdef0",
            "source_volume_id": "vol-aaaaaaaaaaaaaaaaa",
            "game_id": "game-test",
        },
        az="test-az",
        instance="i-test",
    )


def test_create_lost_reply_attach_cleanup_retry() -> None:
    ec2 = Ec2()
    volume = adapter(ec2)
    ec2.lost_create = True
    with pytest.raises(TimeoutError):
        volume.create()
    identity = volume.create()
    assert ec2.creates == 1
    assert volume.attach(identity) is False
    assert volume.attach(identity) is True
    with pytest.raises(ValueError, match="STOPPED_HOST"):
        volume.cleanup(identity, instance_stopped=False, delete_intent=False)
    assert volume.cleanup(identity, instance_stopped=True, delete_intent=False) == "DETACHING"
    assert (
        volume.cleanup(identity, instance_stopped=True, delete_intent=False)
        == "DELETE_INTENT_REQUIRED"
    )
    ec2.fail_delete = True
    with pytest.raises(PermissionError):
        volume.cleanup(identity, instance_stopped=True, delete_intent=True)
    assert volume.read(identity) is not None
    ec2.fail_delete = False
    assert volume.cleanup(identity, instance_stopped=True, delete_intent=True) == "DELETING"
    assert not ec2.volumes


@pytest.mark.parametrize(
    "field,value",
    [
        ("Encrypted", False),
        ("SnapshotId", "wrong"),
        ("AvailabilityZone", "wrong"),
        ("VolumeId", "vol-aaaaaaaaaaaaaaaaa"),
        ("Tags", []),
    ],
)
def test_foreign_volume_never_mutated(field: str, value: Any) -> None:
    ec2 = Ec2()
    volume = adapter(ec2)
    identity = volume.create()
    ec2.volumes[0][field] = value
    with pytest.raises(ValueError):
        volume.attach(identity)
    with pytest.raises(ValueError):
        volume.cleanup(identity, instance_stopped=True, delete_intent=True)
    assert ec2.volumes
