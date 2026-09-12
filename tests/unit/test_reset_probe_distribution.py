"""Actual migration files -> installed probe -> unchanged heartbeat producer; no AWS."""

import base64
import builtins
import hashlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from wishicraft.reset_migration import prepare

ROOT = Path(__file__).resolve().parents[2]
PROBE = "/usr/local/libexec/wishicraft/host-runtime-probe.py"


def test_reset_bundle_distributes_heartbeat_probe(tmp_path: Path) -> None:
    result = prepare(ROOT, tmp_path / "bundle", "{}")
    from wishicraft.ssm_probe import _canonical_probe_command

    entry = next(e for e in result["plan"]["files"] if e["destination"] == PROBE)
    permanent = (tmp_path / "bundle" / entry["source"]).read_bytes()
    assert permanent == base64.b64decode(shlex.split(_canonical_probe_command())[2])
    assert entry["mode"] == 0o755


BASE = "1267ed5912e027ca2e0b1e1a419df62865f6bfcd"
NOW = datetime(2026, 9, 12, tzinfo=UTC)
TEMP_BOOT = "12345678-1234-1234-1234-123456789abc"


def history(path: str) -> bytes:
    return subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)


def load(path: Path, name: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class Installed:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp, self.bundle = tmp, tmp / "bundle"
        self.result = prepare(ROOT, self.bundle, "{}")
        self.plan = self.result["plan"]
        self.paths: dict[str, Path] = {}
        self.bad_owner: Path | None = None
        for entry in self.plan["files"]:
            destination = entry["destination"]
            target = tmp / "host" / destination.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            self.paths[destination] = target
            if entry["predecessor"] is not None:
                if destination.endswith("operation-v2"):
                    old = b"#!/usr/bin/env python3\n" + history(
                        "src/wishicraft/artifacts/targeted_runtime.py"
                    )
                elif destination.endswith("rcon-secret-v2"):
                    old = history("infrastructure/host_runtime/rcon-secret-v2.sh")
                elif destination == PROBE:
                    old = history("src/wishicraft/artifacts/host_runtime_probe.py")
                else:
                    old = (self.bundle / entry["source"]).read_bytes()
                    if destination.endswith("manifest.json"):
                        manifest = json.loads(old)
                        manifest.pop("reset_policies")
                        old = (
                            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
                        ).encode()
                    elif destination.endswith("runtime-contract.json"):
                        config = json.loads(old)
                        config.pop("reset_policies")
                        config["config_digest"] = self.plan["receipt_predecessor"]["target"][
                            "config_digest"
                        ]
                        old = json.dumps(config, sort_keys=True).encode()
                assert hashlib.sha256(old).hexdigest() == entry["predecessor"]
                target.write_bytes(old)
                target.chmod(entry["mode"])
            entry["destination"] = str(target)
        (self.bundle / "install.json").write_text(json.dumps(self.plan))
        self.installer = load(self.bundle / "install.py", "fixture_installer", monkeypatch)
        self.installer.BUNDLE = self.bundle
        self.installer.RECEIPTS = tmp / "receipts"
        self.installer.RECEIPTS.mkdir(mode=0o700)
        receipt = self.installer.RECEIPTS / "receipt.json"
        receipt.write_text(json.dumps(self.plan["receipt_predecessor"]))
        receipt.chmod(0o600)
        monkeypatch.setattr(self.installer.os, "geteuid", lambda: 0)
        actual_stat = Path.stat

        def root_stat(path: Path, **kwargs: Any) -> os.stat_result:
            original = actual_stat(path, **kwargs)
            if path.is_relative_to(tmp):
                values = list(original)
                # Only root ownership is emulated on developer Mac; actual mode/type/bytes remain.
                values[4], values[5] = (1 if path == self.bad_owner else 0), 0
                return os.stat_result(values)
            return original

        monkeypatch.setattr(Path, "stat", root_stat)
        monkeypatch.setattr(
            self.installer, "run", lambda args: "inactive" if "show" in args else ""
        )
        monkeypatch.setattr(
            self.installer.urllib.request,
            "urlopen",
            lambda request, **kwargs: io.BytesIO(
                self.plan["instance_id"].encode()
                if request.full_url.endswith("instance-id")
                else b"test-token"
            ),
        )
        for filename in ("runtime_heartbeat.py", "runtime_heartbeat_producer.py"):
            path = self.paths[PROBE].parent / filename
            path.write_bytes(history("src/wishicraft/" + filename))
            assert path.read_bytes() == (ROOT / "src/wishicraft" / filename).read_bytes()
        self.heartbeat = load(
            self.paths[PROBE].parent / "runtime_heartbeat.py",
            "wishicraft.runtime_heartbeat",
            monkeypatch,
        )
        self.producer = load(
            self.paths[PROBE].parent / "runtime_heartbeat_producer.py",
            "fixture_producer",
            monkeypatch,
        )
        self.producer.PROBE_PATH = str(self.paths[PROBE])
        boot = tmp / "boot-id"
        boot.write_text(TEMP_BOOT)
        self.producer.BOOT_ID_PATH = boot

    def install(self) -> None:
        self.installer.main()

    def heartbeat_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        game: str,
        source: str,
        run: str = "op-new",
        previous: Any = None,
        now: datetime = NOW,
        count: int | None = 0,
        actual_source: str | None = None,
    ) -> tuple[dict[str, Any], Any]:
        probe = load(Path(self.producer.PROBE_PATH), "fixture_probe", monkeypatch)
        manifest = self.paths["/etc/wishicraft/host-runtime/manifest.json"].read_bytes()
        target = {
            "game_id": game,
            "instance_id": self.plan["instance_id"],
            "data_source": source,
            "run_id": run,
            "config_digest": hashlib.sha256(manifest).hexdigest(),
        }
        document: dict[str, Any] = {
            "Id": "container-" + run,
            "Name": "/minecraft",
            "RestartCount": 0,
            "Config": {
                "Image": json.loads(manifest)["image"],
                "Labels": {
                    "com.wishicraft.active-game-id": game,
                    "com.wishicraft.active-game-data-source": source,
                    "com.wishicraft.run-id": run,
                },
            },
            "Mounts": [{"Type": "bind", "Destination": "/data", "Source": actual_source or source}],
            "State": {
                "Status": "running",
                "Running": True,
                "StartedAt": now.isoformat(),
                "OOMKilled": False,
            },
            "HostConfig": {"RestartPolicy": {"Name": "no"}},
            "NetworkSettings": {},
        }
        # Same process on successive observation: StartedAt must remain fixed.
        document["State"]["StartedAt"] = "2026-09-12T00:00:00Z"
        monkeypatch.setattr(
            probe,
            "run",
            lambda *args: subprocess.CompletedProcess(
                args,
                0,
                json.dumps([document])
                if args[:2] == ("docker", "inspect")
                else document["Id"] + "\n",
            ),
        )
        original_open = builtins.open

        def fixture_open(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path) == "/var/lib/wishicraft/runtime/receipt.json":
                return io.StringIO(json.dumps({"phase": "running", "target": target}))
            if str(path) == "/etc/wishicraft/host-runtime/manifest.json":
                return io.BytesIO(manifest)
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(probe, "open", fixture_open, raising=False)
        monkeypatch.setattr(probe, "instance_id", lambda: (target["instance_id"], None))
        monkeypatch.setattr(probe, "observe_mount", lambda: ({}, None))
        monkeypatch.setattr(probe, "observe_unit", lambda unit: ("active", None))
        monkeypatch.setattr(probe, "observe_telemetry", lambda: {})
        monkeypatch.setattr(
            probe,
            "observe_protocol",
            lambda container: (
                {"player_count": count},
                "ready" if count is not None else "unknown",
                count is not None,
            ),
        )

        def run_probe(args: list[str]) -> subprocess.CompletedProcess[str]:
            assert args == ["python3", str(self.paths[PROBE])]
            output = io.StringIO()
            with redirect_stdout(output):
                assert probe.main() == 0
            return subprocess.CompletedProcess(args, 0, output.getvalue())

        monkeypatch.setattr(self.producer, "run", run_probe)
        result = run_probe(["python3", self.producer.PROBE_PATH])
        observed = self.producer.observe(now=now)
        hb = self.heartbeat.derive_heartbeat(
            system_id="wishicraft-main",
            canonical_game_id=game,
            observation=observed,
            previous=previous,
        )
        return json.loads(result.stdout), hb


