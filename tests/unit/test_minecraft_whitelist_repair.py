from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/migrations/minecraft_whitelist_repair.sh"
GENERATOR = ROOT / "tools/build_minecraft_whitelist_repair.py"


def test_repair_is_fail_closed_and_uses_known_predecessors() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    source = SCRIPT.read_text(encoding="utf-8")
    for value in (
        "WHITELIST_PREDECESSOR_BYTES=65",
        "947d6fe39bce595925e5faf1f2fc677fb1edaba95398e07f4c459e7a08ecc279",
        "ENV_PREDECESSOR_BYTES=856",
        "e7e77a6dfc55e7aa697efab7ec6305b58d3e38be92a42175112e29fa549299ac",
        "GAME_SETUP_PREDECESSOR_BYTES=3349",
        "6d42df504412818f807046afa0c2caa082d3d636d71f035a53de90d4cdab2e9b",
        "e912ab95-758e-4b7f-b32e-292eda293104",
    ):
        assert value in source
    assert source.index('checkpoint "STATE:runtime=$RUNTIME_STATE"') < source.index(
        "checkpoint C00_CHANGE_BEGIN"
    )
    assert source.index("systemctl stop minecraft.service") < source.index(
        'atomic_content "$WHITELIST"'
    )
    assert source.index('atomic_content "$WHITELIST"') < source.index(
        "systemctl start minecraft.service"
    )
    assert "systemctl kill" not in source
    assert "rm -rf" not in source
    assert "rcon-cli" not in source
    assert "aws ssm get-parameter" not in source
    assert "upgrade_state" in source
    assert '[[ "$GAME_SETUP_STATE" == canonical ]] || atomic_game_setup' in source
    assert '[[ "$ENV_STATE" == canonical ]] || atomic_content' in source
    assert '[[ "$WHITELIST_STATE" == canonical ]] || atomic_content' in source
    assert "RUNTIME_STATE=stopped_partial" in source
    assert "verify_stopped" in source


def test_repair_generator_is_deterministic_and_roundtrips(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for output in (first, second):
        subprocess.run(
            ["python3", str(GENERATOR), "--source", str(SCRIPT), "--output-root", str(output)],
            check=True,
        )
    for name in (
        "minecraft-whitelist-repair.sh",
        "minecraft-whitelist-repair-payload.json",
        "minecraft-whitelist-repair-manifest.json",
    ):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    payload = json.loads(
        (first / "minecraft-whitelist-repair-payload.json").read_text(encoding="utf-8")
    )
    assert payload["Parameters"]["commands"][0].encode() == SCRIPT.read_bytes()
    assert payload["InstanceIds"] == ["i-021eaa7f33ddaf0a6"]
    assert payload["Parameters"]["executionTimeout"] == ["600"]


def test_repair_one_byte_change_is_detected(tmp_path: Path) -> None:
    output = tmp_path / "candidate"
    subprocess.run(
        ["python3", str(GENERATOR), "--source", str(SCRIPT), "--output-root", str(output)],
        check=True,
    )
    payload = json.loads(
        (output / "minecraft-whitelist-repair-payload.json").read_text(encoding="utf-8")
    )
    changed = bytearray(SCRIPT.read_bytes())
    changed[-2] ^= 1
    assert payload["Parameters"]["commands"][0].encode() != bytes(changed)
