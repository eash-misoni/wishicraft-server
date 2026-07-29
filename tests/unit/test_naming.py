from __future__ import annotations

import pytest

from wishicraft.naming import resource_name, resource_tags


def test_resource_name_and_tags_are_stage_scoped() -> None:
    assert resource_name("wc", "dev", "minecraft") == "wc-dev-minecraft"
    assert resource_tags(
        {"Project": "wishicraft", "ManagedBy": "cdk", "Owner": "project-owner"}, "dev"
    ) == {
        "Project": "wishicraft",
        "ManagedBy": "cdk",
        "Owner": "project-owner",
        "Stage": "dev",
    }


def test_resource_name_rejects_unsafe_parts() -> None:
    with pytest.raises(ValueError, match="component"):
        resource_name("wc", "dev", "minecraft/control")