def test_old_probe_mismatch_then_actual_bundle_repairs_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Installed(tmp_path, monkeypatch)
    game = "game-vanilla-secondary"
    source = f"/srv/minecraft/games/{game}/worlds/op-reset-one/server"
    before, hb = host.heartbeat_record(monkeypatch, game=game, source=source)
    assert before["active_game"]["binding_consistency"] == "mismatch" and hb.empty_since is None
    for legacy in ("game-vanilla-main", "game-vanilla-secondary"):
        legacy_probe, legacy_hb = host.heartbeat_record(
            monkeypatch, game=legacy, source=f"/srv/minecraft/games/{legacy}/server"
        )
        assert legacy_probe["active_game"]["binding_consistency"] == "consistent"
        assert legacy_hb.empty_since == NOW
    host.install()
    after, hb = host.heartbeat_record(monkeypatch, game=game, source=source)
    assert after["active_game"]["binding_consistency"] == "consistent" and hb.empty_since == NOW
    entry = next(e for e in host.plan["files"] if e["destination"] == str(host.paths[PROBE]))
    assert host.paths[PROBE].stat().st_mode & 0o777 == 0o755
    assert hashlib.sha256(host.paths[PROBE].read_bytes()).hexdigest() == entry["sha256"]
    assert (
        host.installer.RECEIPTS / "reset-v1" / ("predecessor-" + entry["source"])
    ).read_bytes() == history("src/wishicraft/artifacts/host_runtime_probe.py")
    host.install()  # Same bundle remains resumable/idempotent.


