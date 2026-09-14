"""Shared capacity, integrity and inactive migration regression tests."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from aws_cdk import App

from infrastructure.stacks.minecraft_target_stack import MinecraftTargetStack
from tests.unit.test_reset_probe_distribution import load
from wishicraft.config import ConfigValidationError, StageConfig, load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_contract import select_target
from wishicraft.runtime_memory import HOST_MEMORY_MIB, validate_memory
from wishicraft.runtime_memory_migration import prepare, validate_registry

ROOT = Path(__file__).resolve().parents[2]
GAMES = tuple(json.loads((ROOT / "config/two-game-dev.json").read_text()))


def stage(**changes: Any) -> StageConfig:
    values = copy.deepcopy(load_configuration(ROOT, "dev").stage.values)
    runtime = values["host_runtime"]
    assert isinstance(runtime, dict)
    runtime["memory"] = {
        "jvm_initial": "1G",
        "jvm_maximum": "4G",
        "container_limit": "6144MiB",
        **changes,
    }
    return StageConfig("dev", values)


@pytest.mark.parametrize(
    "changes",
    [
        {"jvm_initial": None},
        {"jvm_initial": True},
        {"jvm_initial": "0G"},
        {"jvm_initial": "1GiB"},
        {"jvm_initial": "5G"},
        {"jvm_initial": "256M"},
        {"jvm_maximum": "50%"},
        {"jvm_maximum": "4G\nJVM_OPTS=-x"},
        {"jvm_maximum": "1.5G"},
        {"jvm_maximum": "512M"},
        {"jvm_maximum": "5G"},
        {"container_limit": "4097MiB"},
        {"container_limit": "6145MiB"},
        {"container_limit": "8G"},
        {"container_limit": -1},
    ],
)
def test_unsafe_memory_rejected_by_renderer(changes: dict[str, Any]) -> None:
    with pytest.raises(ConfigValidationError):
        render_boot_time_artifacts(
            load_configuration(ROOT, "dev").project,
            stage(**changes),
            observed_uid=993,
            observed_gid=993,
        )


def test_budget_and_legacy_compatibility() -> None:
    assert set(HOST_MEMORY_MIB) == {"t3a.medium", "m8a.large", "r8a.large", "m8a.xlarge"}
    budget = validate_memory(stage())
    assert (budget.initial_mib, budget.maximum_mib, budget.container_mib, budget.host_mib) == (
        1024,
        4096,
        6144,
        8192,
    )
    assert validate_memory(stage(jvm_maximum="2G", container_limit="2816MiB")).container_mib == 2816
    with pytest.raises(ConfigValidationError):
        validate_memory(load_configuration(ROOT, "prod").stage)


def test_downsize_cannot_deploy_unsafe_existing_budget(tmp_path: Path) -> None:
    candidate = stage()
    runtime = candidate.values["host_runtime"]
    assert isinstance(runtime, dict) and isinstance(runtime["target_host"], dict)
    runtime["target_host"]["instance_type"] = "t3a.medium"
    with pytest.raises(ConfigValidationError, match="host RAM"):
        MinecraftTargetStack(
            App(outdir=str(tmp_path / "synth")),
            stage=candidate,
            project=load_configuration(ROOT, "dev").project,
        )


def test_artifact_changes_only_memory_and_preserves_integrity() -> None:
    cfg = load_configuration(ROOT, "dev")

    def render(value: StageConfig) -> Any:
        return render_boot_time_artifacts(
            cfg.project, value, observed_uid=993, observed_gid=993, targeted=True, games=GAMES
        )

    old = render(stage(jvm_maximum="2G", container_limit="2816MiB"))
    new = render(stage())
    assert new == render(stage()) and old.digest != new.digest
    old_compose, new_compose = yaml.safe_load(old.compose_yaml), yaml.safe_load(new.compose_yaml)
    assert new_compose["services"]["minecraft"].pop("mem_limit") == "6144MiB"
    old_compose["services"]["minecraft"].pop("mem_limit")
    assert old_compose == new_compose
    assert new.runtime_env.replace("MAX_MEMORY=4G", "MAX_MEMORY=2G") == old.runtime_env
    for artifact in (old, new):
        manifest = json.loads(artifact.manifest_json)
        assert (
            manifest["compose_sha256"] == hashlib.sha256(artifact.compose_yaml.encode()).hexdigest()
        )
        assert (
            manifest["runtime_env_sha256"]
            == hashlib.sha256(artifact.runtime_env.encode()).hexdigest()
        )
        assert artifact.digest == hashlib.sha256(artifact.manifest_json.encode()).hexdigest()


def inventory() -> dict[str, Any]:
    return {
        "Items": [
            {
                "game_id": {"S": key},
                "lifecycle_state": {"S": "ACTIVE"},
                "materialization_state": {"S": "MATERIALIZED"},
                "world": {"M": {"generation": {"N": "1"}}},
            }
            for key in (
                *GAMES,
                "policy-whitelist-common-v1",
                *("policy-whitelist-game-v1:" + game for game in GAMES),
            )
        ]
    }


def receipt() -> dict[str, Any]:
    evidence = json.loads((ROOT / "docs/evidence/2026-09-12-reset-production.json").read_text())
    return {
        "phase": "stopped",
        "stop": {"save_confirmed": True, "removal_ready": True},
        "target": {
            "instance_id": evidence["bundle"]["plan"]["instance_id"],
            "game_id": GAMES[0],
            "data_source": f"/srv/minecraft/games/{GAMES[0]}/server",
            "run_id": "op-previous",
            "config_digest": evidence["bundle"]["config_digest"],
        },
    }


def test_bundle_reuses_installer_and_changes_no_records(tmp_path: Path) -> None:
    records, stopped = inventory(), receipt()
    before = copy.deepcopy((records, stopped))
    result = prepare(ROOT, tmp_path / "bundle", stopped, records)
    assert result["durable_record_updates"] == []
    assert (records, stopped) == before
    entries = result["plan"]["files"]
    assert len(entries) == 4
    assert all(e["destination"].startswith("/etc/wishicraft/") for e in entries)
    assert result["plan"]["receipt_predecessor"] == stopped
    assert result["old_digest"] != result["new_digest"]
    old = json.loads((tmp_path / "bundle/3.predecessor").read_text())
    new = json.loads((tmp_path / "bundle/3.artifact").read_text())
    new["config_digest"] = old["config_digest"]
    assert new == old
    with pytest.raises(FileExistsError):
        prepare(ROOT, tmp_path / "bundle", stopped, records)


@pytest.mark.parametrize(
    "damage", ["creation", "registry", "unknown", "missing", "page", "unmaterialized"]
)
def test_migration_refuses_registration_or_incomplete_inventory(damage: str) -> None:
    value = inventory()
    if damage == "creation":
        value["Items"][0]["creation"] = {"M": {"config_digest": {"S": "a" * 64}}}
    elif damage in {"registry", "unknown"}:
        value["Items"].append(
            {"game_id": {"S": "registry-game-creation-v1" if damage == "registry" else "game-new"}}
        )
    elif damage == "missing":
        value["Items"].pop()
    elif damage == "page":
        value["LastEvaluatedKey"] = {"game_id": {"S": "x"}}
    else:
        value["Items"][0]["materialization_state"] = {"S": "UNMATERIALIZED"}
    with pytest.raises(ValueError):
        validate_registry(value, GAMES)


def test_start_uses_new_digest_without_rewriting_old_stopped_receipt() -> None:
    stopped = receipt()
    previous = copy.deepcopy(stopped)

    class Targets:
        def read(self, op: str) -> Any:
            raise KeyError(op)

        def freeze(self, **kwargs: Any) -> Any:
            return kwargs["target"]

    runtime = SimpleNamespace(
        targets=Targets(),
        resolver=SimpleNamespace(resolve=lambda: stopped["target"]["instance_id"]),
        game_id=GAMES[0],
        data_source=stopped["target"]["data_source"],
        config_digest="b" * 64,
    )
    target = select_target(
        runtime,
        SimpleNamespace(owner_operation_id="op-new", lease_id="lease-new"),
        {"observation": {"execution": stopped}},
        action="START",
    )
    assert target and target["config_digest"] == "b" * 64 and target["run_id"] == "op-new"
    assert stopped == previous


@pytest.mark.parametrize("fail_after", [1, 2, 3, 4])
def test_actual_four_file_installer_converges_without_data_or_receipt_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after: int
) -> None:
    bundle = tmp_path / "bundle"
    result = prepare(ROOT, bundle, receipt(), inventory())
    plan = result["plan"]
    targets = []
    for index, entry in enumerate(plan["files"]):
        target = tmp_path / "host" / entry["destination"].lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((bundle / f"{index}.predecessor").read_bytes())
        target.chmod(0o600)
        entry["destination"] = str(target)
        targets.append(target)
    (bundle / "install.json").write_text(json.dumps(plan))
    installer = load(bundle / "install.py", "memory_installer", monkeypatch)
    installer.BUNDLE = bundle
    installer.RECEIPTS = tmp_path / "receipts"
    installer.RECEIPTS.mkdir()
    stopped = installer.RECEIPTS / "receipt.json"
    stopped.write_text(json.dumps(plan["receipt_predecessor"]))
    stopped.chmod(0o600)
    world = tmp_path / "data/world/level.dat"
    world.parent.mkdir(parents=True)
    world.write_bytes(b"existing world, never copied or regenerated")
    originals = [(p, p.read_bytes(), p.stat().st_mtime_ns) for p in (world, stopped)]
    actual_stat = Path.stat

    def root_stat(path: Path, **kwargs: Any) -> Any:
        value = actual_stat(path, **kwargs)
        if path.is_relative_to(tmp_path):
            fields = list(value)
            fields[4], fields[5] = 0, 0
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "stat", root_stat)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer, "run", lambda args: "inactive" if "show" in args else "")
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda request, **kwargs: io.BytesIO(
            plan["instance_id"].encode() if request.full_url.endswith("instance-id") else b"token"
        ),
    )
    replace = os.replace
    count = 0

    def interrupted(source: Any, target: Any) -> None:
        nonlocal count
        replace(source, target)
        count += 1
        if count == fail_after:
            raise OSError("lost response after atomic replacement")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(OSError, match="lost response"):
        installer.main()
    monkeypatch.setattr(os, "replace", replace)
    installer.main()
    applied = [actual_stat(p).st_mtime_ns for p in targets]
    installer.main()
    assert applied == [actual_stat(p).st_mtime_ns for p in targets]
    for index, target in enumerate(targets):
        assert target.read_bytes() == (bundle / f"{index}.artifact").read_bytes()
        assert (installer.RECEIPTS / f"memory-v1/predecessor-{index}.artifact").read_bytes() == (
            bundle / f"{index}.predecessor"
        ).read_bytes()
    assert all(
        p.read_bytes() == value and actual_stat(p).st_mtime_ns == mtime
        for p, value, mtime in originals
    )
