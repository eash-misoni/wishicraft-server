"""Canonical stage copies and explicit legacy input exercise both public entry paths."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from aws_cdk import Stack
from aws_cdk.assertions import Template

from infrastructure.app import build_app, retention_input
from tests.unit.test_daily_backup_inputs import cli, cli_context
from wishicraft.retention_release import RetentionRelease, load_retention_release

ROOT = Path(__file__).resolve().parents[2]


def copy_configuration(tmp_path: Path, provision: bool, enabled: bool) -> Path:
    root = tmp_path / "input"
    shutil.copytree(ROOT / "config", root / "config")
    (root / "config/retention-execution-dev.json").write_text(
        json.dumps(dict(schema_version=1, provision=provision, enabled=enabled))
    )
    return root


def check_resources(resources: dict[str, Any], provision: bool, enabled: bool) -> None:
    fn = next(
        v
        for k, v in resources.items()
        if k.startswith("RetentionTaskFunction") and v["Type"] == "AWS::Lambda::Function"
    )
    env = fn["Properties"]["Environment"]["Variables"]
    if provision:
        assert env["RETENTION_PROVISIONED"] == "1"
        assert env["RETENTION_DELETE_ENABLED"] == str(int(enabled))
    else:
        assert "RETENTION_PROVISIONED" not in env and "RETENTION_DELETE_ENABLED" not in env
    assert ("ec2:DeleteSnapshot" in json.dumps(resources)) is enabled
    asl = next(
        v
        for k, v in resources.items()
        if k.startswith("RetentionStateMachine") and v["Type"] == "AWS::StepFunctions::StateMachine"
    )
    assert ("DELETE_ONE" in json.dumps(asl)) is enabled


@pytest.mark.parametrize("provision,enabled", [(False, False), (True, False), (True, True)])
def test_build_app_canonical_and_legacy_are_independent(
    tmp_path: Path, provision: bool, enabled: bool, capsys: Any
) -> None:
    root = copy_configuration(tmp_path, provision, enabled)
    assert load_retention_release(root, "dev") == RetentionRelease(provision, enabled)
    for legacy in (True, False):
        app = build_app(
            root,
            "dev",
            phase=8,
            deployment="control-plane",
            two_games=not legacy,
            daily_backup_validation="legacy" if legacy else None,
            retention_validation="disabled" if legacy else None,
        )
        stack = cast(Stack, app.node.find_child("WishicraftControlPlaneStack-dev"))
        resources = Template.from_stack(stack).to_json()["Resources"]
        check_resources(resources, provision and not legacy, enabled and not legacy)
        assert sum(v["Type"] == "AWS::Lambda::Function" for v in resources.values()) == (
            11 if legacy else 13
        )
        assert len([k for k in resources if k.startswith("DailyBackup")]) == (0 if legacy else 15)
    output = capsys.readouterr().err
    assert '"retention_input": "validation-only:disabled"' in output
    assert str(root / "config/retention-execution-dev.json") in output
    if provision:
        with pytest.raises(ValueError, match="shared runtime"):
            build_app(
                root, "dev", phase=8, deployment="control-plane", daily_backup_validation="legacy"
            )


@pytest.mark.parametrize("provision,enabled", [(False, False), (True, False), (True, True)])
def test_cli_stage_file_and_explicit_legacy(tmp_path: Path, provision: bool, enabled: bool) -> None:
    root = copy_configuration(tmp_path, provision, enabled)
    # Real CLI derives canonical root from its own file; copy only its local test inputs.
    shutil.copytree(
        ROOT / "infrastructure",
        root / "infrastructure",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in (
        "src",
        "pyproject.toml",
        "uv.lock",
        "tools",
        "node_modules",
        "scripts",
        "web",
        "docs",
    ):
        if (ROOT / name).exists():
            (root / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
    for legacy in (True, False):
        context = cli_context()
        if legacy:
            context.pop("two_games")
            context.pop("reset")
            context.pop("game_creation")
            context.pop("game_packages")
            context.pop("whitelist_management")
            context.update(
                validation_action="synth",
                daily_backup_validation="legacy",
                retention_validation="disabled",
            )
        outdir = tmp_path / ("legacy" if legacy else "canonical")
        result = cli(outdir, context, root=root)
        assert result.returncode == 0, result.stderr
        report = next(
            json.loads(line)
            for line in result.stderr.splitlines()
            if line.startswith('{"retention_input"')
        )
        assert report == dict(
            retention_input="validation-only:disabled"
            if legacy
            else str(root / "config/retention-execution-dev.json"),
            provision=provision and not legacy,
            enabled=enabled and not legacy,
        )
        resources = json.loads(
            (outdir / "WishicraftControlPlaneStack-dev.template.json").read_text()
        )["Resources"]
        check_resources(resources, provision and not legacy, enabled and not legacy)
        assert sum(v["Type"] == "AWS::Lambda::Function" for v in resources.values()) == (
            11 if legacy else 13
        )
    if provision:
        context = dict(
            stage="dev",
            phase="8",
            deployment="control-plane",
            validation_action="synth",
            daily_backup_validation="legacy",
        )
        denied = cli(tmp_path / "denied", context, root=root)
        assert denied.returncode != 0 and "shared runtime" in denied.stderr


def test_missing_file_default_uses_its_own_root(tmp_path: Path, capsys: Any) -> None:
    assert retention_input(tmp_path, "dev") == RetentionRelease()
    assert "missing-stage-supplement:default-disabled" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [(False, True), ("true", False), (True, 1), (None, False)])
def test_invalid_stage_file_is_not_coerced(tmp_path: Path, flags: tuple[Any, Any]) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/retention-execution-dev.json").write_text(
        json.dumps(dict(schema_version=1, provision=flags[0], enabled=flags[1]))
    )
    with pytest.raises(ValueError):
        retention_input(tmp_path, "dev")
