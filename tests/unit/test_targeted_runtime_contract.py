"""Transport, Dynamo serialization, host authorization and replay boundaries."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from wishicraft.artifacts import targeted_runtime as host
from wishicraft.auto_stop import deterministic_intent_id
from wishicraft.runtime_contract import RuntimeTargetRepository, command, validate_target
from wishicraft.runtime_heartbeat import ProtocolState, RuntimeObservation, derive_heartbeat
from wishicraft.runtime_heartbeat_producer import _decode, _encode

TARGET = {
    "instance_id": "i-0123456789abcdef0",
    "game_id": "game-vanilla-main",
    "data_source": "/srv/minecraft/games/game-vanilla-main/server",
    "config_digest": "a" * 64,
    "run_id": "op-start",
}
NOW = datetime(2026, 9, 11, tzinfo=UTC)


def request(action: str = "START") -> dict[str, Any]:
    transport = command(operation_id="op-current", lease_id="lease-current", action=action)
    return dict(json.loads(base64.b64decode(transport.split()[-1])))


def authority(action: str = "START") -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    operation = {
        "operation_id": "op-current",
        "lease_id": "lease-current",
        "operation_type": action,
        "target_game_id": TARGET["game_id"],
        "status": "RUNNING",
        "timeout_at": (NOW + timedelta(minutes=20)).isoformat(),
        "runtime_target": TARGET,
    }
    lease = {
        "owner_operation_id": "op-current",
        "lease_id": "lease-current",
        "resource_id": "wishicraft-main",
        "lease_expires_at": int(NOW.timestamp()) + 900,
    }
    return operation, lease, {**TARGET, "system_id": "wishicraft-main"}


@pytest.mark.parametrize("action", ["START", "STOP"])
def test_actual_transport_decodes_at_host_and_current_lease_authorizes(action: str) -> None:
    operation, lease, config = authority(action)
    assert host.authorize(request(action), operation, lease, config, NOW) == TARGET
    assert host.authorize(request(action), operation, lease, config, NOW) == TARGET


@pytest.mark.parametrize(
    "field,value",
    [
        ("game_id", "game-other"),
        ("data_source", "/srv/minecraft/games/game-other/server"),
        ("config_digest", "b" * 64),
        ("instance_id", "i-fffffffffffffffff"),
    ],
)
def test_wrong_target_never_authorized(field: str, value: str) -> None:
    operation, lease, config = authority()
    operation["runtime_target"] = {**TARGET, field: value}
    with pytest.raises(ValueError):
        host.authorize(request(), operation, lease, config, NOW)


@pytest.mark.parametrize("mutation", ["lease", "owner", "expired", "terminal", "timeout"])
def test_delayed_old_request_rejected(mutation: str) -> None:
    operation, lease, config = authority()
    if mutation == "lease":
        lease["lease_id"] = "lease-new"
    if mutation == "owner":
        lease["owner_operation_id"] = "op-new"
    if mutation == "expired":
        lease["lease_expires_at"] = int(NOW.timestamp())
    if mutation == "terminal":
        operation["status"] = "SUCCEEDED"
    if mutation == "timeout":
        operation["timeout_at"] = NOW.isoformat()
    with pytest.raises(ValueError, match="STALE_OPERATION"):
        host.authorize(request(), operation, lease, config, NOW)


def test_other_runtime_container_cannot_be_stopped() -> None:
    container = {"Config": {"Labels": {"com.wishicraft.run-id": "op-new"}}, "Mounts": []}
    with pytest.raises(ValueError, match="CONTAINER_TARGET_MISMATCH"):
        host.validate_container(container, TARGET)


class Dynamo:
    def __init__(self) -> None:
        self.item: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    def update_item(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if "runtime_target" not in self.item:
            self.item["runtime_target"] = kwargs["ExpressionAttributeValues"][":target"]
        raise TimeoutError("lost response after commit or conditional conflict")

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ConsistentRead"] is True
        return {"Item": self.item}


def test_conditional_freeze_response_loss_reuses_exact_serialized_target() -> None:
    db = Dynamo()
    repository = RuntimeTargetRepository(db, "operations")
    assert (
        repository.freeze(operation_id="op-current", lease_id="lease-current", target=TARGET)
        == TARGET
    )
    assert (
        repository.freeze(operation_id="op-current", lease_id="lease-current", target=TARGET)
        == TARGET
    )
    assert "attribute_not_exists(runtime_target)" in db.calls[0]["ConditionExpression"]
    with pytest.raises(ValueError, match="conflict"):
        repository.freeze(
            operation_id="op-current",
            lease_id="lease-current",
            target={**TARGET, "run_id": "op-new"},
        )


def test_runtime_restart_same_boot_resets_empty_continuity_and_warning_identity() -> None:
    observation = RuntimeObservation(
        instance_id=TARGET["instance_id"],
        runtime_id="wishicraft-host-runtime",
        boot_id="00000000-0000-0000-0000-000000000000",
        active_game_id=TARGET["game_id"],
        protocol_state=ProtocolState.READY,
        player_count=0,
        observed_at=NOW,
        run_id="op-start",
    )
    previous = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id=TARGET["game_id"],
        observation=observation,
        previous=None,
    )
    current = derive_heartbeat(
        system_id="wishicraft-main",
        canonical_game_id=TARGET["game_id"],
        observation=replace(observation, observed_at=NOW + timedelta(seconds=60), run_id="op-new"),
        previous=_decode(_encode(previous)),
    )
    assert current.empty_since == current.observed_at
    assert _decode(_encode(current)).run_id == "op-new"
    assert deterministic_intent_id(
        game_id=TARGET["game_id"], boot_id=observation.boot_id, empty_since=NOW, run_id="op-start"
    ) != deterministic_intent_id(
        game_id=TARGET["game_id"], boot_id=observation.boot_id, empty_since=NOW, run_id="op-new"
    )


def test_data_path_cannot_escape_or_select_another_game() -> None:
    with pytest.raises(ValueError):
        validate_target({**TARGET, "data_source": "/srv/minecraft/games/../server"})


def test_host_start_loss_resume_stop_loss_and_old_replay(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real host apply/atomic/flock with process+AWS boundary replaced, no real data."""
    import hashlib
    from pathlib import Path

    from wishicraft.config import load_project_config, load_stage_config
    from wishicraft.host_runtime import render_boot_time_artifacts

    root = Path(__file__).resolve().parents[2]
    artifacts = render_boot_time_artifacts(
        load_project_config(root / "config/project.yaml"),
        load_stage_config(root / "config/stages/dev.yaml", "dev"),
        observed_uid=993,
        observed_gid=993,
        enable_rcon=True,
        rcon_parameter_name="/wishicraft/dev/secret/rcon-password",
        targeted=True,
    )
    directory = tmp_path / "artifacts"
    artifacts.write_new(directory)
    assert (
        hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest() == artifacts.digest
    )
    receipt_root = tmp_path / "receipt"
    receipt_root.mkdir()
    config_path = tmp_path / "config.json"
    operation, lease, config = authority()
    target = {**TARGET, "config_digest": artifacts.digest}
    operation["runtime_target"] = target
    operation["timeout_at"] = "2099-01-01T00:00:00Z"
    lease["lease_expires_at"] = 4070908800
    config.update(target)
    config["lock_name"] = "minecraft-control"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(host, "ROOT", receipt_root)
    monkeypatch.setattr(host, "CONFIG", config_path)
    monkeypatch.setattr(host, "ARTIFACTS", directory)
    monkeypatch.setattr(host, "RUN_ENV", tmp_path / "run/runtime-run.env")
    monkeypatch.setattr(host, "actual_instance", lambda: TARGET["instance_id"])
    monkeypatch.setattr(
        host,
        "item",
        lambda c, table, key, identity: operation if table == "operations_table" else lease,
    )
    containers: list[dict[str, Any]] = []
    monkeypatch.setattr(host, "inspect", lambda: containers.copy())
    state: dict[str, Any] = {
        "unit": "inactive",
        "lose_start": True,
        "lose_stop": True,
        "starts": 0,
        "saves": 0,
    }

    def execute(args: list[str], *, timeout: int = 30) -> str:
        del timeout
        if args[:2] == ["systemctl", "show"]:
            return str(state["unit"])
        if args[:2] == ["systemctl", "start"]:
            if not containers:
                state["starts"] += 1
                containers.append(
                    {
                        "Id": "a" * 64,
                        "State": {"Running": True},
                        "Config": {
                            "Image": json.loads(artifacts.manifest_json)["image"],
                            "Env": artifacts.runtime_env.splitlines(),
                            "Labels": {
                                "com.wishicraft.run-id": target["run_id"],
                                "com.wishicraft.active-game-id": target["game_id"],
                                "com.wishicraft.active-game-data-source": target["data_source"],
                            },
                        },
                        "Mounts": [
                            {
                                "Destination": "/data",
                                "Type": "bind",
                                "Source": target["data_source"],
                            }
                        ],
                    }
                )
            state["unit"] = "active"
            if state["lose_start"]:
                state["lose_start"] = False
                raise TimeoutError("started but reply lost")
        if args[:2] == ["docker", "exec"]:
            assert args[2] == "a" * 64
            state["saves"] += 1
        if args[:2] == ["systemctl", "stop"]:
            containers.clear()
            state["unit"] = "inactive"
            if state["lose_stop"]:
                state["lose_stop"] = False
                raise TimeoutError("stopped but reply lost")
        return ""

    monkeypatch.setattr(host, "execute", execute)
    with pytest.raises(TimeoutError):
        host.apply(request())
    assert json.loads((receipt_root / "receipt.json").read_text())["phase"] == "starting"
    host.apply(request())
    host.apply(request())
    assert state["starts"] == 1
    operation["operation_type"] = "STOP"
    with pytest.raises(TimeoutError):
        host.apply(request("STOP"))
    assert json.loads((receipt_root / "receipt.json").read_text())["phase"] == "stopping"
    host.apply(request("STOP"))
    assert state["saves"] == 1
    assert json.loads((receipt_root / "receipt.json").read_text())["phase"] == "stopped"
    lease["owner_operation_id"] = "op-new"
    with pytest.raises(ValueError, match="STALE_OPERATION"):
        host.apply(request("STOP"))


