"""Server-owned two-stage release configuration. Never reads operator event overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RetentionRelease:
    provision: bool = False
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.provision) is not bool or type(self.enabled) is not bool:
            raise ValueError("RETENTION_FLAGS_MUST_BE_BOOLEAN")
        if self.enabled and not self.provision:
            raise ValueError("RETENTION_ENABLED_REQUIRES_PROVISION")

    @classmethod
    def parse(cls, value: Any) -> RetentionRelease:
        if not isinstance(value, dict) or set(value) != {"schema_version", "provision", "enabled"}:
            raise ValueError("INVALID_RETENTION_RELEASE_CONFIG")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("INVALID_RETENTION_RELEASE_SCHEMA")
        return cls(value["provision"], value["enabled"])


def load_retention_release(root: Path, stage: str) -> RetentionRelease:
    if not stage.isalnum():
        raise ValueError("INVALID_STAGE")
    path = root / "config" / f"retention-execution-{stage}.json"
    return (
        RetentionRelease.parse(json.loads(path.read_text()))
        if path.exists()
        else RetentionRelease()
    )
