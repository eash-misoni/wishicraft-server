from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from wishicraft.artifacts import restore_host, restore_tree
from wishicraft.artifacts import targeted_runtime as host


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
    config.write_text(json.dumps({"instance_id": "i-test", "lock_name": "global"}))
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "CONFIG", config)
    monkeypatch.setattr(host, "ARTIFACTS", artifacts)
    monkeypatch.setattr(host, "actual_instance", lambda: "i-test")
    monkeypatch.setattr(host, "inspect", lambda: [])
    monkeypatch.setattr(host, "stopped_environment", lambda: None)
    monkeypatch.setattr(
        host, "item", lambda *args: {} if args[1] == "locks_table" else {"world": {}}
    )
    from types import SimpleNamespace

    monkeypatch.setattr(
        host, "package_module", lambda: SimpleNamespace(registered=lambda *args: {})
    )
    mount = tmp_path / "mount"
    monkeypatch.setattr(restore_host, "MOUNT", mount)
    monkeypatch.setattr(restore_host, "OWNER_UID", os.getuid())
    monkeypatch.setattr(restore_host, "install_helpers", lambda updates: None)
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
                "previous_world": {},
                "package": {},
                "source_volume_id": "vol-other",
                "operation_id": "op-test",
            },
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
