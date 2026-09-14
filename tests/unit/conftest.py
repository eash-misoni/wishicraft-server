"""Historical migration fixtures independent of today's deployment capacity."""

import subprocess
from pathlib import Path

import pytest

from wishicraft.runtime_migration import BASELINE


@pytest.fixture
def historical_migration_root(tmp_path: Path) -> Path:
    """Keep the migration's exact configuration guard active against its own baseline."""
    repository = Path(__file__).resolve().parents[2]
    root = tmp_path / "historical-migration"
    root.mkdir()
    for name in (".git", "src", "infrastructure"):
        (root / name).symlink_to(repository / name, target_is_directory=True)
    for name in ("project.yaml", "stages/dev.yaml", "secrets.example.yaml"):
        target = root / "config" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            subprocess.check_output(["git", "show", f"{BASELINE}:config/{name}"], cwd=repository)
        )
    return root