def test_waiting_host_command_rechecks_lease_after_real_flock(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fcntl
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    operation, lease, config = authority()
    config["lock_name"] = "minecraft-control"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(host, "ROOT", tmp_path)
    monkeypatch.setattr(host, "CONFIG", path)
    monkeypatch.setattr(host, "actual_instance", lambda: TARGET["instance_id"])
    monkeypatch.setattr(
        host,
        "item",
        lambda c, table, key, identity: operation if table == "operations_table" else lease,
    )
    with (tmp_path / "lock").open("a") as lock, ThreadPoolExecutor(max_workers=1) as pool:
        fcntl.flock(lock, fcntl.LOCK_EX)
        future = pool.submit(host.apply, request())
        try:
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.05)
            lease["owner_operation_id"] = "op-new"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
        with pytest.raises(ValueError, match="STALE_OPERATION"):
            future.result(timeout=2)


def test_real_probe_parser_carries_target_and_rejects_different_observation() -> None:
    from types import SimpleNamespace

    from tests.probe_fixtures import TARGET_INSTANCE_ID, runtime_running_document
    from wishicraft.probe import parse_host_runtime_probe
    from wishicraft.runtime_contract import assert_observed

    document = runtime_running_document()
    target = {**TARGET, "instance_id": TARGET_INSTANCE_ID}
    document["execution"] = {"target": target, "phase": "running", "process_id": "b" * 64}
    probe = parse_host_runtime_probe(json.dumps(document), expected_instance_id=TARGET_INSTANCE_ID)
    assert probe.execution is not None and probe.execution["target"] == target
    runtime = SimpleNamespace(targets=SimpleNamespace(read=lambda op: target))
    assert_observed(runtime, "op-current", {"observation": {"execution": probe.execution}})
    with pytest.raises(ValueError, match="observation mismatch"):
        assert_observed(
            runtime,
            "op-current",
            {
                "observation": {
                    "execution": {**probe.execution, "target": {**target, "run_id": "op-new"}}
                }
            },
        )


