"""Fixed operator payload, executed through authenticated SSM during planned maintenance."""

# ruff: noqa: UP017 -- AL2023 Python 3.9
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wishicraft.artifacts import restore_tree
from wishicraft.artifacts import targeted_runtime as host

MOUNT = Path("/mnt/wishicraft-restore")
OWNER_UID = 0
OWNER_GID = 0
HELPERS = Path("/usr/local/libexec/wishicraft")


def install_helpers(updates: dict[str, Any]) -> None:
    """Only two reviewed helper predecessors; never repair arbitrary runtime drift."""
    predecessors = {
        "reset_worlds.py": "7dc80ce2469c454a32cb5c2dd6ab673ef1e216544c99acf057bb693d81f61b41",
        "world_import.py": "0a934cff209c9214bba66a8b8bbd81cc8c865b3b0e411ddf4e1910cfe2c85d70",
    }
    if set(updates) != set(predecessors):
        raise ValueError("RESTORE_HELPER_SET")
    parent = HELPERS
    for name, previous in predecessors.items():
        target = parent / name
        info = target.lstat()
        value = updates[name]
        compile(value, name, "exec")
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != OWNER_UID
            or info.st_gid != OWNER_GID
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o644
            or hashlib.sha256(target.read_bytes()).hexdigest()
            not in {previous, hashlib.sha256(value.encode()).hexdigest()}
        ):
            raise ValueError("RESTORE_HELPER_PREDECESSOR")
    for name, previous in predecessors.items():
        target = parent / name
        value = updates[name]
        if target.read_text() == value:
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != previous:
            raise ValueError("RESTORE_HELPER_RACE")
        backup = host.ROOT / ("restore-predecessor-" + previous)
        if backup.exists():
            if backup.is_symlink() or hashlib.sha256(backup.read_bytes()).hexdigest() != previous:
                raise ValueError("RESTORE_HELPER_BACKUP")
        else:
            host.atomic(backup, target.read_text())
        descriptor, temporary = tempfile.mkstemp(dir=parent, prefix=".restore-helper-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(value)
                os.fchmod(stream.fileno(), 0o644)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            host.reset_module().sync_directory(parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def run(envelope: dict[str, Any]) -> dict[str, Any]:
    plan = envelope["plan"]
    with (host.ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = json.loads(host.CONFIG.read_text())

        def verify() -> None:
            if (
                datetime.now(timezone.utc).timestamp() + 60 >= envelope["expires_at"]
                or host.actual_instance() != envelope["instance_id"]
                or config["instance_id"] != envelope["instance_id"]
                or hashlib.sha256((host.ARTIFACTS / "manifest.json").read_bytes()).hexdigest()
                != envelope["config_digest"]
                or host.item(config, "locks_table", "lock_name", config["lock_name"])
                or host.inspect()
            ):
                raise ValueError("RESTORE_HOST_FENCE")
            host.stopped_environment()
            host.execute(
                [
                    "bash",
                    "-c",
                    'set -aeu; source /etc/wishicraft/host-runtime.env; "$MOUNT_GUARD" --verify',
                ]
            )
            current = host.item(config, "games_table", "game_id", plan["game_id"])
            package = host.package_module().registered(
                current,
                json.loads((host.ARTIFACTS / "manifest.json").read_text()),
                envelope["config_digest"],
            )
            expected_world = plan["previous_world"]
            if envelope.get("action") == "verify-rollback":
                expected_world = {
                    **expected_world,
                    "current_id": plan["operation_id"],
                    "generation": plan["target_generation"],
                    "generation_counter": plan["target_generation"],
                }
            if current["world"] != expected_world or package != plan["package"]:
                raise ValueError("RESTORE_CURRENT_CHANGED")

        verify()
        if envelope.get("action") == "verify-rollback":
            previous = Path(plan["previous_data_source"])
            observed = restore_tree.inspect(previous, plan)
            if observed != envelope["previous_tree"]:
                raise ValueError("RESTORE_ROLLBACK_TREE_CHANGED")
            verify()
            return {
                "operation_id": plan["operation_id"],
                "rollback_verified": True,
                "previous_tree": observed,
                "maintenance_id": envelope["maintenance_id"],
            }
        install_helpers(envelope["helper_updates"])
        verify()
        volume = envelope["volume_id"]
        if re.fullmatch(r"vol-[a-f0-9]{17}", volume) is None or volume == plan["source_volume_id"]:
            raise ValueError("RESTORE_VOLUME_ID")
        devices = json.loads(
            host.execute(["lsblk", "--json", "--output", "PATH,SERIAL,TYPE,FSTYPE,MOUNTPOINTS"])
        )["blockdevices"]
        matches = [d for d in devices if d.get("serial") == volume.replace("-", "")]
        if (
            len(matches) != 1
            or matches[0].get("type") != "disk"
            or matches[0].get("fstype") != "xfs"
            or matches[0].get("children")
        ):
            raise ValueError("RESTORE_DEVICE_IDENTITY")
        device = matches[0]["path"]
        if re.fullmatch(r"/dev/nvme[0-9]+n1", device) is None:
            raise ValueError("RESTORE_DEVICE_PATH")
        mount = MOUNT
        points = [v for v in matches[0].get("mountpoints", []) if v]
        if points and points != [str(mount)]:
            raise ValueError("RESTORE_DEVICE_IN_USE")
        if not mount.exists():
            mount.mkdir(mode=0o700)
        info = mount.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != OWNER_UID
            or info.st_mode & (0o022 if points else 0o077)
        ):
            raise ValueError("RESTORE_MOUNT_DIRECTORY")
        host.execute(["blockdev", "--setro", device])
        if host.execute(["blockdev", "--getro", device]).strip() != "1":
            raise ValueError("RESTORE_DEVICE_NOT_READ_ONLY")
        if not points:
            if list(mount.iterdir()):
                raise ValueError("RESTORE_MOUNT_NOT_EMPTY")
            host.execute(
                [
                    "mount",
                    "-t",
                    "xfs",
                    "-o",
                    "ro,nouuid,norecovery,nodev,nosuid,noexec",
                    device,
                    str(mount),
                ]
            )
        observed = json.loads(
            host.execute(
                [
                    "findmnt",
                    "--json",
                    "--mountpoint",
                    str(mount),
                    "--output",
                    "SOURCE,FSTYPE,OPTIONS",
                ]
            )
        )["filesystems"]
        if (
            len(observed) != 1
            or observed[0]["source"] != device
            or observed[0]["fstype"] != "xfs"
            or not {"ro", "norecovery", "nodev", "nosuid", "noexec"}.issubset(
                observed[0]["options"].split(",")
            )
        ):
            raise ValueError("RESTORE_READ_ONLY_MOUNT")
        result = restore_tree.prepare(plan, mount, atomic=host.atomic, verify=verify)
        verify()
        host.execute(["umount", str(mount)])
        mount.rmdir()
        return {
            "operation_id": plan["operation_id"],
            "volume_id": volume,
            "unmounted": True,
            **{
                k: result[k]
                for k in (
                    "phase",
                    "prepared_tree",
                    "source_world_tree",
                    "source_tree",
                    "previous_tree",
                )
            },
        }
