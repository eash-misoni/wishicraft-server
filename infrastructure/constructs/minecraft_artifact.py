"""Explicitly supported Minecraft server artifact metadata."""

from __future__ import annotations

from dataclasses import dataclass

from wishicraft.config import StageConfig


@dataclass(frozen=True)
class MinecraftArtifact:
    """One immutable, verified vanilla server artifact."""

    version: str
    url: str
    sha1: str
    sha256: str
    size: int


_CATALOG = {
    "26.2": MinecraftArtifact(
        version="26.2",
        url="https://piston-data.mojang.com/v1/objects/823e2250d24b3ddac457a60c92a6a941943fcd6a/server.jar",
        sha1="823e2250d24b3ddac457a60c92a6a941943fcd6a",
        sha256="cdacdfb25898de5e4b4b0e5ddcc2722f77067e46605709c2d886c000ebb63ec5",
        size=60894273,
    )
}


def resolve_minecraft_artifact(stage: StageConfig) -> MinecraftArtifact:
    """Resolve a stage's supported version only when its lock data exactly matches."""
    artifact = _CATALOG.get(stage.minecraft_version)
    if artifact is None:
        raise ValueError(f"Unsupported Minecraft version: {stage.minecraft_version}")
    if (
        stage.minecraft_server_jar_url,
        stage.minecraft_server_jar_sha1,
        stage.minecraft_server_jar_sha256,
        stage.minecraft_server_jar_size,
    ) != (artifact.url, artifact.sha1, artifact.sha256, artifact.size):
        raise ValueError("Minecraft artifact configuration does not match the supported catalog")
    return artifact
