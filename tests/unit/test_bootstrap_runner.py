from __future__ import annotations

import base64
import gzip
import hashlib
import io
import os
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path

import pytest

from infrastructure.constructs.bootstrap_bundle import FILES, build_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "bootstrap_runner.sh"
BOOTSTRAP_DIRECTORY = REPOSITORY_ROOT / "infrastructure" / "bootstrap"


def _archive(members: Iterable[tuple[str, bytes, bytes | None, str]]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, content, member_type, linkname in members:
                member = tarfile.TarInfo(name)
                member.type = member_type or tarfile.REGTYPE
                member.linkname = linkname
                member.size = len(content) if member.isfile() else 0
                archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
    return raw.getvalue()


def _valid_members() -> list[tuple[str, bytes, bytes | None, str]]:
    return [(name, b'#!/bin/bash\ntouch "$MARKER"\n', None, "") for name in FILES]


def _run_runner(
    tmp_path: Path, archive: bytes, *, digest: str | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    destination = tmp_path / "destination"
    destination.mkdir()
    temp_root = tmp_path / "temporary"
    temp_root.mkdir()
    environment = {
        **os.environ,
        "BUNDLE_BASE64": base64.b64encode(archive).decode("ascii"),
        "BUNDLE_SHA256": digest or hashlib.sha256(archive).hexdigest(),
        "BUNDLE_MEMBERS": "\n".join(FILES),
        "BUNDLE_DEST": str(destination),
        "BUNDLE_TEMP_ROOT": str(temp_root),
        "RUNNER_TEST_MODE": "1",
        "MARKER": str(tmp_path / "bootstrap-ran"),
    }
    result = subprocess.run(
        ["bash", str(RUNNER)], text=True, capture_output=True, env=environment, check=False
    )
    return result, destination, temp_root


def test_bootstrap_runner_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(RUNNER)], check=True)


def test_bootstrap_bundle_is_deterministic_and_runner_extracts_only_allowlisted_files(
    tmp_path: Path,
) -> None:
    first = build_bundle(BOOTSTRAP_DIRECTORY)
    second = build_bundle(BOOTSTRAP_DIRECTORY)
    assert first == second

    result, destination, temp_root = _run_runner(tmp_path, first)

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in destination.iterdir()) == sorted(FILES)
    assert all(not path.is_symlink() and path.is_file() for path in destination.iterdir())
    assert all(path.stat().st_mode & 0o777 == 0o755 for path in destination.iterdir())
    assert all(
        (destination / name).read_bytes() == (BOOTSTRAP_DIRECTORY / name).read_bytes()
        for name in FILES
    )
    assert not (tmp_path / "bootstrap-ran").exists()
    assert list(temp_root.iterdir()) == []


def test_bootstrap_runner_accepts_canonical_members_without_rewriting_them(
    tmp_path: Path,
) -> None:
    archive = build_bundle(BOOTSTRAP_DIRECTORY)
    first, destination, temporary = _run_runner(tmp_path, archive)
    assert first.returncode == 0, first.stderr
    before = {
        name: ((destination / name).read_bytes(), (destination / name).stat().st_mtime_ns)
        for name in FILES
    }
    environment = {
        **os.environ,
        "BUNDLE_BASE64": base64.b64encode(archive).decode("ascii"),
        "BUNDLE_SHA256": hashlib.sha256(archive).hexdigest(),
        "BUNDLE_MEMBERS": "\n".join(FILES),
        "BUNDLE_DEST": str(destination),
        "BUNDLE_TEMP_ROOT": str(temporary),
        "RUNNER_TEST_MODE": "1",
        "MARKER": str(tmp_path / "bootstrap-ran"),
    }

    second = subprocess.run(
        ["bash", str(RUNNER)], text=True, capture_output=True, env=environment, check=False
    )

    assert second.returncode == 0, second.stderr
    assert {
        name: ((destination / name).read_bytes(), (destination / name).stat().st_mtime_ns)
        for name in FILES
    } == before


