"""Naming helpers for stage-isolated AWS resources."""

from __future__ import annotations

from collections.abc import Mapping


def resource_name(resource_prefix: str, stage: str, component: str) -> str:
    """Return the canonical wc-<stage>-<component> resource name."""
    _validate_name_part(resource_prefix, "resource_prefix")
    _validate_name_part(stage, "stage")
    _validate_name_part(component, "component")
    return f"{resource_prefix}-{stage}-{component}"


def resource_tags(project_tags: Mapping[str, str], stage: str) -> dict[str, str]:
    """Return required project tags plus the stage tag."""
    _validate_name_part(stage, "stage")
    required_tags = {"Project", "ManagedBy", "Owner"}
    missing = required_tags - project_tags.keys()
    if missing:
        raise ValueError(f"project tags are missing: {', '.join(sorted(missing))}")
    return {**project_tags, "Stage": stage}


def _validate_name_part(value: str, field_name: str) -> None:
    if (
        not value
        or not value.replace("-", "").isalnum()
        or value.startswith("-")
        or value.endswith("-")
    ):
        raise ValueError(f"{field_name} must contain only alphanumeric characters and hyphens")
