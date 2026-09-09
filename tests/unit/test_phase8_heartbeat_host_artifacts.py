import ast
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "infrastructure" / "host_runtime"


def test_timer_is_non_persistent_and_runs_once_per_60_seconds() -> None:
    timer = (HOST / "wishicraft-heartbeat.timer").read_text()
    assert "OnBootSec=15s" in timer
    assert "OnUnitActiveSec=60s" in timer
    assert "Persistent=false" in timer


def test_service_is_bounded_and_has_no_runtime_lifecycle_actions() -> None:
    service = (HOST / "wishicraft-heartbeat.service").read_text()
    assert "Type=oneshot" in service
    assert "TimeoutStartSec=45" in service
    assert "ExecStart=/usr/bin/python3 -m wishicraft.runtime_heartbeat_producer" in service
    assert "ExecStop=" not in service
    assert "Restart=" not in service


def test_installer_is_fixed_fail_closed_and_only_enables_heartbeat_timer() -> None:
    installer = (HOST / "phase8_heartbeat_install.sh").read_text()
    assert "UNAPPROVED_EXISTING_TARGET" in installer
    assert "systemctl enable --now wishicraft-heartbeat.timer" in installer
    assert "systemctl daemon-reload" in installer
    for forbidden in (
        "start wishicraft-host-runtime",
        "stop wishicraft-host-runtime",
        "reboot",
        "shutdown",
    ):
        assert forbidden not in installer
    for path in (
        ROOT / "src" / "wishicraft" / "runtime_heartbeat.py",
        ROOT / "src" / "wishicraft" / "runtime_heartbeat_producer.py",
        ROOT / "src" / "wishicraft" / "artifacts" / "host_runtime_probe.py",
        HOST / "heartbeat.env",
        HOST / "wishicraft-heartbeat.service",
        HOST / "wishicraft-heartbeat.timer",
    ):
        assert hashlib.sha256(path.read_bytes()).hexdigest() in installer


def test_target_python_artifacts_parse_as_python_3_9() -> None:
    for name in ("runtime_heartbeat.py", "runtime_heartbeat_producer.py"):
        source = (ROOT / "src" / "wishicraft" / name).read_text()
        ast.parse(source, filename=name, feature_version=(3, 9))
