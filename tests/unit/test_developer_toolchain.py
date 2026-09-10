from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DEV_ENV = ROOT / "tools" / "dev-env"
SETUP = ROOT / "tools" / "setup-dev-tools"


def make_executable(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def isolated_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "PATH": str(bin_dir),
        "SHELL": "/bin/sh",
    }
    make_executable(
        bin_dir,
        "uname",
        "[ \"${1:-}\" = -s ] && printf '%s\\n' TestOS || printf '%s\\n' test-arch",
    )
    return environment, bin_dir


def expose_system_tools(bin_dir: Path, names: tuple[str, ...]) -> None:
    for name in names:
        source = shutil.which(name)
        assert source is not None
        (bin_dir / name).symlink_to(source)


def test_check_reports_discovered_tools_and_optional_docker_absence(tmp_path: Path) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    versions = {
        "git": "git version test",
        "uv": "uv 0.test",
        "gh": "gh version 2.test",
        "node": "v22.test",
        "npm": "11.test",
        "npx": "11.test",
    }
    paths = {
        name: make_executable(bin_dir, name, f"printf '%s\\n' '{version}'")
        for name, version in versions.items()
    }
    environment["WISHICRAFT_UV_BIN"] = str(paths["uv"])
    environment["WISHICRAFT_GH_BIN"] = str(paths["gh"])

    completed = subprocess.run(
        [str(DEV_ENV), "check"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"required: uv: available: {paths['uv']}: uv 0.test" in completed.stdout
    assert f"required: gh: available: {paths['gh']}: gh version 2.test" in completed.stdout
    assert "optional: docker: CLI unavailable" in completed.stdout
    assert "optional: aws: unavailable" in completed.stdout


@pytest.mark.parametrize(
    ("daemon_exit", "expected"),
    [
        (1, "CLI available, daemon unavailable"),
        (0, "CLI and daemon available"),
    ],
)
def test_check_distinguishes_docker_cli_from_daemon(
    tmp_path: Path, daemon_exit: int, expected: str
) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    for name in ("git", "uv", "gh", "node", "npm", "npx"):
        make_executable(bin_dir, name, f"printf '%s\\n' '{name} test'")
    make_executable(
        bin_dir,
        "docker",
        f"""if [ \"${{1:-}}\" = --version ]; then
  printf '%s\\n' 'Docker version test'
  exit 0
fi
exit {daemon_exit}""",
    )
    environment["WISHICRAFT_UV_BIN"] = str(bin_dir / "uv")
    environment["WISHICRAFT_GH_BIN"] = str(bin_dir / "gh")

    completed = subprocess.run(
        [str(DEV_ENV), "check"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"optional: docker: {expected}" in completed.stdout


def test_run_exports_discovered_uv_and_repository_cache(tmp_path: Path) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    uv = make_executable(bin_dir, "uv", "printf '%s\\n' 'uv test'")
    probe = make_executable(
        bin_dir,
        "probe-environment",
        'command -v uv\nprintf \'%s\\n\' "$UV_CACHE_DIR" "$JSII_RUNTIME_PACKAGE_CACHE_ROOT"',
    )
    environment["WISHICRAFT_UV_BIN"] = str(uv)

    completed = subprocess.run(
        [str(DEV_ENV), "run", "--", str(probe)],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    lines = completed.stdout.splitlines()
    assert lines == [
        str(bin_dir / "uv"),
        str(ROOT / ".uv-cache"),
        str(ROOT / ".jsii-cache"),
    ]


def test_auth_check_uses_read_only_account_and_repository_queries(tmp_path: Path) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    gh = make_executable(
        bin_dir,
        "gh",
        """case \"$1 $2\" in
  'auth status') printf '%s\\n' 'authenticated to github.com' ;;
  'api user') printf '%s\\n' 'eash-misoni' ;;
  'repo view') printf '%s\\n' 'eash-misoni/wishicraft-server' ;;
  *) exit 2 ;;
esac""",
    )
    environment["WISHICRAFT_GH_BIN"] = str(gh)

    completed = subprocess.run(
        [str(DEV_ENV), "auth-check"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "account=eash-misoni repository=eash-misoni/wishicraft-server" in completed.stdout
    assert "token" not in completed.stdout.lower()


def test_gh_setup_uses_official_checksum_and_user_local_roots(tmp_path: Path) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    data_root = tmp_path / "data"
    cache_root = tmp_path / "cache"
    user_bin = tmp_path / "user-bin"
    environment.update(
        {
            "XDG_DATA_HOME": str(data_root),
            "XDG_CACHE_HOME": str(cache_root),
            "XDG_BIN_HOME": str(user_bin),
        }
    )
    expose_system_tools(bin_dir, ("awk", "chmod", "cp", "ln", "mkdir", "mktemp", "readlink", "rm"))
    make_executable(
        bin_dir,
        "uname",
        "[ \"${1:-}\" = -s ] && printf '%s\\n' Darwin || printf '%s\\n' arm64",
    )
    make_executable(
        bin_dir,
        "curl",
        """url=$2
target=$4
case \"$url\" in
  *_checksums.txt) printf '%s  %s\\n' test-checksum gh_2.100.0_macOS_arm64.zip > \"$target\" ;;
  *) : > \"$target\" ;;
esac""",
    )
    make_executable(bin_dir, "shasum", "printf '%s  %s\\n' test-checksum \"$3\"")
    make_executable(
        bin_dir,
        "unzip",
        """destination=$4
mkdir -p \"$destination/gh_2.100.0_macOS_arm64/bin\"
printf '%s\\n' '#!/bin/sh' \"printf '%s\\\\n' 'gh version 2.100.0'\" > \\
  \"$destination/gh_2.100.0_macOS_arm64/bin/gh\"
chmod 0755 \"$destination/gh_2.100.0_macOS_arm64/bin/gh\"""",
    )

    completed = subprocess.run(
        [str(SETUP), "gh"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    installed = data_root / "wishicraft" / "gh" / "2.100.0" / "bin" / "gh"
    assert installed.is_file()
    assert (user_bin / "gh").readlink() == installed
    assert "official release with SHA-256 verification" in completed.stdout


def test_bundling_cache_setup_uses_discovered_uv_and_locked_requirements(tmp_path: Path) -> None:
    environment, bin_dir = isolated_environment(tmp_path)
    expose_system_tools(bin_dir, ("mktemp", "rm"))
    invocation_log = tmp_path / "uv-invocation"
    uv = make_executable(bin_dir, "uv", 'printf \'%s\\n\' "$*" > "$FAKE_UV_LOG"')
    environment["WISHICRAFT_UV_BIN"] = str(uv)
    environment["FAKE_UV_LOG"] = str(invocation_log)

    completed = subprocess.run(
        [str(SETUP), "bundling-cache"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    invocation = invocation_log.read_text(encoding="utf-8")
    assert "pip install" in invocation
    assert "--python-platform x86_64-manylinux2014" in invocation
    assert "--require-hashes" in invocation
    assert "discord-command-requirements.lock" in invocation
    assert "local bundling cache ready" in completed.stdout


def test_scripts_are_executable_and_do_not_embed_machine_specific_paths() -> None:
    for script in (DEV_ENV, SETUP):
        assert os.access(script, os.X_OK)
        contents = script.read_text(encoding="utf-8")
        assert "/Users/" not in contents
        assert "/opt/homebrew" not in contents.lower()
