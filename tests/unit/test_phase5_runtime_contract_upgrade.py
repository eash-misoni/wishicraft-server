from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]
HOST_RUNTIME = ROOT / "infrastructure" / "host_runtime"
UPGRADE = HOST_RUNTIME / "phase5_runtime_contract_upgrade.sh"
UNIT = HOST_RUNTIME / "wishicraft-host-runtime.service"


def _constant(name: str) -> str:
    match = re.search(
        rf"^readonly {re.escape(name)}=([^\n]+)$",
        UPGRADE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


def test_fixed_upgrade_embeds_the_canonical_secret_free_compose() -> None:
    configuration = load_configuration(ROOT, "dev")
    rendered = render_boot_time_artifacts(
        configuration.project,
        configuration.stage,
        observed_uid=993,
        observed_gid=993,
    )
    embedded = base64.b64decode(_constant("COMPOSE_TARGET_BASE64")).decode()

    assert embedded == rendered.compose_yaml
    assert hashlib.sha256(embedded.encode()).hexdigest() == _constant("COMPOSE_TARGET_SHA256")
    assert "com.wishicraft.active-game-id: game-vanilla-main" in embedded
    assert (
        "com.wishicraft.active-game-data-source: /srv/minecraft/games/game-vanilla-main/server"
    ) in embedded
    assert not re.search(r"password|secret|token|rcon", embedded, re.IGNORECASE)


def test_fixed_upgrade_embeds_the_canonical_mount_ordering_unit() -> None:
    embedded = base64.b64decode(_constant("UNIT_TARGET_BASE64"))
    canonical = UNIT.read_bytes()

    assert embedded == canonical
    assert hashlib.sha256(embedded).hexdigest() == _constant("UNIT_TARGET_SHA256")
    text = embedded.decode()
    assert "Requires=wishicraft-data-volume.service docker.service" in text
    assert "After=wishicraft-data-volume.service docker.service" in text
    assert "RequiresMountsFor=/srv/minecraft" in text
    assert "ExecStop=/usr/local/lib/wishicraft-host-runtime/stop.sh" in text
    assert "Restart=no" in text
    assert "WantedBy=" not in text
    assert "RequiredBy=" not in text


def test_approved_predecessor_is_atomically_upgraded_and_idempotent(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_text("approved predecessor\n", encoding="utf-8")
    predecessor = hashlib.sha256(artifact.read_bytes()).hexdigest()
    target_bytes = b"canonical target\n"
    target = hashlib.sha256(target_bytes).hexdigest()
    payload = base64.b64encode(target_bytes).decode()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "stat").write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        "  %U:%G) echo root:root ;;\n"
        "  %a) echo 600 ;;\n"
        "  %U:%G:%a) echo root:root:600 ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (bin_dir / "chown").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for stub in (bin_dir / "stat", bin_dir / "chown"):
        stub.chmod(0o755)
    command = (
        f"source '{UPGRADE}'; "
        f"apply_artifact '{artifact}' '{predecessor}' '{target}' '{payload}' 600 root:root"
    )
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    first = subprocess.run(
        ["bash", "-c", command], env=environment, capture_output=True, text=True, check=False
    )
    second = subprocess.run(
        ["bash", "-c", command], env=environment, capture_output=True, text=True, check=False
    )

    assert first.returncode == 0
    assert "PASS:UPGRADED" in first.stdout
    assert second.returncode == 0
    assert "PASS:CURRENT" in second.stdout
    assert artifact.read_bytes() == target_bytes
    assert not list(tmp_path.glob("artifact.phase5-upgrade.*"))


def test_unapproved_predecessor_is_rejected_without_change(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_text("unknown local change\n", encoding="utf-8")
    before = artifact.read_bytes()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "stat").write_text(
        '#!/bin/sh\ncase "$2" in %U:%G) echo root:root;; *) echo 600;; esac\n',
        encoding="utf-8",
    )
    (bin_dir / "stat").chmod(0o755)
    command = (
        f"source '{UPGRADE}'; apply_artifact '{artifact}' "
        f"'{hashlib.sha256(b'approved').hexdigest()}' "
        f"'{hashlib.sha256(b'target').hexdigest()}' "
        f"'{base64.b64encode(b'target').decode()}' 600 root:root"
    )

    result = subprocess.run(
        ["bash", "-c", command],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 73
    assert "FAIL:UNAPPROVED_PREDECESSOR" in result.stderr
    assert artifact.read_bytes() == before


def test_upgrade_cli_rejects_all_arguments_and_has_no_arbitrary_input() -> None:
    result = subprocess.run(
        ["bash", str(UPGRADE), "compose-payload"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 64
    assert result.stderr == "FAIL:ARGUMENTS\n"
