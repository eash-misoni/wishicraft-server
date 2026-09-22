"""Same-build Paper save/archive/prepared-world/restart on an isolated CI runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import initial_game, reset_worlds
from wishicraft.artifacts import world_import as imp
from wishicraft.artifacts.targeted_runtime import atomic, validate_persistence


def command(*args: str, timeout: int = 120) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def main() -> None:
    if os.environ.get("CI") != "true" or sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("isolated root Linux CI only")
    root = Path(tempfile.mkdtemp(prefix="wishicraft-paper-import-"))
    root.chmod(0o755)
    print("EVIDENCE_ROOT", root, flush=True)
    repo = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((repo / "config/stages/dev.yaml").read_text())["host_runtime"]
    image = cfg["image"]["reference"]
    package = packages.load()[-1]
    assert package["loader"]["type"] == "paper"
    spec = package["loader"]["server"]
    cache = root / "source-cache"
    cache.mkdir(mode=0o755)
    (cache / spec["filename"]).write_bytes(packages.fetch(spec))
    (cache / spec["filename"]).chmod(0o444)
    command("docker", "pull", image, timeout=300)
    source = root / "source"
    source.mkdir(mode=0o755)
    os.chown(source, 993, 993)
    props = {
        "difficulty": "easy",
        "gamemode": "survival",
        "hardcore": "false",
        "generate-structures": "true",
        "level-seed": "-123",
        "level-type": "minecraft\\:normal",
        "generator-settings": "{}",
        "view-distance": "3",
        "simulation-distance": "3",
    }
    (source / "server.properties").write_text(imp.properties({"properties": props}))
    os.chown(source / "server.properties", 993, 993)
    name = root.name
    cycle = 0
    source_java = ""

    def start(data: Path, package_cache: Path) -> dict[str, object]:
        nonlocal cycle
        cycle += 1
        environment = {
            **packages.environment(package),
            "EULA": "TRUE",
            "UID": "993",
            "GID": "993",
            "SKIP_CHOWN_DATA": "true",
            "INIT_MEMORY": "1G",
            "MAX_MEMORY": "4G",
            "ENABLE_RCON": "true",
            "RCON_PASSWORD": "synthetic-ci-only",
            "STOP_DURATION": "120",
        }
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--memory",
            "6g",
            "--mount",
            f"type=bind,source={data},target=/data",
            "--mount",
            f"type=bind,source={package_cache},target=/wishicraft-package,readonly",
        ]
        for k, v in environment.items():
            args.extend(["-e", k + "=" + v])
        command(*args, image)
        for _ in range(120):
            info = json.loads(command("docker", "inspect", name))[0]
            if not info["State"]["Running"]:
                raise RuntimeError("Paper exited before READY")
            logs = command("docker", "logs", name)
            if "Done (" in logs:
                assert "26.1.2" in logs
                (root / f"cycle-{cycle}-ready.log").write_text(logs)
                print("READY", cycle, flush=True)
                return info
            time.sleep(5)
        raise RuntimeError("Paper READY timeout")

    def rcon(*args: str) -> str:
        return command("docker", "exec", name, "rcon-cli", *args)

    def stop() -> None:
        saved = rcon("save-all", "flush")
        assert "Saved the game" in saved, saved
        command("docker", "stop", "--time", "150", name, timeout=180)
        info = json.loads(command("docker", "inspect", name))[0]
        assert info["State"]["ExitCode"] == 0 and not info["State"]["OOMKilled"]
        (root / f"cycle-{cycle}-stopped.log").write_text(command("docker", "logs", name))
        command("docker", "rm", name)
        os.sync()
        print("SAVED_STOPPED", cycle, flush=True)

    try:
        start(source, cache)
        # java -version is on stderr; obtain only the non-secret JVM version property.
        measured = subprocess.run(
            ["docker", "exec", name, "java", "-XshowSettings:properties", "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
        source_java = next(
            line.split("=", 1)[1].strip()
            for line in measured.stderr.splitlines()
            if line.strip().startswith("java.version =")
        )
        for dimension in ["overworld", "the_nether", "the_end"]:
            response = rcon(
                "execute", "in", "minecraft:" + dimension, "run", "forceload", "add", "0", "0"
            )
            print("DIMENSION", dimension, response.strip(), flush=True)
            for _ in range(30):
                response = rcon(
                    "execute",
                    "in",
                    "minecraft:" + dimension,
                    "run",
                    "setblock",
                    "0",
                    "100",
                    "0",
                    "minecraft:diamond_block",
                )
                if "Changed the block" in response:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("dimension chunk not loaded")
        print("DATAPACKS", rcon("datapack", "list", "enabled"), flush=True)
        stop()
        archive = root / "source.tar"
        selected = root / "selected"
        selected.mkdir()
        import shutil

        for name_in_archive in [imp.LEVEL, *sorted(imp.CONFIGS)]:
            src = source / name_in_archive
            dst = selected / name_in_archive
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copyfile(src, dst)
        with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as tar:
            for path in sorted(selected.iterdir()):
                tar.add(path, arcname=path.name)
        archive.chmod(0o444)
        manifest = {
            "schema_version": 1,
            "source": {
                "server_type": "paper",
                "minecraft_version": "26.1.2",
                "paper_build": 53,
                "paper_commit": package["loader"]["commit"],
                "jar_sha256": spec["sha256"],
                "java_version": source_java,
                "data_version": 4790,
                "level_name": imp.LEVEL,
                "online_mode": True,
                "seed": -123,
            },
            "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_stopped": True,
            "save_confirmed": True,
            "filesystem_synced": True,
            "archive_size": archive.stat().st_size,
            "archive_sha256": imp.sha(archive),
            **imp.tree(selected),
            "configs": {p: imp.sha(selected / p) for p in imp.CONFIGS},
            "properties": props,
            "target_package_digest": packages.digest(package),
        }
        packages.GAMES = root / "games"
        packages.GAMES.mkdir(mode=0o755)
        reset_worlds.GAMES = packages.GAMES
        imp.STAGING = root / "imports"
        imp.STAGING.mkdir(mode=0o755)
        staged = imp.STAGING / manifest["archive_sha256"]
        staged.mkdir(mode=0o755)
        shutil.copyfile(archive, staged / "source.tar")
        (staged / "source.tar").chmod(0o444)
        identity = "game-" + "a" * 64
        target = {
            "game_id": identity,
            "data_source": str(packages.GAMES / identity / "server"),
            "config_digest": "b" * 64,
        }
        game = {
            "game_id": identity,
            "world": {"generation": 1, "seed": -123},
            "materialization_state": "UNMATERIALIZED",
            "package": {"definition": package},
            "creation": {
                "operation_id": "op-" + "a" * 64,
                "config_digest": "b" * 64,
                "package_digest": packages.digest(package),
                "reset_policy": None,
                "import": manifest,
            },
        }
        initial_game.prepare(game, {}, target, atomic, verify=lambda: None)
        data = Path(target["data_source"])
        assert imp.tree(data / imp.LEVEL) == imp.tree(source / imp.LEVEL)
        packages.materialize_mods(target, package, atomic)
        print("PREPARED_GENERATION_1_TREE_IDENTICAL", flush=True)
        for _ in range(2):
            initial_game.prepare(game, {}, target, atomic, verify=lambda: None)
            info = start(data, packages.location(identity))
            validate_persistence(info, target)
            for dimension in ["overworld", "the_nether", "the_end"]:
                response = rcon(
                    "execute",
                    "in",
                    "minecraft:" + dimension,
                    "if",
                    "block",
                    "0",
                    "100",
                    "0",
                    "minecraft:diamond_block",
                    "run",
                    "say",
                    "import-preserved",
                )
                assert "import-preserved" in response, response
            assert initial_game.initialized(target, atomic)
            stop()
        assert imp.sha(archive) == manifest["archive_sha256"]
        (root / "result.json").write_text(
            json.dumps(
                {"status": "passed", "manifest": manifest, "cycles": cycle, "generation": 1},
                indent=2,
            )
        )
        print("PAPER_IMPORT_PASSED", flush=True)
    finally:
        # Disposable CI container only; production worlds are never used by this test.
        subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)


if __name__ == "__main__":
    main()
