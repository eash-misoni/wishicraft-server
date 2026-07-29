from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "data_volume_mount.sh"


def _write_stub(path: Path, name: str, body: str) -> None:
    command = path / name
    command.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    command.chmod(0o755)


def _command_stubs(path: Path) -> None:
    _write_stub(
        path,
        "lsblk",
        'printf "%s\\n" "${LSBLK_ROWS:-/dev/nvme0n1 volroot}"',
    )
    _write_stub(
        path,
        "blkid",
        'if [[ "${*: -2:1}" == "TYPE" ]]; then\n'
        '  value="$(cat "$TEST_STATE/filesystem_type")"\n'
        '  [[ -n "$value" ]] || exit 2\n'
        '  printf "%s\\n" "$value"\n'
        "else\n"
        '  [[ -n "$(cat "$TEST_STATE/filesystem_type")" ]] || exit 2\n'
        '  cat "$TEST_STATE/uuid"\n'
        "fi",
    )
    _write_stub(path, "wipefs", 'cat "$TEST_STATE/signatures"')
    _write_stub(path, "readlink", 'printf "%s\\n" "${@: -1}"')
    _write_stub(
        path,
        "mkfs.xfs",
        'printf "%s\\n" "$*" >> "$TEST_STATE/mkfs_calls"\n'
        'printf "xfs" > "$TEST_STATE/filesystem_type"\n'
        'printf "xfs" > "$TEST_STATE/signatures"',
    )
    _write_stub(
        path,
        "mount",
        'printf "%s\\n" "$*" >> "$TEST_STATE/mount_calls"\n'
        'printf "mounted" > "$TEST_STATE/mounted"',
    )
    _write_stub(
        path,
        "findmnt",
        '[[ -f "$TEST_STATE/mounted" ]] || exit 1\n'
        '[[ "$2" == "--target" ]] && exit 0\n'
        'case "$3" in\n'
        '  SOURCE) printf "%s\\n" "${FINDMNT_SOURCE:-/dev/nvme1n1}" ;;\n'
        '  UUID) cat "$TEST_STATE/uuid" ;;\n'
        '  FSTYPE) printf "%s\\n" "${FINDMNT_TYPE:-xfs}" ;;\n'
        "  *) exit 1 ;;\n"
        "esac",
    )
    _write_stub(path, "sleep", ":")


def _run_script(
    tmp_path: Path,
    *,
    filesystem_type: str = "",
    signatures: str = "",
    fstab: str = "",
    mounted: bool = False,
    mount_path_contents: bool = False,
    rows: str = "/dev/nvme0n1 volroot\n/dev/nvme1n1 voldata",
    extra_environment: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    stubs = tmp_path / "stubs"
    state = tmp_path / "state"
    mount_path = tmp_path / "mount"
    stubs.mkdir(exist_ok=True)
    state.mkdir(exist_ok=True)
    _command_stubs(stubs)
    (state / "filesystem_type").write_text(filesystem_type, encoding="utf-8")
    (state / "signatures").write_text(signatures, encoding="utf-8")
    (state / "uuid").write_text("uuid-data", encoding="utf-8")
    (state / "mkfs_calls").write_text("", encoding="utf-8")
    (state / "mount_calls").write_text("", encoding="utf-8")
    if mounted:
        (state / "mounted").touch()
    if mount_path_contents:
        mount_path.mkdir()
        (mount_path / "unexpected").touch()
    fstab_path = tmp_path / "fstab"
    fstab_path.write_text(fstab, encoding="utf-8")
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "TEST_STATE": str(state),
        "DATA_VOLUME_ID": "vol-data",
        "MOUNT_PATH": str(mount_path),
        "FILESYSTEM_TYPE": "xfs",
        "WISHICRAFT_FSTAB_PATH": str(fstab_path),
        "WISHICRAFT_MOUNT_MARKER_PATH": str(state / "marker"),
        "WISHICRAFT_DEVICE_WAIT_ATTEMPTS": "2",
        "WISHICRAFT_DEVICE_WAIT_SECONDS": "0",
        "LSBLK_ROWS": rows,
    }
    if extra_environment:
        environment.update(extra_environment)
    return (
        subprocess.run(
            ["bash", str(SCRIPT)],
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        ),
        state,
        fstab_path,
    )


