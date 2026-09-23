from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from wishicraft.artifacts import restore_host, restore_tree
from wishicraft.artifacts import targeted_runtime as host


@pytest.mark.parametrize(
    "change", ["incident", "replaced", "expired", "system", "revision", "operation"]
)
def test_host_rechecks_current_authority_at_each_boundary(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    import copy
    import time

    lease = {
        "id": "maint-1",
        "status": "ACTIVE",
        "stage": "dev",
        "started_at": int(time.time()) - 10,
        "expires_at": int(time.time()) + 600,
    }
    envelope = {
        "plan": {"system_id": "system", "stage": "dev"},
        "maintenance": copy.deepcopy(lease),
        "maintenance_id": "maint-1",
        "instance_id": "i-test",
        "system_state_table": "state",
        "protection_revision": 7,
    }
    state = {
        "system_id": "system",
        "maintenance": lease,
        "desired_state": "STOPPED",
        "target_instance_id": "i-test",
        "desired_revision": 7,
    }
    config = {"system_id": "system"}
    monkeypatch.setattr(host, "item", lambda *args: state)
    restore_host.maintenance_fence(config, envelope)
    if change == "incident":
        lease["status"] = "INCIDENT"
    elif change == "replaced":
        lease["id"] = "maint-2"
    elif change == "expired":
        lease["expires_at"] = int(time.time()) - 1
        envelope["maintenance"] = copy.deepcopy(lease)
    elif change == "system":
        config["system_id"] = "other"
    elif change == "revision":
        state["desired_revision"] = 9
    else:
        state["current_operation_id"] = "op-active"
    with pytest.raises(ValueError, match="RESTORE_HOST_"):
        restore_host.maintenance_fence(config, envelope)


def test_helper_upgrade_is_exact_and_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    root = tmp_path / "receipts"
    root.mkdir()
    monkeypatch.setattr(restore_host, "HELPERS", helpers)
    monkeypatch.setattr(restore_host, "OWNER_UID", os.getuid())
    monkeypatch.setattr(restore_host, "OWNER_GID", os.getgid())
    monkeypatch.setattr(host, "ROOT", root)
    updates = {}
    for name in ("reset_worlds.py", "world_import.py"):
        previous = subprocess.check_output(
            [
                "git",
                "show",
                "40015d233e192b7a132c1840c1483c3f80a08fa6:src/wishicraft/artifacts/" + name,
            ]
        )
        path = helpers / name
        path.write_bytes(previous)
        path.chmod(0o644)
        updates[name] = previous.decode() + "\n# synthetic successor\n"
    restore_host.install_helpers(updates)
    times = {p.name: p.stat().st_mtime_ns for p in helpers.iterdir()}
    restore_host.install_helpers(updates)
    assert times == {p.name: p.stat().st_mtime_ns for p in helpers.iterdir()}
    (helpers / "world_import.py").write_text("# unrelated drift\n")
    with pytest.raises(ValueError, match="PREDECESSOR"):
        restore_host.install_helpers(updates)


def test_read_only_mount_precedes_tree_read_and_is_unmounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "manifest.json").write_text("{}")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"instance_id": "i-test", "lock_name": "global", "system_id": "system"})
    )
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "CONFIG", config)
    monkeypatch.setattr(host, "ARTIFACTS", artifacts)
    monkeypatch.setattr(host, "actual_instance", lambda: "i-test")
    monkeypatch.setattr(host, "inspect", lambda: [])
    monkeypatch.setattr(host, "stopped_environment", lambda: None)
    import time

    lease = {
        "id": "maint-test",
        "status": "ACTIVE",
        "stage": "dev",
        "started_at": int(time.time()) - 10,
        "expires_at": int(time.time()) + 600,
    }
    state = {
        "system_id": "system",
        "target_instance_id": "i-test",
        "desired_state": "STOPPED",
        "desired_revision": 1,
        "maintenance": lease,
    }
    monkeypatch.setattr(
        host,
        "item",
        lambda *args: (
            state
            if args[1] == "restore_state_table"
            else {}
            if args[1] == "locks_table"
            else {"world": {}}
        ),
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        host, "package_module", lambda: SimpleNamespace(registered=lambda *args: {})
    )
    mount = tmp_path / "mount"
    monkeypatch.setattr(restore_host, "MOUNT", mount)
    monkeypatch.setattr(restore_host, "OWNER_UID", os.getuid())
    monkeypatch.setattr(restore_host, "install_helpers", lambda updates, **kwargs: None)
    commands: list[list[str]] = []
    volume = "vol-0123456789abcdef0"

    def execute(args: list[str], **kwargs: Any) -> str:
        commands.append(args)
        if args[0] == "lsblk":
            return json.dumps(
                {
                    "blockdevices": [
                        {
                            "serial": volume.replace("-", ""),
                            "path": "/dev/nvme2n1",
                            "type": "disk",
                            "fstype": "xfs",
                            "mountpoints": [],
                        }
                    ]
                }
            )
        if args[:2] == ["blockdev", "--getro"]:
            return "1"
        if args[0] == "findmnt":
            return json.dumps(
                {
                    "filesystems": [
                        {
                            "source": "/dev/nvme2n1",
                            "fstype": "xfs",
                            "options": "ro,nouuid,norecovery,nodev,nosuid,noexec",
                        }
                    ]
                }
            )
        return ""

    monkeypatch.setattr(host, "execute", execute)

    def prepare(plan: Any, source: Path, **kwargs: Any) -> dict[str, Any]:
        assert source == mount
        assert any(c[:2] == ["blockdev", "--setro"] for c in commands)
        assert any(
            c[0] == "mount" and "ro,nouuid,norecovery,nodev,nosuid,noexec" in c for c in commands
        )
        return {
            "phase": "prepared",
            "prepared_tree": {},
            "source_world_tree": {},
            "source_tree": {},
            "previous_tree": {},
        }

    monkeypatch.setattr(restore_tree, "prepare", prepare)
    import hashlib
    import time

    result = restore_host.run(
        {
            "plan": {
                "game_id": "game-test",
                "system_id": "system",
                "stage": "dev",
                "previous_world": {},
                "package": {},
                "source_volume_id": "vol-other",
                "operation_id": "op-test",
            },
            "maintenance": lease,
            "maintenance_id": lease["id"],
            "system_state_table": "state",
            "protection_revision": 1,
            "volume_id": volume,
            "instance_id": "i-test",
            "expires_at": int(time.time()) + 600,
            "config_digest": hashlib.sha256(b"{}").hexdigest(),
            "helper_updates": {},
        }
    )
    assert result["unmounted"] is True
    assert commands[-1] == ["umount", str(mount)]
    assert not mount.exists()
