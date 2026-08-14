from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/bootstrap/minecraft_rcon_firewall.sh"


def _command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _environment(tmp_path: Path, *, nft_available: bool = True) -> tuple[dict[str, str], Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    for name in ("bash", "cat", "cmp", "cp", "dirname", "grep", "mktemp", "mv", "rm"):
        executable = shutil.which(name)
        assert executable
        (commands / name).symlink_to(executable)

    rules = tmp_path / "etc/nftables/wishicraft-rcon.nft"
    rules.parent.mkdir(parents=True, mode=0o700)
    rules.parent.chmod(0o700)
    state = tmp_path / "nft-state"
    log = tmp_path / "nft-log"
    _command(
        commands,
        "stat",
        "if [[ $1 == -c && $2 == %U:%G:%a ]]; then "
        "case $3 in */nftables) printf root:root:700;; *) printf root:root:600;; esac; "
        "else exit 2; fi",
    )
    _command(commands, "chown", ":")
    _command(commands, "chmod", ":")
    _command(commands, "install", 'mkdir -p "${@: -1}"; chmod 0700 "${@: -1}"')
    nft_body = r"""
printf '%s\n' "$*" >> "$NFT_LOG"
case "$*" in
  "list table inet wishicraft_rcon")
    count=0; [[ ! -f "$NFT_LIST_COUNT" ]] || count=$(cat "$NFT_LIST_COUNT")
    count=$((count+1)); printf '%s' "$count" > "$NFT_LIST_COUNT"
    if [[ ${NFT_RACE:-0} == 1 && $count -ge 2 ]]; then printf race-table > "$NFT_STATE"; exit 0; fi
    [[ -f "$NFT_STATE" ]] || exit 1
    cat "$NFT_STATE"
    ;;
  "--check --file "*)
    grep -q '^destroy ' "$3" && exit 1
    [[ ${NFT_CHECK_EXIT:-0} == 0 ]] || exit "$NFT_CHECK_EXIT"
    ;;
  "--file "*)
    [[ ${NFT_APPLY_EXIT:-0} == 0 ]] || exit "$NFT_APPLY_EXIT"
    cat > "$NFT_STATE" <<EOF
table inet wishicraft_rcon {
 chain input {
  type filter hook input priority filter; policy accept;
  tcp dport 25575 ip daddr != 127.0.0.1 drop
  tcp dport 25575 ip6 daddr != ::1 drop
 }
}
EOF
    ;;
  *) exit 2;;
esac"""
    if nft_available:
        _command(commands, "nft", nft_body)
    _command(
        commands,
        "dnf",
        'printf "%s\\n" "$*" >> "$DNF_LOG"; '
        '[[ ${DNF_EXIT:-0} == 0 ]] || exit "$DNF_EXIT"; '
        'cp "$NFT_TEMPLATE" "$COMMANDS/nft"; chmod 0755 "$COMMANDS/nft"',
    )
    template = tmp_path / "nft-template"
    template.write_text(f"#!/usr/bin/env bash\nset -eu\n{nft_body}\n", encoding="utf-8")
    template.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(commands),
        "COMMANDS": str(commands),
        "NFT_TEMPLATE": str(template),
        "NFT_STATE": str(state),
        "NFT_LOG": str(log),
        "NFT_LIST_COUNT": str(tmp_path / "nft-list-count"),
        "DNF_LOG": str(tmp_path / "dnf-log"),
        "RCON_PORT": "25575",
        "WISHICRAFT_RCON_NFT_RULES_PATH": str(rules),
    }
    return env, rules


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], text=True, capture_output=True, env=env, check=False
    )


def test_shell_syntax_and_nftables_104_contract() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "create table inet wishicraft_rcon" in source
    assert "destroy table" not in source
    assert not any(line.lstrip().startswith("flush ruleset") for line in source.splitlines())
    assert "delete table" not in source


def test_absent_state_applies_once_then_is_noop(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    first = _run(env)
    before = rules.stat().st_mtime_ns
    second = _run(env)
    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    assert "WCRF:COMPLETE" in first.stderr
    assert rules.stat().st_mtime_ns == before
    assert rules.read_text().startswith("create table inet wishicraft_rcon")
    log = Path(env["NFT_LOG"]).read_text()
    assert log.count("--file") == 2  # one check and one apply; second run applies neither


def test_boot_restore_reuses_canonical_rules(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    assert _run(env).returncode == 0
    Path(env["NFT_STATE"]).unlink()
    before = rules.stat().st_mtime_ns
    assert _run(env).returncode == 0
    assert rules.stat().st_mtime_ns == before


def test_canonical_table_without_rules_only_finalizes_file(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    assert _run(env).returncode == 0
    rules.unlink()
    before_state = Path(env["NFT_STATE"]).read_bytes()
    assert _run(env).returncode == 0
    assert rules.is_file()
    assert Path(env["NFT_STATE"]).read_bytes() == before_state


@pytest.mark.parametrize(
    ("setting", "value", "marker"),
    (
        ("NFT_CHECK_EXIT", "1", "NFT_CHECK"),
        ("NFT_APPLY_EXIT", "1", "NFT_APPLY"),
        ("NFT_RACE", "1", "TABLE_RACE"),
    ),
)
def test_nft_failure_is_fail_closed(tmp_path: Path, setting: str, value: str, marker: str) -> None:
    env, rules = _environment(tmp_path)
    env[setting] = value
    result = _run(env)
    assert result.returncode != 0
    assert f"WCRF:FAIL:{marker}" in result.stderr
    assert not rules.exists()


def test_stale_temporary_file_stops_before_apply(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    stale = rules.with_name(rules.name + ".stale")
    stale.write_text("unknown provenance", encoding="utf-8")
    result = _run(env)
    assert result.returncode != 0
    assert "WCRF:FAIL:TEMP_CONFLICT" in result.stderr
    assert not Path(env["NFT_STATE"]).exists()
    assert stale.read_text() == "unknown provenance"


def test_package_is_installed_only_when_nft_is_missing(tmp_path: Path) -> None:
    env, _ = _environment(tmp_path, nft_available=False)
    assert _run(env).returncode == 0
    assert Path(env["DNF_LOG"]).read_text().splitlines() == ["install -y nftables"]


def test_conflicting_live_table_is_not_changed(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    state = Path(env["NFT_STATE"])
    state.write_text("table inet wishicraft_rcon { chain other {} }\n", encoding="utf-8")
    before = state.read_bytes()
    result = _run(env)
    assert result.returncode != 0
    assert "WCRF:FAIL:TABLE_CONFLICT" in result.stderr
    assert state.read_bytes() == before
    assert not rules.exists()


def test_rules_conflict_is_not_replaced(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    rules.write_text("conflict\n", encoding="utf-8")
    before = rules.read_bytes()
    result = _run(env)
    assert result.returncode != 0
    assert "WCRF:FAIL:RULES_CONFLICT" in result.stderr
    assert rules.read_bytes() == before
