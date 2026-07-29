"""The single per-stage CDK stack used during the initial delivery phases."""

from __future__ import annotations

from aws_cdk import Stack, Tags
from constructs import Construct

from wishicraft.config import ProjectConfig, StageConfig
from wishicraft.naming import resource_tags


class MinecraftStack(Stack):
    """Phase 0 stack shell; it intentionally declares no AWS resources yet."""

    def __init__(
        self, scope: Construct, construct_id: str, *, project: ProjectConfig, stage: StageConfig
    ) -> None:
        super().__init__(scope, construct_id)
        raw_tags = project.values["resource_tags"]
        assert isinstance(raw_tags, dict)
        project_tags = {key: value for key, value in raw_tags.items() if isinstance(value, str)}
        tags = resource_tags(project_tags, stage.stage)
        for key, value in tags.items():
            Tags.of(self).add(key, value)
