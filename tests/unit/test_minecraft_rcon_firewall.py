from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/bootstrap/minecraft_rcon_firewall.sh"


def _command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _table() -> dict[str, Any]:
    return {"family": "inet", "name": "wishicraft_rcon", "handle": 1}


def _canonical(*, reverse_matches: bool = False) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for family, address in (("ip", "127.0.0.1"), ("ip6", "::1")):
        matches = [
            {
                "match": {
                    "op": "==",
                    "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                    "right": 25575,
                }
            },
            {
                "match": {
                    "op": "!=",
                    "left": {"payload": {"protocol": family, "field": "daddr"}},
                    "right": address,
                }
            },
        ]
        if reverse_matches:
            matches.reverse()
        rules.append(
            {
                "rule": {
                    "family": "inet",
                    "table": "wishicraft_rcon",
                    "chain": "input",
                    "handle": len(rules) + 3,
                    "expr": [*matches, {"drop": None}],
                }
            }
        )
    return {
        "nftables": [
            {"metainfo": {"json_schema_version": 1}},
            {"table": _table()},
            {
                "chain": {
                    "family": "inet",
                    "table": "wishicraft_rcon",
                    "name": "input",
                    "handle": 2,
                    "type": "filter",
                    "hook": "input",
                    "prio": 0,
                    "policy": "accept",
                }
            },
            *rules,
        ]
    }


def _empty(**extra: object) -> dict[str, Any]:
    table = _table() | extra
    return {"nftables": [{"metainfo": {"json_schema_version": 1}}, {"table": table}]}


def _write_state(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")


def _environment(tmp_path: Path, *, nft_available: bool = True) -> tuple[dict[str, str], Path]:
    commands = tmp_path / "commands"
    commands.mkdir()
    for name in (
        "bash",
        "cat",
        "cmp",
        "cp",
        "cut",
        "dirname",
        "grep",
        "mktemp",
        "mv",
        "rm",
    ):
        executable = shutil.which(name)
        assert executable
        (commands / name).symlink_to(executable)
    (commands / "python3").symlink_to(sys.executable)

    rules = tmp_path / "etc/nftables/wishicraft-rcon.nft"
    rules.parent.mkdir(parents=True, mode=0o700)
    rules.parent.chmod(0o700)
    state = tmp_path / "nft-state.json"
    log = tmp_path / "nft-log"
    count = tmp_path / "nft-json-count"
    canonical = tmp_path / "canonical.json"
    empty = tmp_path / "empty.json"
    race = tmp_path / "race.json"
    _write_state(canonical, _canonical())
    _write_state(empty, _empty())
    _write_state(race, {"nftables": [{"table": _table()}, {"set": {"name": "race"}}]})
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
  "--version") printf '%s\n' 'nftables v1.0.4';;
  "list tables") [[ ! -f "$NFT_STATE" ]] || printf '%s\n' 'table inet wishicraft_rcon';;
  "-j list table inet wishicraft_rcon")
    n=0; [[ ! -f "$NFT_JSON_COUNT" ]] || n=$(cat "$NFT_JSON_COUNT")
    n=$((n+1)); printf '%s' "$n" > "$NFT_JSON_COUNT"
    if [[ ${NFT_RACE_KIND:-none} != none && $n -ge ${NFT_RACE_AT:-2} ]]; then
      cp "$NFT_RACE_JSON" "$NFT_STATE"
    fi
    [[ -f "$NFT_STATE" ]] || exit 1
    cat "$NFT_STATE"
    ;;
  "--check --file "*) [[ ${NFT_CHECK_EXIT:-0} == 0 ]] || exit "$NFT_CHECK_EXIT";;
  "--file "*)
    [[ ${NFT_APPLY_EXIT:-0} == 0 ]] || exit "$NFT_APPLY_EXIT"
    batch=$2
    if grep -qx 'create table inet wishicraft_rcon' "$batch"; then
      [[ ! -f "$NFT_STATE" ]] || exit 1
    elif grep -q '^create chain inet wishicraft_rcon input ' "$batch"; then
      cmp -s "$NFT_STATE" "$NFT_EMPTY_JSON" || exit 1
    else
      exit 2
    fi
    cp "$NFT_CANONICAL_JSON" "$NFT_STATE"
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
        "NFT_JSON_COUNT": str(count),
        "NFT_CANONICAL_JSON": str(canonical),
        "NFT_EMPTY_JSON": str(empty),
        "NFT_RACE_JSON": str(race),
        "DNF_LOG": str(tmp_path / "dnf-log"),
        "RCON_PORT": "25575",
        "WISHICRAFT_RCON_NFT_RULES_PATH": str(rules),
    }
    return env, rules


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], text=True, capture_output=True, env=env, check=False
    )


