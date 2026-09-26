"""Deployment inputs and synth-only historical scenarios must not silently mix."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app, daily_backup_input
from wishicraft.config import load_daily_backup_configuration

ROOT = Path(__file__).resolve().parents[2]


def resources(root: Path, *, validation: str | None, shared: bool = True) -> dict[str, Any]:
    app = build_app(
        root,
        "dev",
        phase=8,
        deployment="control-plane",
        two_games=shared,
        daily_backup_validation=validation,
    )
    stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
    return cast(dict[str, Any], Template.from_stack(stack).to_json()["Resources"])


@pytest.mark.parametrize("provision,enabled", [(False, False), (True, False), (True, True)])
def test_explicit_legacy_is_independent_of_stage_and_canonical_uses_stage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    provision: bool,
    enabled: bool,
) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "config/daily-backup-dev.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provision": provision,
                "enabled": enabled,
            }
        )
    )
    for shared in (False, True):
        legacy = resources(tmp_path, validation="legacy", shared=shared)
        assert sum(r["Type"] == "AWS::Lambda::Function" for r in legacy.values()) == 11
        assert not any(k.startswith("DailyBackup") for k in legacy)
    current = resources(tmp_path, validation=None)
    daily = {k: v for k, v in current.items() if k.startswith("DailyBackup")}
    assert len(daily) == (15 if provision else 0)
    if provision:
        with pytest.raises(ValueError, match="daily BACKUP requires the shared runtime contract"):
            resources(tmp_path, validation=None, shared=False)
        rule = next(r["Properties"] for r in daily.values() if r["Type"] == "AWS::Events::Rule")
        assert rule["State"] == ("ENABLED" if enabled else "DISABLED")
    output = capsys.readouterr().err
    assert '"daily_backup_input": "validation-only:legacy"' in output
    assert str(tmp_path / "config/daily-backup-dev.json") in output


def test_single_game_explicit_provision_keeps_shared_runtime_guard() -> None:
    with pytest.raises(ValueError, match="daily BACKUP requires the shared runtime contract"):
        resources(ROOT, validation="enabled", shared=False)


@pytest.mark.parametrize(
    "validation,action", [("legacy", "deploy"), ("enabled", "deploy"), ("unknown", "synth")]
)
def test_validation_input_is_not_a_deployment_default(validation: str, action: str) -> None:
    with pytest.raises(ValueError, match="synth-only"):
        daily_backup_input(ROOT, "dev", validation=validation, action=action)


@pytest.mark.parametrize(
    "flags",
    [
        {"provision": False, "enabled": True},
        {"provision": "true", "enabled": False},
        {"provision": True, "enabled": 1},
        {"provision": None, "enabled": False},
    ],
)
def test_canonical_invalid_flags_are_not_coerced(tmp_path: Path, flags: dict[str, Any]) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/daily-backup-dev.json").write_text(
        json.dumps({"schema_version": 1, **flags})
    )
    with pytest.raises(ValueError):
        daily_backup_input(tmp_path, "dev")


def cli(tmp_path: Path, context: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # Child-scoped CDK input, never a process-wide test mutation; no environment is logged.
    environment = {
        **os.environ,
        "CDK_CONTEXT_JSON": json.dumps(context),
        "CDK_OUTDIR": str(tmp_path),
    }
    return subprocess.run(
        [sys.executable, "-m", "infrastructure.app"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def cli_context() -> dict[str, str]:
    return {
        "stage": "dev",
        "phase": "8",
        "deployment": "control-plane",
        "two_games": "true",
        "reset": "true",
        "game_creation": "true",
        "whitelist_management": "true",
        "game_packages": "true",
    }


@pytest.mark.parametrize("validation", [None, "legacy", "enabled"])
def test_cli_full_shared_input_matches_build_app_selection(
    tmp_path: Path, validation: str | None
) -> None:
    context = cli_context()
    if validation is not None:
        context.update(validation_action="synth", daily_backup_validation=validation)
    result = cli(tmp_path, context)
    assert result.returncode == 0, result.stderr
    flags = daily_backup_input(ROOT, "dev", validation=validation)
    report = next(
        json.loads(line)
        for line in result.stderr.splitlines()
        if line.startswith('{"daily_backup_input"')
    )
    assert {k: report[k] for k in ("provision", "enabled")} == flags
    assert report["daily_backup_input"] == (
        f"validation-only:{validation}"
        if validation
        else str(ROOT / "config/daily-backup-dev.json")
    )
    template = json.loads((tmp_path / "WishicraftControlPlaneStack-dev.template.json").read_text())
    daily = {k: v for k, v in template["Resources"].items() if k.startswith("DailyBackup")}
    assert len(daily) == (15 if flags["provision"] else 0)
    if daily:
        for resource in daily.values():
            properties = resource["Properties"]
            if resource["Type"] == "AWS::Lambda::Function":
                assert properties["Environment"]["Variables"]["DAILY_BACKUP_ENABLED"] == (
                    "1" if flags["enabled"] else "0"
                )
            if resource["Type"] == "AWS::Events::Rule":
                assert properties["State"] == ("ENABLED" if flags["enabled"] else "DISABLED")
            if resource["Type"] == "AWS::CloudWatch::Alarm":
                assert properties["ActionsEnabled"] is flags["enabled"]


@pytest.mark.parametrize("action", [None, "deploy"])
def test_cli_validation_requires_explicit_synth(tmp_path: Path, action: str | None) -> None:
    context = cli_context()
    context["daily_backup_validation"] = "legacy"
    if action:
        context["validation_action"] = action
    result = cli(tmp_path, context)
    assert result.returncode != 0
    assert "requires explicit validation_action=synth" in result.stderr


def test_cli_single_game_enabled_still_rejects(tmp_path: Path) -> None:
    result = cli(
        tmp_path,
        {
            "stage": "dev",
            "phase": "8",
            "deployment": "control-plane",
            "validation_action": "synth",
            "daily_backup_validation": "enabled",
        },
    )
    assert result.returncode != 0
    assert "daily BACKUP requires the shared runtime contract" in result.stderr


def test_canonical_missing_supplement_is_still_disabled(tmp_path: Path) -> None:
    assert (
        daily_backup_input(tmp_path, "dev")
        == load_daily_backup_configuration(tmp_path, "dev")
        == {
            "provision": False,
            "enabled": False,
        }
    )
