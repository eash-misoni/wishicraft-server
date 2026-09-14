"""Deploy-time budgets for the single shared Minecraft container."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wishicraft.config import ConfigValidationError, StageConfig

# Nominal EC2 RAM, not guest MemTotal. Guest/kernel reservations are checked at release.
HOST_MEMORY_MIB = {"t3a.medium": 4096, "m8a.large": 8192, "r8a.large": 16384, "m8a.xlarge": 16384}


@dataclass(frozen=True)
class MemoryBudget:
    initial_mib: int
    maximum_mib: int
    container_mib: int
    host_mib: int


def memory_mib(value: object, *, jvm: bool = False) -> int:
    units = "M|G" if jvm else "MiB|GiB|M|G"
    match = re.fullmatch(r"([1-9][0-9]*)(" + units + ")", value) if isinstance(value, str) else None
    if match is None:
        raise ConfigValidationError(["host_runtime.memory requires positive integer " + units])
    return int(match[1]) * (1024 if match[2] in {"G", "GiB"} else 1)


def validate_memory(stage: StageConfig) -> MemoryBudget:
    """Reject unsafe explicit values; never infer missing capacity or auto-tune it."""
    initial = memory_mib(stage.host_runtime_value("memory.jvm_initial"), jvm=True)
    maximum = memory_mib(stage.host_runtime_value("memory.jvm_maximum"), jvm=True)
    container = memory_mib(stage.host_runtime_value("memory.container_limit"))
    host = HOST_MEMORY_MIB[stage.target_instance_type]
    errors = []
    if not 512 <= initial <= maximum or maximum < 1024:
        errors.append("host_runtime.memory requires 512MiB <= Xms <= Xmx and Xmx >= 1GiB")
    # Retain D-061's 768 MiB allowance on 4 GiB hosts; scale for larger heaps.
    if container - maximum < max(768, (maximum + 3) // 4):
        errors.append("container memory must exceed JVM maximum heap by >= max(768MiB, 25%)")
    reserve = 1024 if host == 4096 else 2048
    if container > host - reserve:
        errors.append(f"host_runtime.memory must leave at least {reserve}MiB nominal host RAM")
    if errors:
        raise ConfigValidationError(errors)
    return MemoryBudget(initial, maximum, container, host)
