from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_SCRIPT = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "minecraft_artifact_install.sh"
GAME_SCRIPT = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "minecraft_game_setup.sh"


def _stub(path: Path, name: str, body: str) -> None:
    command = path / name
    command.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    command.chmod(0o755)


def _artifact_environment(
    tmp_path: Path, *, curl_result: int = 0, verification_value: str | None = None
) -> dict[str, str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    _stub(
        stubs,
        "curl",
        f'[[ "{curl_result}" == 0 ]] || exit {curl_result}\n'
        'destination="${@: -2:1}"\nprintf artifact > "$destination"\nprintf curl >> "$TEST_LOG"',
    )
    _stub(stubs, "stat", 'printf "%s" "${ARTIFACT_TEST_SIZE:-8}"')
    _stub(
        stubs,
        "sha1sum",
        'printf \'%s  %s\\n\' "${ARTIFACT_TEST_SHA1:-$ARTIFACT_SHA1}" "$1"',
    )
    _stub(
        stubs,
        "sha256sum",
        'printf \'%s  %s\\n\' "${ARTIFACT_TEST_SHA256:-$ARTIFACT_SHA256}" "$1"',
    )
    _stub(stubs, "chown", ":")
    _stub(stubs, "chmod", ":")
    guard = tmp_path / "guard"
    guard.write_text("#!/usr/bin/env bash\nexit ${MOUNT_GUARD_RESULT:-0}\n", encoding="utf-8")
    guard.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "MOUNT_GUARD": str(guard),
        "ARTIFACT_URL": "https://piston-data.mojang.com/v1/objects/example/server.jar",
        "ARTIFACT_SHA1": "a" * 40,
        "ARTIFACT_SHA256": "b" * 64,
        "ARTIFACT_SIZE": "8",
        "ARTIFACT_PATH": str(tmp_path / "packages" / "server.jar"),
        "TEST_LOG": str(tmp_path / "log"),
    }
    if verification_value == "size":
        environment["ARTIFACT_TEST_SIZE"] = "9"
    if verification_value == "sha1":
        environment["ARTIFACT_TEST_SHA1"] = "0" * 40
    if verification_value == "sha256":
        environment["ARTIFACT_TEST_SHA256"] = "0" * 64
    return environment


def test_minecraft_bootstrap_scripts_have_valid_shell_syntax() -> None:
    for script in (ARTIFACT_SCRIPT, GAME_SCRIPT):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_artifact_download_is_verified_and_atomically_placed(tmp_path: Path) -> None:
    environment = _artifact_environment(tmp_path)

    result = subprocess.run(
        ["bash", str(ARTIFACT_SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode == 0, result.stderr
    assert Path(environment["ARTIFACT_PATH"]).read_text(encoding="utf-8") == "artifact"
    assert (tmp_path / "log").read_text(encoding="utf-8") == "curl"

    result = subprocess.run(
        ["bash", str(ARTIFACT_SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "log").read_text(encoding="utf-8") == "curl"


@pytest.mark.parametrize("mount_guard_result,curl_result", ((1, 0), (0, 1)))
def test_artifact_bootstrap_fails_without_placing_unverified_file(
    tmp_path: Path, mount_guard_result: int, curl_result: int
) -> None:
    environment = _artifact_environment(tmp_path, curl_result=curl_result)
    environment["MOUNT_GUARD_RESULT"] = str(mount_guard_result)

    result = subprocess.run(
        ["bash", str(ARTIFACT_SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode != 0
    assert not Path(environment["ARTIFACT_PATH"]).exists()


@pytest.mark.parametrize("verification_value", ("size", "sha1", "sha256"))
def test_artifact_bootstrap_rejects_each_checksum_or_size_mismatch(
    tmp_path: Path, verification_value: str
) -> None:
    environment = _artifact_environment(tmp_path, verification_value=verification_value)

    result = subprocess.run(
        ["bash", str(ARTIFACT_SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode != 0
    assert not Path(environment["ARTIFACT_PATH"]).exists()


def test_game_setup_writes_only_the_initial_game_configuration(tmp_path: Path) -> None:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in {
        "getent": "exit 1",
        "id": "exit 1",
        "groupadd": 'printf groupadd >> "$TEST_LOG"',
        "useradd": 'printf useradd >> "$TEST_LOG"',
        "chown": ":",
        "chmod": ":",
        "install": (
            'if [[ "$1" == "-d" ]]; then for value in "$@"; '
            'do [[ "$value" == /* ]] && mkdir -p "$value"; done; fi'
        ),
    }.items():
        _stub(stubs, name, body)
    guard = tmp_path / "guard"
    guard.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    guard.chmod(0o755)
    mount = tmp_path / "mount"
    artifact = mount / "packages" / "vanilla" / "26.2" / "server.jar"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("jar", encoding="utf-8")
    game = mount / "games" / "game-vanilla-main"
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "TEST_LOG": str(tmp_path / "log"),
        "MOUNT_GUARD": str(guard),
        "MOUNT_PATH": str(mount),
        "GAME_ID": "game-vanilla-main",
        "GAME_DIRECTORY": str(game),
        "ARTIFACT_PATH": str(artifact),
        "MINECRAFT_PORT": "25565",
        "PROFILE_NAME": "NEWISHIN_",
        "PROFILE_UUID": "e912ab95758e4b7fb32e292eda293104",
    }

    result = subprocess.run(
        ["bash", str(GAME_SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode == 0, result.stderr
    server = game / "server"
    assert (server / "eula.txt").read_text(encoding="utf-8") == "eula=true\n"
    properties = (server / "server.properties").read_text(encoding="utf-8")
    assert "online-mode=true" in properties
    assert "white-list=true" in properties
    assert "enforce-whitelist=true" in properties
    assert "enable-rcon=false" in properties
    assert "management-server-enabled=false" in properties
    assert (server / "whitelist.json").read_text(encoding="utf-8") == (
        '[{"uuid":"e912ab95758e4b7fb32e292eda293104","name":"NEWISHIN_"}]\n'
    )

    with (server / "server.properties").open("a", encoding="utf-8") as properties_file:
        properties_file.write("online-mode=false\n")
    result = subprocess.run(
        ["bash", str(GAME_SCRIPT), "--verify"],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode != 0