def test_shell_syntax_and_nftables_104_contract() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "create table inet wishicraft_rcon\nadd chain" in source
    assert "create chain inet wishicraft_rcon input" in source
    assert "destroy table" not in source
    assert "delete table" not in source
    assert "flush ruleset" not in source
    assert "flush table" not in source


def test_absent_state_uses_four_command_batch_then_is_noop(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    first = _run(env)
    before = rules.stat().st_mtime_ns
    second = _run(env)
    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    assert rules.stat().st_mtime_ns == before
    assert rules.read_text().splitlines() == [
        "create table inet wishicraft_rcon",
        (
            "add chain inet wishicraft_rcon input "
            "{ type filter hook input priority 0; policy accept; }"
        ),
        "add rule inet wishicraft_rcon input tcp dport 25575 ip daddr != 127.0.0.1 drop",
        "add rule inet wishicraft_rcon input tcp dport 25575 ip6 daddr != ::1 drop",
    ]
    assert Path(env["NFT_LOG"]).read_text().count("--file") == 2


def test_boot_restore_reuses_canonical_rules(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    assert _run(env).returncode == 0
    Path(env["NFT_STATE"]).unlink()
    Path(env["NFT_JSON_COUNT"]).unlink()
    before = rules.stat().st_mtime_ns
    assert _run(env).returncode == 0
    assert rules.stat().st_mtime_ns == before


def test_canonical_table_without_rules_only_finalizes_file(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _canonical(reverse_matches=True))
    before = Path(env["NFT_STATE"]).read_bytes()
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert rules.is_file()
    assert Path(env["NFT_STATE"]).read_bytes() == before


def test_approved_empty_v15_recovery_uses_three_command_batch(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _empty())
    result = _run(env, "--recover-empty-v15")
    assert result.returncode == 0, result.stderr
    assert rules.is_file()
    log = Path(env["NFT_LOG"]).read_text()
    assert rules.read_text().startswith("create table inet wishicraft_rcon\n")
    assert log.count("--file") == 2
    assert "WCRF:STEP:RECOVERY_APPLY" in result.stderr


def test_empty_table_is_not_generally_accepted(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _empty())
    result = _run(env)
    assert result.returncode == 54
    assert "WCRF:FAIL:EMPTY_TABLE_UNAPPROVED" in result.stderr
    assert not rules.exists()


@pytest.mark.parametrize("extra", ({"comment": "x"}, {"flags": ["owner"]}))
def test_empty_table_with_metadata_is_conflict(tmp_path: Path, extra: dict[str, object]) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _empty(**extra))
    result = _run(env, "--recover-empty-v15")
    assert result.returncode == 44
    assert "WCRF:FAIL:UNEXPECTED_OBJECT" in result.stderr
    assert not rules.exists()


@pytest.mark.parametrize("kind", ("set", "map", "flowtable", "counter", "unknown"))
def test_empty_table_with_other_object_is_conflict(tmp_path: Path, kind: str) -> None:
    env, rules = _environment(tmp_path)
    value = _empty()
    value["nftables"].append({kind: {"family": "inet", "table": "wishicraft_rcon", "name": "x"}})
    _write_state(Path(env["NFT_STATE"]), value)
    result = _run(env, "--recover-empty-v15")
    assert result.returncode == 44
    assert not rules.exists()


@pytest.mark.parametrize("race_kind", ("chain", "unknown"))
def test_recovery_race_stops_before_apply(tmp_path: Path, race_kind: str) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _empty())
    env["NFT_RACE_KIND"] = race_kind
    before_apply = _run(env, "--recover-empty-v15")
    assert before_apply.returncode == 61
    assert "WCRF:FAIL:RECOVERY_RACE" in before_apply.stderr
    assert not rules.exists()
    assert not any(
        line.startswith("--file ") for line in Path(env["NFT_LOG"]).read_text().splitlines()
    )