def test_bootstrap_runner_stops_before_writing_when_a_member_conflicts(tmp_path: Path) -> None:
    archive = build_bundle(BOOTSTRAP_DIRECTORY)
    destination = tmp_path / "destination"
    destination.mkdir()
    conflict = destination / FILES[0]
    conflict.write_bytes(b"not the canonical bootstrap script\n")
    conflict.chmod(0o755)
    before = (conflict.read_bytes(), conflict.stat().st_mtime_ns)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    environment = {
        **os.environ,
        "BUNDLE_BASE64": base64.b64encode(archive).decode("ascii"),
        "BUNDLE_SHA256": hashlib.sha256(archive).hexdigest(),
        "BUNDLE_MEMBERS": "\n".join(FILES),
        "BUNDLE_DEST": str(destination),
        "BUNDLE_TEMP_ROOT": str(temporary),
        "RUNNER_TEST_MODE": "1",
        "MARKER": str(tmp_path / "bootstrap-ran"),
    }

    result = subprocess.run(
        ["bash", str(RUNNER)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode != 0
    assert (conflict.read_bytes(), conflict.stat().st_mtime_ns) == before
    assert sorted(path.name for path in destination.iterdir()) == [FILES[0]]
    assert not (tmp_path / "bootstrap-ran").exists()
    assert list(temporary.iterdir()) == []


def test_bootstrap_runner_rejects_existing_symlink_without_replacing_it(tmp_path: Path) -> None:
    archive = build_bundle(BOOTSTRAP_DIRECTORY)
    destination = tmp_path / "destination"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside\n")
    link = destination / FILES[0]
    link.symlink_to(outside)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    environment = {
        **os.environ,
        "BUNDLE_BASE64": base64.b64encode(archive).decode("ascii"),
        "BUNDLE_SHA256": hashlib.sha256(archive).hexdigest(),
        "BUNDLE_MEMBERS": "\n".join(FILES),
        "BUNDLE_DEST": str(destination),
        "BUNDLE_TEMP_ROOT": str(temporary),
        "RUNNER_TEST_MODE": "1",
        "MARKER": str(tmp_path / "bootstrap-ran"),
    }

    result = subprocess.run(
        ["bash", str(RUNNER)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode != 0
    assert link.is_symlink()
    assert outside.read_bytes() == b"outside\n"
    assert sorted(path.name for path in destination.iterdir()) == [FILES[0]]
    assert not (tmp_path / "bootstrap-ran").exists()
    assert list(temporary.iterdir()) == []


@pytest.mark.parametrize(
    "archive",
    [
        pytest.param(_archive(_valid_members()), id="checksum-mismatch"),
        pytest.param(b"not-a-gzip-archive", id="corrupt-archive"),
        pytest.param(_archive([("/absolute/path", b"x", None, "")]), id="absolute-path"),
        pytest.param(_archive([("../escape.sh", b"x", None, "")]), id="parent-path"),
        pytest.param(_archive([("dir/../../escape.sh", b"x", None, "")]), id="nested-parent-path"),
        pytest.param(
            _archive([(FILES[0], b"", tarfile.SYMTYPE, "target")] + _valid_members()[1:]),
            id="symlink",
        ),
        pytest.param(
            _archive([(FILES[0], b"", tarfile.LNKTYPE, FILES[1])] + _valid_members()[1:]),
            id="hardlink",
        ),
        pytest.param(
            _archive(_valid_members() + [("unexpected.sh", b"x", None, "")]),
            id="unexpected-regular-file",
        ),
        pytest.param(_archive(_valid_members()[:-1]), id="missing-required-member"),
        pytest.param(
            _archive(_valid_members() + [(FILES[0], b"duplicate", None, "")]),
            id="duplicate-member",
        ),
        pytest.param(
            _archive([(FILES[0], b"", tarfile.FIFOTYPE, "")] + _valid_members()[1:]),
            id="fifo",
        ),
    ],
)
def test_bootstrap_runner_rejects_unsafe_archives_without_extracting_or_running_scripts(
    tmp_path: Path, archive: bytes, request: pytest.FixtureRequest
) -> None:
    digest = "0" * 64 if request.node.callspec.id == "checksum-mismatch" else None

    result, destination, temp_root = _run_runner(tmp_path, archive, digest=digest)

    assert result.returncode != 0
    assert list(destination.iterdir()) == []
    assert not (tmp_path / "bootstrap-ran").exists()
    assert list(temp_root.iterdir()) == []
