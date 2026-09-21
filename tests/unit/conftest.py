"""Historical migration fixtures independent of today's deployment capacity."""

import json
import subprocess
from pathlib import Path

import pytest

from wishicraft.runtime_migration import BASELINE


@pytest.fixture
def historical_migration_root(tmp_path: Path) -> Path:
    """Keep the migration's exact configuration guard active against its own baseline."""
    return configuration_at(tmp_path, BASELINE)


@pytest.fixture
def historical_catalog_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run old same-digest migration tests against their original full checkout."""
    from wishicraft import game_package_migration, heartbeat_game_migration

    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "catalog-predecessor"
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(repository), str(root)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "checkout", "--quiet", "--detach", "866f6ca"], check=True
    )
    document = (root / "src/wishicraft/artifacts/game-packages.json").read_text()
    monkeypatch.setattr(game_package_migration, "load", lambda: json.loads(document)["packages"])
    monkeypatch.setattr(
        heartbeat_game_migration, "load_packages", lambda: json.loads(document)["packages"]
    )
    return root


def configuration_at(tmp_path: Path, baseline: str) -> Path:
    """Historical artifacts retain their original configuration and exact byte checks."""
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "historical-migration"
    root.mkdir()
    for name in (".git", "src", "infrastructure", "docs"):
        (root / name).symlink_to(repository / name, target_is_directory=True)
    for name in ("project.yaml", "stages/dev.yaml", "secrets.example.yaml"):
        target = root / "config" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            subprocess.check_output(["git", "show", f"{baseline}:config/{name}"], cwd=repository)
        )
    return root