def test_bundle_preserves_world_paths_and_disables_v1_first(tmp_path: Any) -> None:
    from pathlib import Path

    from wishicraft.runtime_migration import prepare

    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "bundle"
    prepare(root, output, TARGET["instance_id"])
    files = json.loads((output / "install.json").read_text())["files"]
    assert files[0]["destination"] == "/usr/local/libexec/wishicraft/operation-v1"
    assert "exit 64" in (output / files[0]["source"]).read_text()
    assert all(not item["destination"].startswith("/srv/minecraft") for item in files)
    assert len({item["destination"] for item in files}) == len(files)
    compile((output / files[-1]["source"]).read_text(), "operation-v2", "exec")
    compile((output / "install.py").read_text(), "install.py", "exec")


def test_stopped_receipt_for_other_run_cannot_authorize_ec2_stop() -> None:
    from types import SimpleNamespace
    from typing import cast

    from wishicraft.stop_workflow_lambda import Runtime, _receipt_stopped

    runtime = cast(Runtime, SimpleNamespace(targets=SimpleNamespace(read=lambda op: TARGET)))
    payload: dict[str, object] = {
        "state": {
            "observation": {
                "execution": {"phase": "stopped", "target": {**TARGET, "run_id": "op-other"}}
            }
        }
    }
    assert not _receipt_stopped(payload, runtime, "op-stop")
    payload = {"state": {"observation": {"execution": {"phase": "stopped", "target": TARGET}}}}
    assert _receipt_stopped(payload, runtime, "op-stop")
