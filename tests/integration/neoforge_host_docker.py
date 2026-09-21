"""Real host wrapper/Compose/NeoForge; isolated AWS and systemd adapters only."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import yaml  # noqa: E402

from tests.integration.neoforge_docker import registered_block, worldgen_evidence  # noqa: E402
from tests.probe_fixtures import runtime_running_document  # noqa: E402
from web.local_operations import MemoryDynamo, service  # noqa: E402
from wishicraft import interrupted_stop_recovery as recovery  # noqa: E402
from wishicraft.artifacts import game_package, whitelist_policy  # noqa: E402
from wishicraft.artifacts import targeted_runtime as host
from wishicraft.config import load_configuration  # noqa: E402
from wishicraft.game_creation import create  # noqa: E402
from wishicraft.host_runtime import render_boot_time_artifacts  # noqa: E402
from wishicraft.operation import WebOperationContext, _attribute_map  # noqa: E402
from wishicraft.package_authority import GamePackageAuthority  # noqa: E402
from wishicraft.probe import parse_host_runtime_probe  # noqa: E402
from wishicraft.ssm_probe import _canonical_probe_command  # noqa: E402
from wishicraft.web_status import decode  # noqa: E402


def main() -> None:
    if os.environ.get("CI") != "true" or sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("disposable root Linux CI only")
    root = Path(tempfile.mkdtemp(prefix="wishicraft-neoforge-docker-host-"))
    print("HOST_FIXTURE", root, flush=True)
    cfg = load_configuration(Path(__file__).resolve().parents[2], "dev")
    legacy = tuple(json.loads(Path("config/two-game-dev.json").read_text()))
    packages = game_package.load()
    rendered = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        games=legacy,
        packages=packages,
        publish_minecraft_port=False,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
    )
    artifacts = root / "artifacts"
    rendered.write_new(artifacts)
    secret = root / "synthetic-rcon"
    secret.write_text("synthetic-ci-only")
    secret.chmod(0o444)
    root.chmod(0o755)
    cli_root = Path("/run/wishicraft")
    assert not cli_root.exists(), "refuse existing ephemeral secret directory"
    cli_root.mkdir(mode=0o700)
    # The only rendered fixture adjustment is the synthetic secret source (no public ports).
    compose = yaml.safe_load(rendered.compose_yaml)
    for mount in compose["services"]["minecraft"]["volumes"]:
        if mount["target"] == "/run/secrets/rcon-password":
            mount["source"] = str(secret)
    text = yaml.safe_dump(compose, sort_keys=True)
    (artifacts / "compose.yaml").write_text(text)
    manifest = json.loads(rendered.manifest_json)
    manifest["compose_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    manifest_bytes = game_package.canonical(manifest).encode()
    (artifacts / "manifest.json").write_bytes(manifest_bytes)
    artifact_digest = hashlib.sha256(manifest_bytes).hexdigest()
    subprocess.run(["docker", "pull", manifest["image"]], check=True, timeout=300)
    Path("/srv/minecraft/games").mkdir(parents=True, exist_ok=True, mode=0o755)
    db = MemoryDynamo()
    domain = service(db)
    records = []
    for index, package in enumerate(packages):
        result = create(
            domain._repository,
            value={
                "display_name": "Create Survival" if index else "Vanilla fixture",
                "seed": "42",
                "reset": True,
                "package_id": package["package_id"],
            },
            key="web:" + hashlib.sha256((root.name + str(index)).encode()).hexdigest(),
            actor=WebOperationContext("9", "CI", "a" * 64, "b" * 64),
            now=datetime.now(UTC),
            defaults={
                "package": {"package_id": "vanilla", "package_version": "initial-fixed-version"},
                "runtime": {"class": "default", "idle_shutdown_minutes": 30},
                "config_digest": artifact_digest,
                "package_catalog": packages,
            },
        )
        game_id = db.records["operation", str(result["operation_id"])]["target_game_id"]["S"]
        records.append({k: decode(v) for k, v in db.records["games", game_id].items()})
        assert not game_package.GAMES.joinpath(game_id).exists()
    config = {
        "instance_id": "i-0123456789abcdef0",
        "game_id": legacy[0],
        "data_source": "/srv/minecraft/games/" + legacy[0] + "/server",
        "config_digest": artifact_digest,
        "system_id": "ci-only",
        "lock_name": "ci-only",
        "games": legacy,
        "game_creation": True,
        "games_table": "games",
        "operations_table": "operations_table",
        "locks_table": "locks_table",
        "region": "ap-northeast-1",
        "reset_policies": {},
        "initial_whitelist": [],
        "whitelist_management": True,
    }
    host.ROOT, host.CONFIG, host.ARTIFACTS, host.RUN_ENV = (
        root,
        root / "config.json",
        artifacts,
        root / "runtime-run.env",
    )
    host.CONFIG.write_text(json.dumps(config))
    host.CONFIG.chmod(0o600)
    # Exercise the unmodified SSM stdin command in the installed layout, outside
    # the checkout. Only systemd/IMDS/mount are unavailable in disposable CI.
    runtime_modules = Path("/usr/local/libexec/wishicraft")
    assert not runtime_modules.exists()
    runtime_modules.mkdir(parents=True)
    (runtime_modules / "game_package.py").write_bytes(Path(game_package.__file__).read_bytes())
    installed_artifacts = Path("/etc/wishicraft/host-runtime")
    assert not installed_artifacts.exists()
    installed_artifacts.parent.mkdir(parents=True, exist_ok=True)
    installed_artifacts.symlink_to(artifacts, target_is_directory=True)
    receipt_path = Path("/var/lib/wishicraft/runtime/receipt.json")
    assert not receipt_path.exists()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.symlink_to(root / "receipt.json")
    probe_bin = root / "probe-bin"
    probe_bin.mkdir()
    systemctl = probe_bin / "systemctl"
    systemctl.write_text("#!/bin/sh\n[ \"$1\" = show ] || exit 1\nprintf 'loaded\\nactive\\n'\n")
    systemctl.chmod(0o755)
    host.actual_instance = lambda: config["instance_id"]
    operation: dict[str, Any] = {}
    lease = {
        "owner_operation_id": "",
        "lease_id": "lease-ci",
        "resource_id": "ci-only",
        "lock_name": "ci-only",
        "lease_expires_at": 4070908800,
    }

    def item(config: Any, table: str, key: str, identity: str) -> dict[str, Any]:
        if table == "operations_table":
            return operation
        if table == "locks_table":
            return lease
        if identity == whitelist_policy.COMMON:
            return {
                "game_id": identity,
                "policy_json": whitelist_policy.encoded(whitelist_policy.empty()),
            }
        return next((g for g in records if g["game_id"] == identity), {})

    real_execute = host.execute
    state = "inactive"

    def compose_command(args: list[str], env: dict[str, str] | None = None) -> str:
        if env is None:
            env = {
                **os.environ,
                **dict(line.split("=", 1) for line in host.RUN_ENV.read_text().splitlines()),
            }
        return subprocess.run(
            ["docker", "compose", "-f", str(artifacts / "compose.yaml"), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=240,
        ).stdout

    def execute(args: list[str], *, timeout: int = 30) -> str:
        nonlocal state
        if args[:3] == ["aws", "dynamodb", "get-item"]:
            assert "--query" not in args
            key, value = next(iter(json.loads(args[args.index("--key") + 1]).items()))
            record = item(config, args[args.index("--table-name") + 1], key, value["S"])
            return json.dumps({"Item": _attribute_map(record)}) if record else ""
        env = dict(os.environ)
        if args[0] == "env":
            split = args.index("bash")
            env.update(dict(arg.split("=", 1) for arg in args[1:split]))
            args = args[split:]
        if args[0] == "bash":
            if len(args) >= 4 and args[-4] == "wishicraft-preflight":
                env.update(
                    WISHICRAFT_RUN_ID=args[-3], WISHICRAFT_GAME_ID=args[-2], GAME_DIRECTORY=args[-1]
                )
                compose_command(["ps", "--all", "--quiet", "minecraft"], env)
            return (
                ""  # disposable mount/platform boundary; real production script remains unchanged
            )
        if args[0].endswith("/rcon-secret-v2"):
            run_env = dict(line.split("=", 1) for line in host.RUN_ENV.read_text().splitlines())
            for name in ("rcon-cli.env", "rcon-cli.yaml"):
                placeholder = Path(run_env["GAME_DIRECTORY"]) / ("." + name)
                if placeholder.exists():
                    assert placeholder.is_file() and placeholder.stat().st_size == 0
                    placeholder.unlink()
                path = cli_root / name
                if args[1] == "prepare":
                    path.write_bytes(b"")
                    os.chown(path, 993, 993)
                    path.chmod(0o600)
                else:
                    path.unlink(missing_ok=True)
            return ""
        if args[:2] == ["systemctl", "show"]:
            return "success" if "--property=Result" in args else state
        if args[:2] == ["systemctl", "start"]:
            compose_command(["up", "--detach", "--no-build", "--pull", "never"])
            state = "active"
            for _ in range(150):
                containers = host.inspect()
                if containers:
                    if not containers[0]["State"]["Running"]:
                        raise AssertionError("server exited")
                    try:
                        real_execute(["docker", "exec", containers[0]["Id"], "mc-health"])
                        return ""
                    except RuntimeError:
                        pass
                time.sleep(4)
            raise AssertionError("server not healthy")
        if args[:2] == ["systemctl", "stop"]:
            current = host.inspect()[0]
            logs = real_execute(["docker", "logs", current["Id"]])
            (root / (operation["operation_id"] + "-" + current["Id"][:12] + ".log")).write_text(
                logs
            )
            compose_command(["stop", "--timeout", "150"])
            stopped = host.inspect()[0]["State"]
            assert stopped["ExitCode"] == 0 and not stopped["OOMKilled"]
            state = "inactive"
            return ""
        result = real_execute(args, timeout=timeout)
        if args[:2] == ["docker", "exec"] and args[-2:] == ["rcon-cli", "list"]:
            print("SYNTHETIC_RCON_LIST", repr(result), flush=True)
        return result

    host.execute = execute
    assert not host.inspect(), "refuse preexisting Compose project"
    sequence = 0
    current: dict[str, str] | None = None

    def start(game: dict[str, Any], *, reset: bool = False, commit: bool = True) -> dict[str, Any]:
        nonlocal sequence, current
        sequence += 1
        run = "op-package-" + str(sequence)
        target = {
            "instance_id": config["instance_id"],
            "game_id": game["game_id"],
            "data_source": str(game_package.GAMES / game["game_id"] / "server"),
            "config_digest": artifact_digest,
            "run_id": run,
        }
        if reset:
            target["data_source"] = str(
                game_package.GAMES / game["game_id"] / "worlds" / run / "server"
            )
        operation.update(
            operation_id=run,
            lease_id="lease-ci",
            operation_type="RESET" if reset else "SWITCH" if current else "START",
            status="RUNNING",
            timeout_at="2099-01-01T00:00:00Z",
            target_game_id=game["game_id"],
            runtime_target=target,
        )
        lease["owner_operation_id"] = run
        request = {
            "schema_version": 2,
            "operation_id": run,
            "lease_id": "lease-ci",
            "action": "START",
        }
        if current:
            operation["switch_source"] = dict(current)
            if reset:
                operation["reset_plan"] = json.dumps(
                    {
                        "schema_version": 1,
                        "source": current,
                        "target": target,
                        "seed": 43,
                        "policy": game["creation"]["reset_policy"],
                    }
                )
            host.apply({**request, "action": "STOP"})
            assert not host.inspect()
        if reset:
            host.apply({**request, "action": "RESET_PREPARE"})
            host.apply({**request, "action": "RESET_PREPARE"})
            assert not Path(target["data_source"]).joinpath("world").exists()
        host.apply(request)
        host.apply(request)
        current = target
        container = host.inspect()[0]
        host.validate_container(container, target)
        host.configured_container(container, manifest)
        package = game_package.observed(container, manifest, target)
        probe_result = subprocess.run(
            ["/bin/sh", "-c", _canonical_probe_command()],
            cwd="/",
            env={
                **os.environ,
                "PATH": str(probe_bin) + os.pathsep + os.environ["PATH"],
                "PYTHONPATH": "/does-not-exist",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert probe_result.returncode == 0, probe_result.stderr
        probe_document = json.loads(probe_result.stdout)
        assert probe_document["minecraft"]["ready"] is True, probe_document
        assert probe_document["active_game"]["game_id"] == game["game_id"]
        assert probe_document["active_game"]["binding_consistency"] == "consistent"
        assert probe_document["execution"]["target"] == target
        assert probe_document["minecraft"]["protocol"]["version_match"] is True
        # CI has no EC2 IMDS or retained XFS mount. Substitute ONLY these
        # infrastructure observations; retain actual package/protocol/execution.
        assert set(probe_document["errors"]) <= {
            "INSTANCE_ID_UNAVAILABLE",
            "INSTANCE_ID_INVALID",
            "MOUNT_OBSERVATION_FAILED",
        }, probe_document["errors"]
        probe_document["identity"]["instance_id"] = target["instance_id"]
        probe_document["mount"] = runtime_running_document()["mount"]
        probe_document["errors"] = []
        db.records["games", game["game_id"]] = _attribute_map(game)
        stdout = json.dumps(probe_document)
        expected = GamePackageAuthority(db, "games", legacy).expected_version(stdout)
        parsed = parse_host_runtime_probe(
            stdout,
            expected_instance_id=target["instance_id"],
            expected_minecraft_version=expected,
        )
        assert parsed.ready and parsed.protocol.version_match
        assert parsed.active_game.game_id == game["game_id"]
        assert parsed.execution and parsed.execution["target"] == target
        print(
            "EXACT_SSM_PACKAGE_AUTHORITY_PARSER_READY", package["package_id"], expected, flush=True
        )
        print("EXACT_SSM_STDIN_PACKAGE_OBSERVED", package["package_id"], flush=True)
        assert container["HostConfig"]["Memory"] == 6442450944
        assert json.loads(Path(target["data_source"]).joinpath("whitelist.json").read_text()) == []
        if package["loader"]["type"] == "neoforge":
            args = Path(target["data_source"]).joinpath("user_jvm_args.txt").read_text().split()
            assert "-Xms1G" in args and "-Xmx4G" in args
            for block in ("create:andesite_casing", "farmersdelight:stove"):
                response = registered_block(real_execute, container["Id"], block)
                print("HOST_REGISTERED_BLOCK", block, response.strip(), flush=True)
        if commit:
            game["materialization_state"] = "MATERIALIZED"
        print(
            "HOST_PACKAGE_READY", sequence, package["package_id"], target["data_source"], flush=True
        )
        return container

    try:
        vanilla, neo, worldgen = records
        interrupted = start(neo, commit=False)
        assert current is not None
        old_target = dict(current)
        old_game = json.dumps(neo, sort_keys=True)
        old_world = Path(current["data_source"]) / "world"
        world_inode = old_world.stat().st_ino
        real_execute(["docker", "exec", interrupted["Id"], "rcon-cli", "save-all", "flush"])
        execute(["systemctl", "stop", host.UNIT])
        assert json.loads((root / "receipt.json").read_text())["phase"] == "running"
        operation["status"] = "FAILED"
        saved_lease = dict(lease)
        lease.clear()
        initial_owner = game_package.GAMES / (neo["game_id"] + ".initial-owner.json")
        plan = {
            "schema_version": 1,
            "target": old_target,
            "container_id": interrupted["Id"],
            "original_started_at": interrupted["State"]["StartedAt"],
            "game_sha256": recovery.digest(neo),
            "world_directory_inode": world_inode,
            "prepared_owner_sha256": recovery.digest(
                {**json.loads(initial_owner.read_text()), "phase": "prepared"}
            ),
            "package_digest": game_package.digest(
                game_package.registered(neo, manifest, artifact_digest)
            ),
        }

        def recovery_gate() -> None:
            assert not lease and operation["status"] == "FAILED"
            assert json.dumps(neo, sort_keys=True) == old_game

        recovery.recover(host, plan, operator_gate=recovery_gate)
        recovery.recover(host, plan, operator_gate=recovery_gate)
        assert not host.inspect()
        assert json.loads((root / "receipt.json").read_text())["target"] == old_target
        assert old_world.stat().st_ino == world_inode and (old_world / "level.dat").is_file()
        assert json.dumps(neo, sort_keys=True) == old_game
        print("OLD_RUN_FRESH_PROOF_FINALIZED_WORLD_AND_UNMATERIALIZED_GAME_RETAINED", flush=True)
        lease.update(saved_lease)
        current = None
        assert json.loads(initial_owner.read_text())["phase"] == "initialized"
        cache_before = {
            p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in game_package.location(neo["game_id"]).rglob("*.jar")
        }
        resumed = start(neo, commit=False)
        assert resumed["Id"] != interrupted["Id"]
        assert json.dumps(neo, sort_keys=True) == old_game
        assert old_world.stat().st_ino == world_inode
        assert all(
            (p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in cache_before.items()
        )
        # The fixture only commits after the exact SSM protocol/package observation.
        neo["materialization_state"] = "MATERIALIZED"
        print("INITIALIZED_PREPARED_WORLD_REUSED_NEW_RUN_READY", flush=True)
        first = start(vanilla)
        real_execute(
            [
                "docker",
                "exec",
                first["Id"],
                "rcon-cli",
                "scoreboard",
                "objectives",
                "add",
                "preserved",
                "dummy",
            ]
        )
        start(neo)
        neo_server = game_package.GAMES / neo["game_id"] / "server"
        (neo_server / "defaultconfigs").mkdir(exist_ok=True)
        custom = neo_server / "defaultconfigs/wishicraft-ci.toml"
        custom.write_text("fixture = true\n")
        os.chown(custom, 993, 993)
        start(neo, reset=True)
        assert current is not None
        reset_server = Path(current["data_source"])
        assert (
            reset_server / "defaultconfigs/wishicraft-ci.toml"
        ).read_bytes() == custom.read_bytes()
        assert (neo_server / "world/level.dat").is_file()
        terrain = start(worldgen)
        worldgen_evidence(real_execute, terrain["Id"])
        assert set(
            p.name for p in (game_package.GAMES / worldgen["game_id"] / "server/mods").iterdir()
        ) == {m["filename"] for m in packages[2]["mods"]}
        final = start(vanilla)
        assert "preserved" in real_execute(
            ["docker", "exec", final["Id"], "rcon-cli", "scoreboard", "objectives", "list"]
        )
        assert not list((game_package.GAMES / vanilla["game_id"] / "server/mods").iterdir())
        assert not (
            game_package.GAMES / vanilla["game_id"] / "server/libraries/net/neoforged"
        ).exists()
        operation["operation_type"] = "STOP"
        host.apply(
            {
                "schema_version": 2,
                "operation_id": operation["operation_id"],
                "lease_id": "lease-ci",
                "action": "STOP",
            }
        )
        assert not host.inspect()
        print("HOST_NEOFORGE_START_SWITCH_RESET_WHITELIST_PASSED", flush=True)
    finally:
        for container in host.inspect():
            subprocess.run(["docker", "logs", container["Id"]], timeout=30)
            subprocess.run(["docker", "stop", "--time", "150", container["Id"]], timeout=180)
            subprocess.run(["docker", "rm", container["Id"]], timeout=30)


if __name__ == "__main__":
    main()
