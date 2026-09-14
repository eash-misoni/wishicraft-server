"""Pinned NeoForge candidate qualification on an isolated Linux Docker CI runner."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml


def command(*args: str, timeout: int = 60) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout).stdout


def main() -> None:
    if os.environ.get("CI") != "true" or sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("isolated root Linux CI only")
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="wishicraft-neoforge-docker-"))
    print("FIXTURE", root, flush=True)
    root.chmod(0o755)
    package = json.loads((repo / "config/game-packages.json").read_text())["packages"][1]
    stage = yaml.safe_load((repo / "config/stages/dev.yaml").read_text())["host_runtime"]
    image = stage["image"]["reference"]
    command("docker", "pull", image, timeout=300)
    data, cache = root / "server", root / "cache"
    data.mkdir(mode=0o755)
    os.chown(data, 993, 993)
    cache.mkdir(mode=0o755)
    mods = data / "mods"
    mods.mkdir(mode=0o755)
    files = [*package["mods"], package["loader"]["installer"]]
    for artifact in files:
        request = urllib.request.Request(
            artifact["url"], headers={"User-Agent": "Wishicraft/pinned-runtime-integration"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read(artifact["size"] + 1)
        assert len(content) == artifact["size"]
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
        path = (mods if artifact in package["mods"] else cache) / artifact["filename"]
        path.write_bytes(content)
        path.chmod(0o444)
        print("ARTIFACT", artifact["filename"], artifact["sha256"], flush=True)
    (data / "server.properties").write_text(
        "online-mode=true\nwhite-list=true\nenforce-whitelist=true\n"
        "level-name=world\nview-distance=3\nsimulation-distance=3\n"
    )
    (data / "whitelist.json").write_text("[]\n")
    for path in (data / "server.properties", data / "whitelist.json"):
        os.chown(path, 993, 993)
        path.chmod(0o640)
    name = root.name
    environment = {
        "EULA": "TRUE",
        "TYPE": "NEOFORGE",
        "VERSION": package["minecraft_version"],
        "NEOFORGE_VERSION": package["loader"]["version"],
        "NEOFORGE_INSTALLER": "/pinned/" + package["loader"]["installer"]["filename"],
        "NEOFORGE_FORCE_REINSTALL": "true",
        "UID": "993",
        "GID": "993",
        "INIT_MEMORY": stage["memory"]["jvm_initial"],
        "MAX_MEMORY": stage["memory"]["jvm_maximum"],
        "ENABLE_RCON": "true",
        "RCON_PASSWORD": "synthetic-ci-only",
        "SKIP_CHOWN_DATA": "true",
        "STOP_DURATION": "120",
    }
    try:
        for cycle in range(2):
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
                f"type=bind,source={cache},target=/pinned,readonly",
            ]
            for key, value in environment.items():
                args.extend(["-e", key + "=" + value])
            command(*args, image)
            for _ in range(120):
                info = json.loads(command("docker", "inspect", name))[0]
                assert info["State"]["Running"], "candidate container exited"
                result = subprocess.run(["docker", "exec", name, "mc-health"], capture_output=True)
                if result.returncode == 0:
                    break
                time.sleep(5)
            else:
                raise AssertionError("candidate not READY")
            assert "0 of a max" in command("docker", "exec", name, "rcon-cli", "list")
            top = command("docker", "top", name, "-eo", "pid,args")
            assert "-Xmx4G" in top and "-Xms1G" in top
            assert info["HostConfig"]["Memory"] == 6442450944
            logs = command("docker", "logs", name)
            (root / f"cycle-{cycle}.log").write_text(logs)
            for mod in package["mods"]:
                assert mod["mod_id"] in logs.lower()
                assert (
                    hashlib.sha256((mods / mod["filename"]).read_bytes()).hexdigest()
                    == mod["sha256"]
                )
            print("NEOFORGE_READY", cycle, package["loader"]["version"], flush=True)
            print(command("docker", "exec", name, "rcon-cli", "save-all", "flush"), flush=True)
            command("docker", "stop", "--time", "150", name, timeout=180)
            info = json.loads(command("docker", "inspect", name))[0]
            assert not info["State"]["OOMKilled"] and info["State"]["ExitCode"] == 0
            assert (data / "world/level.dat").is_file()
            command("docker", "rm", name)
        print("NEOFORGE_CANDIDATE_PASSED", flush=True)
    finally:
        result = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        (root / "final-container.log").write_text(result.stdout + result.stderr)
        if result.returncode == 0:
            print((result.stdout + result.stderr)[-18000:], flush=True)
        subprocess.run(["docker", "stop", "--time", "150", name], capture_output=True, timeout=180)
        subprocess.run(["docker", "rm", name], capture_output=True)


if __name__ == "__main__":
    main()
