from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "infrastructure" / "bootstrap" / "minecraft_rcon_firewall.sh"


def _write_command(path: Path, name: str, body: str) -> None:
    command = path / name
    command.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    command.chmod(0o755)


def _nft_body() -> str:
    return (
        'printf "%s\\n" "$*" >> "$NFT_LOG"\n'
        'if [[ "$1" == "--check" ]]; then\n'
        '  [[ "${NFT_CHECK_EXIT:-0}" == 0 ]] || exit "$NFT_CHECK_EXIT"\n'
        '  cat "$3" > "$NFT_RULES"\n'
        'elif [[ "$1" == "--file" ]]; then\n'
        '  [[ "${NFT_APPLY_EXIT:-0}" == 0 ]] || exit "$NFT_APPLY_EXIT"\n'
        '  cat "$2" > "$NFT_RULES"\n'
        'elif [[ "$1" == "list" && "$2" == "table" ]]; then\n'
        '  exit "${NFT_LIST_EXIT:-0}"\n'
        "else\n"
        "  exit 1\n"
        "fi"
    )


def _firewall_environment(
    tmp_path: Path, *, nft_available: bool = True, dnf_exit: int = 0
) -> tuple[dict[str, str], Path]:
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    if nft_available:
        _write_command(stubs, "nft", _nft_body())
    _write_command(
        stubs,
        "dnf",
        'printf "%s\\n" "$*" >> "$DNF_LOG"\n'
        f'[[ "{dnf_exit}" == 0 ]] || exit {dnf_exit}\n'
        "cat > \"$STUB_DIRECTORY/nft\" <<'NFT'\n"
        "#!/usr/bin/env bash\n"
        "set -eu\n" + _nft_body() + '\nNFT\n/bin/chmod 0755 "$STUB_DIRECTORY/nft"',
    )
    _write_command(stubs, "chown", ":")
    _write_command(stubs, "chmod", ":")
    _write_command(stubs, "stat", "printf 'root:root:600'")
    _write_command(
        stubs,
        "install",
        'for argument in "$@"; do\n  [[ "$argument" == /* ]] && mkdir -p "$argument"\ndone',
    )
    rules_path = tmp_path / "nftables" / "wishicraft-rcon.nft"
    environment = {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "STUB_DIRECTORY": str(stubs),
        "DNF_LOG": str(tmp_path / "dnf-log"),
        "NFT_LOG": str(tmp_path / "nft-log"),
        "NFT_RULES": str(tmp_path / "nft-rules"),
        "RCON_PORT": "25575",
        "WISHICRAFT_RCON_NFT_RULES_PATH": str(rules_path),
    }
    return environment, rules_path


def test_rcon_firewall_script_has_valid_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_rcon_firewall_installs_nftables_when_missing_and_applies_loopback_only_rules(
    tmp_path: Path,
) -> None:
    environment, rules_path = _firewall_environment(tmp_path, nft_available=False)

    first = subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )
    second = subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "dnf-log").read_text(encoding="utf-8").splitlines() == [
        "install -y nftables"
    ]
    rules = rules_path.read_text(encoding="utf-8")
    assert "destroy table inet wishicraft_rcon" in rules
    assert "table inet wishicraft_rcon" in rules
    assert "tcp dport 25575 ip daddr != 127.0.0.1 drop" in rules
    assert "tcp dport 25575 ip6 daddr != ::1 drop" in rules
    assert "25565" not in rules
    assert "flush ruleset" not in rules
    assert (tmp_path / "nft-log").read_text(encoding="utf-8").count("--check --file") == 2
    assert not list(rules_path.parent.glob("wishicraft-rcon.nft.*"))


@pytest.mark.parametrize(
    ("nft_available", "dnf_exit", "check_exit", "apply_exit"),
    (
        (False, 1, 0, 0),
        (True, 0, 1, 0),
        (True, 0, 0, 1),
    ),
)
def test_rcon_firewall_fails_closed_without_persisting_rules(
    tmp_path: Path, nft_available: bool, dnf_exit: int, check_exit: int, apply_exit: int
) -> None:
    environment, rules_path = _firewall_environment(
        tmp_path, nft_available=nft_available, dnf_exit=dnf_exit
    )
    environment["NFT_CHECK_EXIT"] = str(check_exit)
    environment["NFT_APPLY_EXIT"] = str(apply_exit)

    result = subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, env=environment, check=False
    )

    assert result.returncode != 0
    assert not rules_path.exists()
    assert not list(rules_path.parent.glob("wishicraft-rcon.nft.*"))