@pytest.mark.parametrize("game", ["game-vanilla-main", "game-vanilla-secondary"])
def test_legacy_new_world_and_same_boot_run_continuity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, game: str
) -> None:
    host = Installed(tmp_path, monkeypatch)
    host.install()
    _, old = host.heartbeat_record(
        monkeypatch, game=game, source=f"/srv/minecraft/games/{game}/server", run="op-old"
    )
    _, new = host.heartbeat_record(
        monkeypatch,
        game=game,
        source=f"/srv/minecraft/games/{game}/worlds/op-world/server",
        previous=old,
        now=NOW + timedelta(seconds=60),
    )
    assert (
        old.boot_id == new.boot_id and old.run_id != new.run_id and old.process_id != new.process_id
    )
    assert new.empty_since == NOW + timedelta(seconds=60)
    from wishicraft.auto_stop import deterministic_intent_id

    def intent(hb: Any) -> str:
        return deterministic_intent_id(
            game_id=game,
            boot_id=hb.boot_id,
            empty_since=hb.empty_since,
            run_id=hb.run_id,
            process_id=hb.process_id,
        )

    assert intent(old) != intent(new)  # A delivered old warning cannot authorize this new run.
    _, next_hb = host.heartbeat_record(
        monkeypatch,
        game=game,
        source=f"/srv/minecraft/games/{game}/worlds/op-world/server",
        previous=new,
        now=NOW + timedelta(seconds=120),
    )
    assert next_hb.empty_since == new.empty_since


@pytest.mark.parametrize(
    "count,path,actual",
    [
        (1, "worlds/op-world/server", None),
        (None, "worlds/op-world/server", None),
        (0, "worlds/../server", None),
        (0, "worlds/unknown/server", None),
        (0, "worlds/op-world/server", "/srv/minecraft/games/game-vanilla-main/server"),
    ],
)
def test_positive_unknown_and_invalid_binding_are_not_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count: int | None,
    path: str,
    actual: str | None,
) -> None:
    host = Installed(tmp_path, monkeypatch)
    host.install()
    _, hb = host.heartbeat_record(
        monkeypatch,
        game="game-vanilla-secondary",
        source="/srv/minecraft/games/game-vanilla-secondary/" + path,
        count=count,
        actual_source=actual,
    )
    assert hb.empty_since is None


@pytest.mark.parametrize("fault", ["unknown", "missing", "mode", "owner", "symlink"])
def test_probe_predecessor_rejected_before_any_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    host = Installed(tmp_path, monkeypatch)
    probe = host.paths[PROBE]
    if fault == "unknown":
        probe.write_text("unknown")
    elif fault == "missing":
        probe.unlink()
    elif fault == "mode":
        probe.chmod(0o600)
    elif fault == "owner":
        host.bad_owner = probe
    elif fault == "symlink":
        probe.unlink()
        probe.symlink_to(host.paths["/etc/wishicraft/host-runtime/manifest.json"])
    before = {str(p): p.read_bytes() for p in host.paths.values() if p.exists()}
    with pytest.raises(ValueError):
        host.install()
    assert before == {str(p): p.read_bytes() for p in host.paths.values() if p.exists()}


@pytest.mark.parametrize("destination", [PROBE, "/usr/local/libexec/wishicraft/operation-v2"])
def test_partial_bundle_resume_after_atomic_probe_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    host = Installed(tmp_path, monkeypatch)
    original = host.installer.os.replace

    def lose_reply(source: Any, target: Any) -> None:
        original(source, target)
        if Path(target) == host.paths[destination]:
            raise OSError("synthetic response loss")

    with monkeypatch.context() as scoped:
        scoped.setattr(host.installer.os, "replace", lose_reply)
        with pytest.raises(OSError):
            host.install()
    host.install()
    assert all(not host.installer.validate_entry(e) for e in host.plan["files"])
