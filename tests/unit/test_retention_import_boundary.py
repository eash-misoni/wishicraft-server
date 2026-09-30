"""Source-level compatibility, separate from mandatory Linux artifact qualification."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from wishicraft.dynamodb_read import item
from wishicraft.maintenance_operator import item as cli_item
from wishicraft.retention_release import environment_release


def test_shared_item_preserves_wire_semantics_and_cli_export() -> None:
    assert cli_item is item

    class Api:
        def get_item(self, **kw: Any) -> dict[str, Any]:
            assert kw == dict(TableName="table", Key={"key": {"S": "value"}}, ConsistentRead=True)
            return {"Item": {"count": {"N": "120"}}}

    assert item(Api(), "table", "key", "value") == {"count": Decimal(120)}
    assert type(item(Api(), "table", "key", "value")["count"]) is Decimal


@pytest.mark.parametrize(
    "provision,enabled,valid",
    [("0", "0", True), ("1", "0", True), ("1", "1", True), ("0", "1", False), ("true", "0", False)],
)
def test_light_release_flags(monkeypatch: Any, provision: str, enabled: str, valid: bool) -> None:
    monkeypatch.setenv("RETENTION_PROVISIONED", provision)
    monkeypatch.setenv("RETENTION_DELETE_ENABLED", enabled)
    if valid:
        assert environment_release().enabled == (enabled == "1")
    else:
        with pytest.raises(ValueError):
            environment_release()


def test_runtime_imports_never_load_operator_or_yaml() -> None:
    root = Path(__file__).resolve().parents[2]
    script = """
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname in {'wishicraft.maintenance_operator','wishicraft.config','yaml','aws_cdk'}:
   raise AssertionError('UNEXPECTED_CLI_DEPENDENCY')
sys.meta_path.insert(0,Block())
import wishicraft.retention_runtime
import wishicraft.retention_deletion_repository
import wishicraft.retention_recovery_reads
"""
    subprocess.run([sys.executable, "-c", script], cwd=root, check=True)
