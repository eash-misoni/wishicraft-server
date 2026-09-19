"""Production-shape Compose interpolation for stopped package-aware migration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from wishicraft.artifacts import game_package
from wishicraft.config import load_configuration
from wishicraft.host_runtime import render_boot_time_artifacts


def compose(path: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--file", str(path), "config", "--quiet"],
        capture_output=True,
        text=True,
        env={**os.environ, **environment},
        check=False,
    )


def main() -> None:
    if os.environ.get("CI") != "true" or sys.platform != "linux":
        raise RuntimeError("Linux CI only")
    root = Path(__file__).resolve().parents[2]
    cfg = load_configuration(root, "dev")
    rendered = render_boot_time_artifacts(
        cfg.project,
        cfg.stage,
        observed_uid=993,
        observed_gid=993,
        targeted=True,
        enable_rcon=True,
        rcon_parameter_name=cfg.secrets.rcon_password_parameter_name("dev"),
        games=tuple(json.loads((root / "config/two-game-dev.json").read_text())),
        reset_policies=json.loads((root / "config/reset-dev.json").read_text()),
        packages=game_package.load(),
    )
    temporary = Path(tempfile.mkdtemp(prefix="wishicraft-package-migration-compose-"))
    definition = temporary / "compose.yaml"
    definition.write_text(rendered.compose_yaml)
    (temporary / "runtime.env").write_text(rendered.runtime_env)
    base = dict(
        line.split("=", 1)
        for line in rendered.runtime_env.splitlines()
        if line and not line.startswith("#")
    )
    base.update(
        {
            "WISHICRAFT_RUN_ID": "op-package-compose",
            "WISHICRAFT_GAME_ID": "game-package-compose",
            "GAME_DIRECTORY": str(temporary / "server"),
        }
    )
    for package in game_package.load():
        environment = {**base, **game_package.projection("game-package-compose", package)}
        result = compose(definition, environment)
        assert result.returncode == 0, result.stderr
        print("PACKAGE_COMPOSE_VALID", package["loader"]["type"], flush=True)
    missing = {**base, **game_package.projection("game-package-compose", game_package.load()[1])}
    missing.pop("WISHICRAFT_PACKAGE_NEOFORGE_VERSION")
    result = compose(definition, missing)
    assert result.returncode != 0 and "verified package required" in result.stderr
    print("PACKAGE_COMPOSE_MISSING_ENV_REJECTED", flush=True)


if __name__ == "__main__":
    main()
