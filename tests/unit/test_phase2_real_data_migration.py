from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infrastructure/migrations/phase2_real_data_migration.sh"


def test_real_data_migration_has_valid_shell_syntax_and_fixed_identity() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    script = SCRIPT.read_text(encoding="utf-8")
    for value in (
        "i-021eaa7f33ddaf0a6",
        "i-04fc0629dc4ea466e",
        "vol-03ac9f534326c345c",
        "ap-northeast-1a",
        "420cea6d-0520-4436-bb5a-db1191f1e63b",
        "/srv/minecraft/games/game-vanilla-main/server",
    ):
        assert value in script
    assert 'readonly PROPERTIES="$SERVER_DIR/server.properties"' in script


def test_real_data_migration_forbids_destructive_filesystem_and_broad_ownership_actions() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "mkfs" not in script
    assert "xfs_repair" not in script
    assert "force detach" not in script
    assert "chown -R" not in script
    assert script.count('chown 993:993 "$PROPERTIES"') == 1
    assert "chmod" not in script
    assert 'cat "$PROPERTIES"' not in script


def test_real_data_migration_mounts_only_expected_existing_xfs_uuid() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "wipefs -n" in script
    assert '[[ "$type" == xfs ]]' in script
    assert '[[ "$uuid" == "$EXPECTED_UUID" ]]' in script
    assert '[[ "$signatures" == xfs ]]' in script
    assert 'mount "$MOUNT_PATH"' in script
    assert "--mount-existing" in script


def test_real_data_migration_properties_contract_is_content_preserving() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "server-properties.before" in script
    assert "sha256sum" in script
    assert "PROPERTIES_PRECONDITION" in script
    assert "PROPERTIES_POSTCONDITION" in script
    assert "no_extended_acl" in script