def test_data_volume_mount_script_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_empty_expected_volume_is_formatted_once_and_mounted_idempotently(tmp_path: Path) -> None:
    result, state, fstab = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (state / "mkfs_calls").read_text(encoding="utf-8").count("/dev/nvme1n1") == 1
    assert fstab.read_text(encoding="utf-8").splitlines() == [
        f"UUID=uuid-data {tmp_path / 'mount'} xfs defaults,nofail 0 2 # wishicraft-data-volume"
    ]
    assert (state / "marker").exists()

    rerun, rerun_state, rerun_fstab = _run_script(
        tmp_path,
        filesystem_type="xfs",
        signatures="xfs",
        fstab=fstab.read_text(encoding="utf-8"),
        mounted=True,
    )
    assert rerun.returncode == 0, rerun.stderr
    assert rerun_state.joinpath("mkfs_calls").read_text(encoding="utf-8") == ""
    assert rerun_state.joinpath("mount_calls").read_text(encoding="utf-8") == ""
    assert rerun_fstab.read_text(encoding="utf-8").count("wishicraft-data-volume") == 1


@pytest.mark.parametrize(
    ("filesystem_type", "signatures"),
    (("ext4", "ext4"), ("", "gpt")),
)
def test_existing_non_xfs_or_partition_signature_fails_without_mutation(
    tmp_path: Path, filesystem_type: str, signatures: str
) -> None:
    result, state, fstab = _run_script(
        tmp_path, filesystem_type=filesystem_type, signatures=signatures
    )

    assert result.returncode != 0
    assert (state / "mkfs_calls").read_text(encoding="utf-8") == ""
    assert (state / "mount_calls").read_text(encoding="utf-8") == ""
    assert fstab.read_text(encoding="utf-8") == ""
    assert not (state / "marker").exists()


def test_existing_xfs_is_reused_without_formatting(tmp_path: Path) -> None:
    result, state, _ = _run_script(tmp_path, filesystem_type="xfs", signatures="xfs")

    assert result.returncode == 0, result.stderr
    assert (state / "mkfs_calls").read_text(encoding="utf-8") == ""
    assert (state / "mount_calls").read_text(encoding="utf-8")


def test_missing_or_other_volume_never_selects_root_device(tmp_path: Path) -> None:
    result, state, fstab = _run_script(tmp_path, rows="/dev/nvme0n1 volroot")

    assert result.returncode != 0
    assert "timed out" in result.stderr
    assert (state / "mkfs_calls").read_text(encoding="utf-8") == ""
    assert fstab.read_text(encoding="utf-8") == ""


def test_conflicting_fstab_and_wrong_existing_mount_fail_closed(tmp_path: Path) -> None:
    conflict = f"UUID=other {tmp_path / 'mount'} xfs defaults,nofail 0 2\n"
    result, state, fstab = _run_script(
        tmp_path, filesystem_type="xfs", signatures="xfs", fstab=conflict
    )
    assert result.returncode != 0
    assert (state / "mount_calls").read_text(encoding="utf-8") == ""

    result, state, _ = _run_script(
        tmp_path,
        filesystem_type="xfs",
        signatures="xfs",
        mounted=True,
        extra_environment={"FINDMNT_SOURCE": "/dev/nvme0n1"},
    )
    assert result.returncode != 0
    assert not (state / "marker").exists()
    assert fstab.read_text(encoding="utf-8") == ""


def test_nonempty_unmounted_path_and_mismatched_mount_type_fail_closed(tmp_path: Path) -> None:
    nonempty_path = tmp_path / "nonempty"
    nonempty_path.mkdir()
    result, state, fstab = _run_script(
        nonempty_path,
        filesystem_type="xfs",
        signatures="xfs",
        mount_path_contents=True,
    )
    assert result.returncode != 0
    assert (state / "mount_calls").read_text(encoding="utf-8") == ""
    assert fstab.read_text(encoding="utf-8") == ""

    mismatch_path = tmp_path / "mismatch"
    mismatch_path.mkdir()
    result, state, fstab = _run_script(
        mismatch_path,
        filesystem_type="xfs",
        signatures="xfs",
        mounted=True,
        extra_environment={"FINDMNT_TYPE": "ext4"},
    )
    assert result.returncode != 0
    assert not (state / "marker").exists()
    assert fstab.read_text(encoding="utf-8") == ""