@pytest.mark.parametrize(
    ("setting", "marker"),
    (("NFT_CHECK_EXIT", "NFT_CHECK"), ("NFT_APPLY_EXIT", "NFT_APPLY")),
)
def test_initial_transaction_failure_is_atomic(tmp_path: Path, setting: str, marker: str) -> None:
    env, rules = _environment(tmp_path)
    env[setting] = "1"
    result = _run(env)
    assert result.returncode != 0
    assert f"WCRF:FAIL:{marker}" in result.stderr
    assert not Path(env["NFT_STATE"]).exists()
    assert not rules.exists()


def test_expression_order_is_semantic(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    _write_state(Path(env["NFT_STATE"]), _canonical(reverse_matches=True))
    assert _run(env).returncode == 0
    assert rules.exists()


@pytest.mark.parametrize(
    ("mutation", "marker", "status"),
    (
        (("op", "=="), "ADDRESS_PREDICATE", 50),
        (("address", "127.0.0.2"), "ADDRESS_PREDICATE", 50),
        (("port", 25576), "PORT_PREDICATE", 49),
        (("verdict", "accept"), "VERDICT", 51),
        (("extra", True), "UNEXPECTED_EXPRESSION", 53),
    ),
)
def test_semantic_conflicts(
    tmp_path: Path, mutation: tuple[str, object], marker: str, status: int
) -> None:
    env, rules = _environment(tmp_path)
    value = _canonical()
    expr = value["nftables"][3]["rule"]["expr"]
    key, changed = mutation
    if key == "op":
        expr[1]["match"]["op"] = changed
    elif key == "address":
        expr[1]["match"]["right"] = changed
    elif key == "port":
        expr[0]["match"]["right"] = changed
    elif key == "verdict":
        expr[-1] = {str(changed): None}
    else:
        expr.insert(2, {"counter": {"packets": 0, "bytes": 0}})
    _write_state(Path(env["NFT_STATE"]), value)
    result = _run(env)
    assert result.returncode == status
    assert f"WCRF:FAIL:{marker}" in result.stderr
    assert not rules.exists()


def test_duplicate_rule_is_rejected(tmp_path: Path) -> None:
    env, _ = _environment(tmp_path)
    value = _canonical()
    value["nftables"].append(value["nftables"][3])
    _write_state(Path(env["NFT_STATE"]), value)
    result = _run(env)
    assert result.returncode == 52
    assert "WCRF:FAIL:DUPLICATE" in result.stderr


def test_json_query_and_parse_failures_are_distinct(tmp_path: Path) -> None:
    env, _ = _environment(tmp_path)
    Path(env["NFT_STATE"]).write_text("not-json\n")
    parsed = _run(env)
    assert parsed.returncode == 42
    assert "WCRF:FAIL:JSON_PARSE" in parsed.stderr


def test_python_absence_stops_before_nft_or_filesystem_change(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    Path(env["COMMANDS"], "python3").unlink()
    result = _run(env)
    assert result.returncode == 21
    assert "WCRF:FAIL:PYTHON_LOOKUP" in result.stderr
    assert not rules.exists()
    assert not Path(env["NFT_LOG"]).exists()


def test_stale_temporary_file_stops_before_apply(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    stale = rules.with_name(rules.name + ".stale")
    stale.write_text("unknown provenance", encoding="utf-8")
    result = _run(env)
    assert result.returncode == 30
    assert stale.read_text() == "unknown provenance"
    assert not Path(env["NFT_STATE"]).exists()


def test_package_is_installed_only_when_nft_is_missing(tmp_path: Path) -> None:
    env, _ = _environment(tmp_path, nft_available=False)
    assert _run(env).returncode == 0
    assert Path(env["DNF_LOG"]).read_text().splitlines() == ["install -y nftables"]


def test_conflicting_live_table_is_not_changed(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    value = _canonical()
    value["nftables"][1]["table"]["name"] = "other"
    _write_state(Path(env["NFT_STATE"]), value)
    before = Path(env["NFT_STATE"]).read_bytes()
    result = _run(env)
    assert result.returncode == 43
    assert Path(env["NFT_STATE"]).read_bytes() == before
    assert not rules.exists()


def test_rules_conflict_is_not_replaced(tmp_path: Path) -> None:
    env, rules = _environment(tmp_path)
    rules.write_text("conflict\n", encoding="utf-8")
    before = rules.read_bytes()
    result = _run(env)
    assert result.returncode == 35
    assert rules.read_bytes() == before
