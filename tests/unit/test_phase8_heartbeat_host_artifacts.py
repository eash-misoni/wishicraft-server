import ast
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
    # Historical installer must retain its deployed v1 hashes. New artifacts use the
    # targeted-runtime migration bundle, never a rewritten Phase 8 installer.
    for digest in (
        "d92dd704ccc56f821ba5116298a8861bab70ad26d29101cbc23ef423ffd1b0d9",
        "a7e2b141d2f5b4c79fb5f847f633557c4935dc0374da044a16b6dcc3134e9999",
        "0efcf7e493d85495e36c2234c8ebee3b7a35fdba0f855e527ec1a3d51e1bebb2",
    ):
        assert digest in installer


def test_target_python_artifacts_parse_as_python_3_9() -> None:
    for name in ("runtime_heartbeat.py", "runtime_heartbeat_producer.py"):
        source = (ROOT / "src" / "wishicraft" / name).read_text()
        ast.parse(source, filename=name, feature_version=(3, 9))
