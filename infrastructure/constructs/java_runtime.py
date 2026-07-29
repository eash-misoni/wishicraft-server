"""Allowlisted Java runtime packages for the initial Amazon Linux host."""

from __future__ import annotations

from typing import Final

JAVA_RUNTIME_PACKAGES: Final = {
    "corretto-25-headless": "java-25-amazon-corretto-headless",
}


def resolve_java_package(java_runtime: str) -> str:
    """Resolve one supported logical runtime without accepting arbitrary package names."""
    try:
        return JAVA_RUNTIME_PACKAGES[java_runtime]
    except KeyError as error:
        raise ValueError(f"Unsupported Phase 1 Java runtime: {java_runtime}") from error
