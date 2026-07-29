from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from infrastructure.constructs.java_runtime import resolve_java_package
from wishicraft.config import load_configuration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "java_runtime_install.sh"


def _write_stub(path: Path, name: str, body: str) -> None:
    command = path / name
    command.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    command.chmod(0o755)


def _run_script(
    tmp_path: Path,
    *,
    runtime: str = "corretto-25-headless",
    dnf_failure: bool = False,
    rpm_missing: bool = False,
    java_missing: bool = False,
    java_version: str = 'openjdk version "25.0.4"\nOpenJDK Runtime Environment Corretto-25.0.4.7.1',
) -> tuple[subprocess.CompletedProcess[str], Path]:
    stubs = tmp_path / "stubs"
    state = tmp_path / "state"
    stubs.mkdir()
    state.mkdir()
    _write_stub(
        stubs,
        "dnf",
        'printf "%s\\n" "$*" >> "$TEST_STATE/dnf_calls"\n'
        '[[ "${DNF_FAILURE:-0}" == "0" ]] || exit 1\n'
        'if [[ ! -f "$TEST_STATE/installed" ]]; then touch "$TEST_STATE/installed"; fi',
    )
    _write_stub(
        stubs,
        "rpm",
        '[[ "${RPM_MISSING:-0}" == "0" && -f "$TEST_STATE/installed" ]] || exit 1',
    )
    _write_stub(
        stubs,
        "java",
        '[[ "${JAVA_MISSING:-0}" == "0" ]] || exit 127\nprintf "%b\\n" "$JAVA_VERSION_OUTPUT" >&2',
    )
    (state / "dnf_calls").touch()
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "TEST_STATE": str(state),
        "JAVA_RUNTIME": runtime,
        "DNF_FAILURE": "1" if dnf_failure else "0",
        "RPM_MISSING": "1" if rpm_missing else "0",
        "JAVA_MISSING": "1" if java_missing else "0",
        "JAVA_VERSION_OUTPUT": java_version,
    }
    return (
        subprocess.run(
            ["bash", str(SCRIPT)],
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        ),
        state,
    )


def test_stage_java_runtime_and_allowlist_resolve_to_the_corretto_25_package() -> None:
    assert load_configuration(REPOSITORY_ROOT, "dev").stage.java_runtime == "corretto-25-headless"
    assert load_configuration(REPOSITORY_ROOT, "prod").stage.java_runtime == "corretto-25-headless"
    assert resolve_java_package("corretto-25-headless") == "java-25-amazon-corretto-headless"


def test_unsupported_java_runtime_is_rejected_without_a_fallback() -> None:
    with pytest.raises(ValueError, match="Unsupported Phase 1 Java runtime"):
        resolve_java_package("corretto-99-headless")


def test_java_runtime_script_installs_and_verifies_corretto_25_idempotently(tmp_path: Path) -> None:
    result, state = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert state.joinpath("dnf_calls").read_text(encoding="utf-8") == (
        "install -y java-25-amazon-corretto-headless\n"
    )

    second_result = subprocess.run(
        ["bash", str(SCRIPT)],
        check=False,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'stubs'}:{os.environ['PATH']}",
            "TEST_STATE": str(state),
            "JAVA_RUNTIME": "corretto-25-headless",
            "DNF_FAILURE": "0",
            "RPM_MISSING": "0",
            "JAVA_MISSING": "0",
            "JAVA_VERSION_OUTPUT": 'openjdk version "25.0.4" Corretto',
        },
    )
    assert second_result.returncode == 0, second_result.stderr
    assert (
        state.joinpath("dnf_calls")
        .read_text(encoding="utf-8")
        .count("java-25-amazon-corretto-headless")
        == 2
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"runtime": "corretto-99-headless"}, "unsupported Java runtime"),
        ({"dnf_failure": True}, ""),
        ({"rpm_missing": True}, ""),
        ({"java_missing": True}, "java command failed"),
        ({"java_version": 'openjdk version "24.0.1" Corretto'}, "Java major version is not 25"),
        ({"java_version": 'openjdk version "25.0.4" OpenJDK'}, "Java runtime is not Corretto"),
    ),
)
def test_java_runtime_script_fails_closed_when_install_or_verification_fails(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    result, _ = _run_script(tmp_path, **cast(Any, kwargs))

    assert result.returncode != 0
    if message:
        assert message in result.stderr


def test_java_runtime_script_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
