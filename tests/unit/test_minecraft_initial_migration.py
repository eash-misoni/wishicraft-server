from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/migrations/minecraft_initial_migration.sh"
GENERATOR = ROOT / "tools/build_minecraft_initial_migration.py"


def test_shell_syntax_and_fixed_contract() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = SCRIPT.read_text(encoding="utf-8")
    for fixed in (
        "game-vanilla-main",
        "26.2",
        "-Xms1G -Xmx3G",
        "25565",
        "25575",
        "NEWISHIN_",
        "e912ab95758e4b7fb32e292eda293104",
        "cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5",
    ):
        assert fixed in source


def test_fail_closed_order_and_no_forbidden_firewall_or_rcon_operation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("checkpoint P00_START") < source.index("checkpoint C00_CHANGE_BEGIN")
    assert source.index("verify_firewall; pass P04_FIREWALL") < source.index("curl --fail")
    assert source.index("systemctl daemon-reload") < source.index(
        "systemctl enable minecraft.service"
    )
    assert source.index("systemctl enable minecraft.service") < source.index(
        "systemctl start minecraft.service"
    )
    assert "nft --file" not in source
    assert "delete table" not in source
    assert "flush ruleset" not in source
    assert "mcrcon" not in source


def test_readonly_rcon_port_is_passed_to_firewall_classifier_without_reassignment() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'env RCON_PORT="$RCON_PORT" "$FIREWALL_SCRIPT" --classify-table' in source
    assert '$(RCON_PORT=$RCON_PORT "$FIREWALL_SCRIPT" --classify-table)' not in source
    rejected = subprocess.run(
        ["bash", "-c", "readonly RCON_PORT=25575; RCON_PORT=$RCON_PORT env"],
        capture_output=True,
        text=True,
        check=False,
    )
    accepted = subprocess.run(
        [
            "bash",
            "-c",
            (
                "readonly RCON_PORT=25575; "
                "env RCON_PORT=$RCON_PORT bash -c '[[ $RCON_PORT == 25575 ]]'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "readonly variable" in rejected.stderr
    assert "RCON_PORT=25575" not in rejected.stdout
    assert accepted.returncode == 0


@pytest.mark.parametrize(
    "fixture",
    (
        "fresh_state",
        "run14_partial",
        "approved_env_predecessor",
        "canonical_noop",
        "artifact_conflict",
        "symlink_conflict",
        "enable_link_conflict",
        "mount_mismatch",
        "java_version_mismatch",
        "jar_hash_mismatch",
        "download_failure",
        "secret_failure",
        "config_metadata_mismatch",
        "firewall_mismatch",
        "race",
        "unit_race",
        "runtime_race",
        "start_failure",
        "ready_timeout",
        "listener_mismatch",
        "management_listener",
        "non_target_unchanged",
        "secret_non_exposure",
        "idempotency",
        "mtime_unchanged",
        "checkpoint_unique",
        "completion_unique",
    ),
)
def test_required_fixture_contract_is_explicit(fixture: str) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    mapping = {
        "fresh_state": "absent",
        "run14_partial": "properties_state",
        "approved_env_predecessor": (
            "973b24da0b4669b07b396ab4f9d5222aa6525427cb4890b55f4f9e110e42d2ec"
        ),
        "canonical_noop": "canonical",
        "artifact_conflict": "JAR_CONFLICT",
        "symlink_conflict": "! -L",
        "enable_link_conflict": "enable_state",
        "mount_mismatch": "MOUNT_VOLUME",
        "java_version_mismatch": "JAVA_VERSION",
        "jar_hash_mismatch": "JAR_VERIFY",
        "download_failure": "JAR_DOWNLOAD",
        "secret_failure": "SECRET_RETRIEVAL",
        "config_metadata_mismatch": "PROPERTIES_POST",
        "firewall_mismatch": "FIREWALL_TABLE",
        "race": "PROPERTIES_RACE",
        "unit_race": "UNIT_RACE",
        "runtime_race": "RUNTIME_RACE",
        "start_failure": "fail START",
        "ready_timeout": "READY_TIMEOUT",
        "listener_mismatch": "MINECRAFT_LISTENER",
        "management_listener": "MANAGEMENT_LISTENER",
        "non_target_unchanged": "verify_firewall",
        "secret_non_exposure": "set +x",
        "idempotency": "canonical",
        "mtime_unchanged": '[[ "${states[unit]}" == canonical ]]',
        "checkpoint_unique": "checkpoint()",
        "completion_unique": "OK:minecraft_initial_game_completed",
    }
    assert mapping[fixture] in source


def test_generator_is_deterministic_and_roundtrips(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for output in (first, second):
        subprocess.run(
            ["python3", str(GENERATOR), "--source", str(SCRIPT), "--output-root", str(output)],
            check=True,
        )
    for name in (
        "minecraft-initial-migration.sh",
        "minecraft-initial-payload.json",
        "minecraft-initial-manifest.json",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    payload = json.loads((first / "minecraft-initial-payload.json").read_text(encoding="utf-8"))
    assert payload["Parameters"]["commands"][0].encode() == SCRIPT.read_bytes()
    assert payload["InstanceIds"] == ["i-021eaa7f33ddaf0a6"]
    assert payload["Parameters"]["executionTimeout"] == ["900"]


def test_one_byte_change_is_detected(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    subprocess.run(
        ["python3", str(GENERATOR), "--source", str(SCRIPT), "--output-root", str(output)],
        check=True,
    )
    payload = json.loads((output / "minecraft-initial-payload.json").read_text(encoding="utf-8"))
    changed = bytearray(SCRIPT.read_bytes())
    changed[-2] ^= 1
    assert payload["Parameters"]["commands"][0].encode() != bytes(changed)
