"""Pinned package integrity, interrupted writes and generation/Game isolation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts.targeted_runtime import atomic
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def filesystem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    games = tmp_path / "games"
    games.mkdir(mode=0o755)
    monkeypatch.setattr(packages, "GAMES", games)
    monkeypatch.setattr(packages, "OWNER_UID", os.getuid())
    monkeypatch.setattr(packages, "OWNER_GID", os.getgid())
    package = packages.load()[1]
    for artifact in [*package["mods"], package["loader"]["installer"]]:
        content = artifact["filename"].encode()
        artifact.update(size=len(content), sha256=hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(packages, "fetch", lambda spec: spec["filename"].encode())
    for game in ("game-a", "game-b"):
        server = games / game / "server"
        server.mkdir(parents=True, mode=0o755)
        (server / "world").mkdir()
        (server / "world/level.dat").write_bytes(game.encode())
    return games, package


def materialize(games: Path, package: dict[str, Any], game: str = "game-a") -> None:
    packages.materialize_mods(
        {"game_id": game, "data_source": str(games / game / "server")},
        package,
        atomic,
        uid=os.getuid(),
        gid=os.getgid(),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("minecraft_version", "latest"),
        ("package_version", "^1"),
        ("minecraft_version", "1.21.2"),
    ],
)
def test_floating_and_unsupported_versions(field: str, value: str) -> None:
    candidate = packages.load()[1]
    candidate[field] = value
    with pytest.raises(ValueError):
        packages.validate(candidate)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "f" * 63),
        ("filename", "../mod.jar"),
        ("url", "https://example.com/latest.jar"),
        ("version", ">=6.0"),
        ("size", True),
        ("client_required", False),
        ("file_id", "latest"),
    ],
)
def test_invalid_artifact(field: str, value: Any) -> None:
    candidate = packages.load()[1]
    candidate["mods"][0][field] = value
    with pytest.raises(ValueError):
        packages.validate(candidate)


def test_duplicate_and_loader_mismatch() -> None:
    package = packages.load()[1]
    package["mods"].append(copy.deepcopy(package["mods"][0]))
    with pytest.raises(ValueError, match="DUPLICATE"):
        packages.validate(package)
    package = packages.load()[1]
    package["loader"]["version"] = "21.1.220"
    with pytest.raises(ValueError, match="INSTALLER_VERSION"):
        packages.validate(package)


def test_manifest_commits_every_package_field_and_legacy_is_unchanged() -> None:
    cfg = load_configuration(ROOT, "dev")
    games = tuple(json.loads((ROOT / "config/two-game-dev.json").read_text()))

    def render(value: Any = None) -> Any:
        return render_boot_time_artifacts(
            cfg.project,
            cfg.stage,
            observed_uid=993,
            observed_gid=993,
            targeted=True,
            games=games,
            packages=value,
        )

    legacy = render()
    assert render(None) == legacy
    current = render(packages.load())
    assert current == render(packages.load()) and current.digest != legacy.digest
    manifest = json.loads(current.manifest_json)
    assert manifest["packages"] == packages.load()
    assert current.digest == hashlib.sha256(current.manifest_json.encode()).hexdigest()
    changed = packages.load()
    changed[1]["mods"][0]["sha256"] = "a" * 64
    assert render(changed).digest != current.digest
    compose = yaml.safe_load(current.compose_yaml)["services"]["minecraft"]
    assert compose["mem_limit"] == "6144MiB"
    assert "MAX_MEMORY=4G" in current.runtime_env and "INIT_MEMORY=1G" in current.runtime_env
    assert "TYPE=" not in current.runtime_env and "VERSION=" not in current.runtime_env
    assert "WISHICRAFT_PACKAGE_TYPE?" in compose["environment"]["TYPE"]


def test_registration_is_exact_and_legacy_only_vanilla() -> None:
    catalog = packages.load()
    package = catalog[1]
    manifest = {"packages": catalog, "games": ["game-a", "game-b"]}
    game = {
        "game_id": "game-new",
        "runtime": {"class": "default"},
        "package": {
            "package_id": package["package_id"],
            "package_version": package["package_version"],
            "definition": package,
        },
        "creation": {"config_digest": "a" * 64, "package_digest": packages.digest(package)},
    }
    assert packages.registered(game, manifest, "a" * 64) == package
    with pytest.raises(ValueError, match="REGISTRATION"):
        packages.registered(game, manifest, "b" * 64)
    game.pop("creation")
    game["game_id"] = "game-a"
    with pytest.raises(ValueError, match="LEGACY"):
        packages.registered(game, manifest, "a" * 64)
    game["package"] = {k: catalog[0][k] for k in ("package_id", "package_version")}
    assert packages.registered(game, manifest, "a" * 64)["loader"]["type"] == "vanilla"


def test_private_materialization_retry_and_world_preservation(filesystem: Any) -> None:
    games, package = filesystem
    materialize(games, package)
    cache = packages.location("game-a")
    files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in cache.rglob("*.jar")}
    materialize(games, package)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == prior for p, prior in files.items())
    materialize(games, packages.load()[0], "game-b")
    assert list((games / "game-b/server/mods").iterdir()) == []
    for game in ("game-a", "game-b"):
        assert (games / game / "server/world/level.dat").read_bytes() == game.encode()
    assert not (games / "game-b/server/libraries").exists()


def test_download_failure_and_partial_retry(
    filesystem: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    games, package = filesystem
    real_fetch = packages.fetch
    calls = 0

    def interrupted(spec: Any) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("upstream unavailable")
        return real_fetch(spec)

    monkeypatch.setattr(packages, "fetch", interrupted)
    with pytest.raises(OSError):
        materialize(games, package)
    first = packages.location("game-a") / "mods" / package["mods"][0]["filename"]
    prior = first.stat().st_mtime_ns
    partial = first.with_name(first.name + ".partial")
    partial.write_bytes(b"interrupted temporary")
    monkeypatch.setattr(packages, "fetch", real_fetch)
    materialize(games, package)
    assert first.stat().st_mtime_ns == prior and not partial.exists()
    projected = games / "game-a/server/mods" / first.name
    projected.with_name(projected.name + ".partial").write_bytes(b"partial projection")
    materialize(games, package)
    assert not projected.with_name(projected.name + ".partial").exists()


@pytest.mark.parametrize("where", ["cache", "projection"])
def test_corruption_never_becomes_vanilla(filesystem: Any, where: str) -> None:
    games, package = filesystem
    materialize(games, package)
    base = packages.location("game-a") if where == "cache" else games / "game-a/server"
    jar = base / "mods" / package["mods"][0]["filename"]
    jar.chmod(0o600)
    jar.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="HASH"):
        materialize(games, package)
    assert (games / "game-a/server/world/level.dat").read_bytes() == b"game-a"


def test_unowned_and_symlink_refused(filesystem: Any) -> None:
    games, package = filesystem
    cache = packages.location("game-a")
    cache.symlink_to(games / "game-b", target_is_directory=True)
    with pytest.raises(ValueError, match="UNOWNED"):
        materialize(games, package)
    cache.unlink()
    materialize(games, package)
    (cache / "mods/unknown.jar").symlink_to(games / "game-b/server/world/level.dat")
    with pytest.raises(ValueError, match="UNKNOWN"):
        materialize(games, package)


def test_offline_bundle_reuses_installer_without_record_or_data_changes(tmp_path: Path) -> None:
    from tests.unit.test_runtime_memory import inventory, receipt
    from wishicraft.game_package_migration import prepare

    result = prepare(ROOT, tmp_path / "bundle", receipt(), inventory())
    assert result["durable_record_updates"] == []
    assert result["new_digest"] != result["old_digest"]
    assert result["plan"]["receipt_predecessor"] == receipt()
    assert len(result["plan"]["files"]) == 8
    for entry in result["plan"]["files"]:
        assert not entry["destination"].startswith("/srv/")
        source = tmp_path / "bundle" / entry["source"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["sha256"]
    assert result["plan"]["package_environment"]["WISHICRAFT_PACKAGE_TYPE"] == "VANILLA"


def test_cdk_package_digest_recovery_compression_and_no_new_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aws_cdk import App
    from aws_cdk.assertions import Template

    from infrastructure.stacks.control_plane_stack import ControlPlaneStack
    from wishicraft.backup_workflow_lambda import recovery_runtime_config

    cfg = load_configuration(ROOT, "dev")
    games = tuple(json.loads((ROOT / "config/two-game-dev.json").read_text()))
    policy = json.loads((ROOT / "config/reset-dev.json").read_text())
    templates = []
    for enabled in (False, True):
        app = App(
            outdir=str(tmp_path / str(enabled)),
            context={"game_packages": str(enabled).lower(), "whitelist_management": "true"},
        )
        stack = ControlPlaneStack(
            app,
            project=cfg.project,
            stage=cfg.stage,
            secrets=cfg.secrets,
            phase=8,
            games=games,
            reset_policies=policy,
            game_creation=True,
        )
        templates.append(Template.from_stack(stack).to_json())
    old, new = (t["Resources"] for t in templates)
    assert {key: value["Type"] for key, value in old.items()} == {
        key: value["Type"] for key, value in new.items()
    }
    for key, resource in new.items():
        if resource["Type"] == "AWS::StepFunctions::StateMachine":
            assert resource == old[key]
        if resource["Type"] == "AWS::Lambda::Function":
            env = resource["Properties"]["Environment"]["Variables"]
            assert (
                sum(len(k) + len(v if isinstance(v, str) else "x" * 100) for k, v in env.items())
                < 4096
            )
            if resource["Properties"]["Handler"] == "wishicraft.backup_workflow_lambda.handler":
                assert "RECOVERY_RUNTIME_JSON" not in env
                monkeypatch.setenv("GAME_PACKAGES", "1")
                monkeypatch.setenv(
                    "RECOVERY_RUNTIME_ZLIB_BASE64", env["RECOVERY_RUNTIME_ZLIB_BASE64"]
                )
                runtime = json.loads(recovery_runtime_config())
                assert json.loads(runtime["manifest_json"])["packages"] == packages.load()
                assert (
                    hashlib.sha256(runtime["compose_yaml"].encode()).hexdigest()
                    == json.loads(runtime["manifest_json"])["compose_sha256"]
                )


@pytest.mark.parametrize("damage", ["version", "loader", "digest", "mount", "missing", "symlink"])
def test_observation_rejects_wrong_runtime_or_missing_mods(filesystem: Any, damage: str) -> None:
    games, package = filesystem
    materialize(games, package)
    target = {"game_id": "game-a", "data_source": str(games / "game-a/server")}
    actual: dict[str, Any] = {
        "Config": {
            "Env": [k + "=" + v for k, v in packages.environment(package).items()],
            "Labels": {"com.wishicraft.package-digest": packages.digest(package)},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(packages.location("game-a")),
                "Destination": "/wishicraft-package",
                "RW": False,
            }
        ],
    }
    manifest = {"packages": [packages.load()[0], package]}
    assert packages.observed(actual, manifest, target) == package
    if damage in {"version", "loader"}:
        key = "VERSION" if damage == "version" else "TYPE"
        actual["Config"]["Env"] = [
            v if not v.startswith(key + "=") else key + "=VANILLA" for v in actual["Config"]["Env"]
        ]
    elif damage == "digest":
        actual["Config"]["Labels"]["com.wishicraft.package-digest"] = "0" * 64
    elif damage == "mount":
        actual["Mounts"][0]["RW"] = True
    elif damage == "missing":
        (games / "game-a/server/mods" / package["mods"][0]["filename"]).unlink()
    else:
        directory = games / "game-a/server/mods"
        directory.rename(directory.with_name("saved-mods"))
        directory.symlink_to(directory.with_name("saved-mods"), target_is_directory=True)
    with pytest.raises(ValueError):
        packages.observed(actual, manifest, target)


def test_protocol_version_comes_from_integrity_checked_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins
    import subprocess

    from wishicraft.artifacts import host_runtime_probe as probe

    package = packages.load()[1]
    manifest = {
        "packages": packages.load(),
        "compose_sha256": hashlib.sha256(b"compose").hexdigest(),
        "runtime_env_sha256": hashlib.sha256(b"env").hexdigest(),
    }
    body = packages.canonical(manifest)
    target = {"config_digest": hashlib.sha256(body.encode()).hexdigest(), "run_id": "op-test"}
    documents = {
        "/etc/wishicraft/host-runtime/manifest.json": body,
        "/etc/wishicraft/host-runtime/compose.yaml": "compose",
        "/etc/wishicraft/host-runtime/runtime.env": "env",
        "/var/lib/wishicraft/runtime/receipt.json": json.dumps({"target": target}),
    }
    paths = {}
    for index, (name, value) in enumerate(documents.items()):
        paths[name] = tmp_path / str(index)
        paths[name].write_text(value)
    original_open, original_exists = builtins.open, os.path.exists

    def mapped_open(name: Any, *args: Any, **kw: Any) -> Any:
        return original_open(paths.get(name, name), *args, **kw)

    monkeypatch.setattr(builtins, "open", mapped_open)
    monkeypatch.setattr(os.path, "exists", lambda name: name in paths or original_exists(name))
    monkeypatch.setattr(
        probe,
        "run",
        lambda *args: subprocess.CompletedProcess(
            args, 0, json.dumps([{"Config": {"Labels": {"com.wishicraft.run-id": "op-test"}}}]), ""
        ),
    )

    def verified(actual: Any, observed_manifest: Any, observed_target: Any) -> Any:
        assert observed_manifest == manifest and observed_target == target
        return package

    monkeypatch.setattr(packages, "observed", verified)
    assert probe.package_version("container") == "1.21.1"
    assert probe.version_matches_expected("1.21.1", "1.21.1")
    assert not probe.version_matches_expected("26.2", "1.21.1")
    paths["/etc/wishicraft/host-runtime/runtime.env"].write_text("changed")
    with pytest.raises(ValueError, match="ARTIFACT_MISMATCH"):
        probe.package_version("container")


@pytest.mark.parametrize(
    "response",
    [
        "There are 1 of a max of 20 players online: Player\n\x1b[0m\n",
        "There are 0 of a max of 20 players online: Player\n\x1b[0m\n",
        "There are 0 of a max of 20 players online: \n\x1b[2J\n",
        "There are 0 of a max of 20 players online: \n\x1b[0m\nextra",
        "There are 0 of a max of 20 players online: \n\x1b[0m\x1b[0m\n",
        "unknown",
    ],
)
def test_neoforge_zero_player_gate_stays_fail_closed(response: str) -> None:
    from wishicraft.artifacts.targeted_runtime import confirmed_empty_players

    assert not confirmed_empty_players(response, neoforge=True)


def test_only_qualified_neoforge_accepts_observed_trailing_color_reset() -> None:
    from wishicraft.artifacts.targeted_runtime import confirmed_empty_players

    response = "There are 0 of a max of 20 players online: \n"
    assert confirmed_empty_players(response) and confirmed_empty_players(response, neoforge=True)
    response += "\x1b[0m\n"
    assert confirmed_empty_players(response, neoforge=True)
    assert not confirmed_empty_players(response)


def test_real_dynamo_serializers_preserve_package_list_and_booleans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wishicraft.artifacts import targeted_runtime as host
    from wishicraft.backup_provenance import _decode_map
    from wishicraft.operation import _attribute_map

    package = packages.load()[1]
    document: dict[str, object] = {"game_id": "game-test", "package": {"definition": package}}
    attributes = _attribute_map(document)
    monkeypatch.setattr(host, "execute", lambda *args, **kwargs: json.dumps({"Item": attributes}))
    assert (
        host.item(
            {"games_table": "synthetic", "region": "synthetic"},
            "games_table",
            "game_id",
            "game-test",
        )
        == document
    )
    assert _decode_map(attributes) == document
