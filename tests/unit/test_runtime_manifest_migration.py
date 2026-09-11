"""Real installer boundaries with a filesystem fixture and explicit host substitutes."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from wishicraft.artifacts import runtime_install as installer
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts
from wishicraft.runtime_migration import prepare

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "i-04fc0629dc4ea466e"
LEGACY = {
    "schema_version": 1,
    "apply_class": "boot-time",
    "game_id": "game-vanilla-main",
    "image": "ghcr.io/itzg/minecraft-server:2026.7.2-java25@sha256:"
    "6ec1110e4d9236d00ae9436a3e4a5929583e5b19cc94b756a7c603f7cf647a77",
    "minecraft_version": "26.2",
    "server_type": "VANILLA",
    "compose_sha256": "08c5cee203eb8350e30778456ccd1e240eeff5e9cc65494b292684092c0108a7",
    "runtime_env_sha256": "271ce8bea4effa701c90c35c9ff3e93266437cfa76a84ed917d6381900d26837",
    "secret_material_included": False,
}
LEGACY_BYTES = (json.dumps(LEGACY, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_historical_renderer_and_new_manifest(tmp_path: Path) -> None:
    import runpy

    old = tmp_path / "renderer.py"
    old.write_bytes(
        subprocess.check_output(["git", "show", "b3e27e1:src/wishicraft/host_runtime.py"], cwd=ROOT)
    )
    for name in ("project.yaml", "stages/dev.yaml", "secrets.example.yaml"):
        path = tmp_path / "config" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            subprocess.check_output(["git", "show", "b3e27e1:config/" + name], cwd=ROOT)
        )
    config = load_configuration(tmp_path, "dev")
    rendered = runpy.run_path(str(old))["render_boot_time_artifacts"](
        config.project,
        config.stage,
        observed_uid=993,
        observed_gid=993,
        publish_minecraft_port=False,
    )
    assert rendered.manifest_json.encode() == LEGACY_BYTES
    bundle = tmp_path / "bundle"
    prepare(ROOT, bundle, INSTANCE)
    entries = json.loads((bundle / "install.json").read_text())["files"]
    manifest = next(e for e in entries if e["destination"].endswith("/manifest.json"))
    assert manifest["predecessor"] == hashlib.sha256(LEGACY_BYTES).hexdigest()
    new = json.loads((bundle / manifest["source"]).read_text())
    for field, name in (("compose_sha256", "compose.yaml"), ("runtime_env_sha256", "runtime.env")):
        entry = next(e for e in entries if e["destination"].endswith("/" + name))
        assert new[field] == hashlib.sha256((bundle / entry["source"]).read_bytes()).hexdigest()
    config = load_configuration(ROOT, "dev")
    assert new == json.loads(
        render_boot_time_artifacts(
            config.project,
            config.stage,
            observed_uid=993,
            observed_gid=993,
            enable_rcon=True,
            rcon_parameter_name="/wishicraft/dev/secret/rcon-password",
            targeted=True,
        ).manifest_json
    )


@pytest.fixture
def host_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    bundle, targets, receipts = tmp_path / "bundle", tmp_path / "host", tmp_path / "receipts"
    bundle.mkdir()
    targets.mkdir()
    entries = []
    for i, (name, previous) in enumerate(
        (("manifest.json", LEGACY_BYTES), ("other", b"old-other"))
    ):
        source, target = bundle / str(i), targets / name
        source.write_bytes(b"new-" + name.encode())
        target.write_bytes(previous)
        target.chmod(0o600)
        entries.append(
            {
                "destination": str(target),
                "source": str(i),
                "mode": 0o600,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "predecessor": hashlib.sha256(previous).hexdigest(),
            }
        )
    (bundle / "install.json").write_text(json.dumps({"instance_id": INSTANCE, "files": entries}))
    monkeypatch.setattr(installer, "BUNDLE", bundle)
    monkeypatch.setattr(installer, "RECEIPTS", receipts)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    original_stat = Path.stat
    owners: dict[str, int] = {}

    def root_stat(path: Path, **kwargs: Any) -> Any:
        info = original_stat(path, **kwargs)
        if path in (targets / "manifest.json", targets / "other"):
            return SimpleNamespace(st_mode=info.st_mode, st_uid=owners.get(path.name, 0), st_gid=0)
        return info

    monkeypatch.setattr(Path, "stat", root_stat)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, **kwargs: io.BytesIO(
            INSTANCE.encode() if request.full_url.endswith("instance-id") else b"token"
        ),
    )
    calls = []

    def run(args: list[str]) -> str:
        calls.append(args)
        return "inactive" if args[:2] == ["systemctl", "show"] else ""

    monkeypatch.setattr(installer, "run", run)
    return {
        "targets": targets,
        "receipts": receipts,
        "entries": entries,
        "owners": owners,
        "calls": calls,
    }


def test_existing_manifest_install_and_same_bundle_resume(
    host_tree: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = host_tree["targets"] / "manifest.json"
    original_replace = os.replace

    def interrupt(source: str, destination: Path) -> None:
        if destination.name == "other":
            raise OSError("interrupted before second replacement")
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        installer.install()
    assert target.read_bytes() == b"new-manifest.json"
    assert (host_tree["receipts"] / "predecessor-0").read_bytes() == LEGACY_BYTES
    before = target.stat().st_mode
    monkeypatch.setattr(os, "replace", original_replace)
    installer.install()
    assert target.stat().st_mode == before
    assert (host_tree["targets"] / "other").read_bytes() == b"new-other"
    assert (host_tree["receipts"] / "predecessor-0").read_bytes() == LEGACY_BYTES
    (host_tree["receipts"] / "receipt.json").write_text("{}")
    with pytest.raises(ValueError, match="EXECUTION_ALREADY_RECORDED"):
        installer.install()


@pytest.mark.parametrize(
    "damage,error",
    [
        ("unknown", "UNKNOWN_PREDECESSOR"),
        ("missing", "MISSING_PREDECESSOR"),
        ("owner", "TARGET_OWNER_MODE"),
        ("mode", "TARGET_OWNER_MODE"),
        ("symlink", "FILE_IDENTITY"),
        ("other", "UNKNOWN_PREDECESSOR"),
    ],
)
def test_all_artifacts_checked_before_first_replace(
    host_tree: dict[str, Any], damage: str, error: str
) -> None:
    target = host_tree["targets"] / "manifest.json"
    if damage == "unknown":
        target.write_bytes(b"unknown")
    elif damage == "missing":
        target.unlink()
    elif damage == "owner":
        host_tree["owners"]["manifest.json"] = 501
    elif damage == "mode":
        target.chmod(0o644)
    elif damage == "symlink":
        target.unlink()
        target.symlink_to(host_tree["targets"] / "other")
    else:
        (host_tree["targets"] / "other").write_bytes(b"unknown-other")
    with pytest.raises(ValueError, match=error):
        installer.install()
    assert not host_tree["receipts"].exists()
    if damage == "other":
        assert target.read_bytes() == LEGACY_BYTES
