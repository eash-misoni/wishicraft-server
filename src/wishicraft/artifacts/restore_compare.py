"""Supplemental stopped-world comparison, not a RESTORE validator or writer."""

from __future__ import annotations

import gzip
import hashlib
import io
import math
import struct
from pathlib import Path
from typing import Any

from wishicraft.artifacts import restore_reader as reader

NBT_LIMIT = 16 * 1024 * 1024
MAX_CHANGES = 128


def typed_nbt(data: bytes) -> Any:
    """Keep tag types and exact numbers. Arrays remain typed, opaque bytes."""
    stream = io.BytesIO(data)
    nodes = 0

    def take(size: int) -> bytes:
        if not 0 <= size <= NBT_LIMIT:
            raise ValueError("COMPARE_NBT_LENGTH")
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("COMPARE_NBT_TRUNCATED")
        return value

    def number(fmt: str) -> Any:
        return struct.unpack(">" + fmt, take(struct.calcsize(">" + fmt)))[0]

    def string() -> str:
        return take(number("H")).decode("utf-8", errors="surrogatepass")

    def payload(tag: int, depth: int = 0) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > 64 or nodes > 500_000:
            raise ValueError("COMPARE_NBT_COMPLEXITY")
        if 1 <= tag <= 6:
            value = number({1: "b", 2: "h", 3: "i", 4: "q", 5: "f", 6: "d"}[tag])
            if tag >= 5 and not math.isfinite(value):
                raise ValueError("COMPARE_NBT_NONFINITE")
            return [tag, str(value) if tag <= 4 else value.hex()]
        if tag == 8:
            return [tag, string()]
        if tag in (7, 11, 12):
            count = number("i")
            raw = take(count * {7: 1, 11: 4, 12: 8}[tag])
            return [tag, {"count": count, "opaque_sha256": hashlib.sha256(raw).hexdigest()}]
        if tag == 9:
            child, count = number("B"), number("i")
            if not 0 <= count <= 500_000 or child not in range(13) or (child == 0 and count):
                raise ValueError("COMPARE_NBT_LIST")
            return [tag, child, [payload(child, depth + 1) for _ in range(count)]]
        if tag == 10:
            result = {}
            while child := number("B"):
                name = string()
                if name in result:
                    raise ValueError("COMPARE_NBT_DUPLICATE")
                result[name] = payload(child, depth + 1)
            return [tag, result]
        raise ValueError("COMPARE_NBT_TAG")

    if len(data) > NBT_LIMIT or number("B") != 10:
        raise ValueError("COMPARE_NBT_ROOT")
    name = string()
    result = payload(10)
    if stream.read(1):
        raise ValueError("COMPARE_NBT_TRAILING")
    return {"root_name": name, "root": result}


def stable(path: Path) -> dict[str, Any]:
    value = reader.fingerprint(path)
    if value["state"] != "read":
        raise ValueError("COMPARE_UNSTABLE")
    return value


def manifest(root: Path) -> dict[str, Any]:
    return {str(p.relative_to(root)): stable(p) for p in reader.bounded_files(root)}


def aggregate(records: dict[str, Any]) -> dict[str, Any]:
    """The existing file_group JSON/hash encoding, reconstructed from entries."""
    if any(r["state"] != "read" for r in records.values()):
        raise ValueError("COMPARE_UNSTABLE")
    return {
        "count": len(records),
        "state": "read",
        "sha256": reader.summary_hash(records),
        "names_sha256": reader.summary_hash(sorted(records)),
    }


def is_metadata(name: str) -> bool:
    p = Path(name)
    return p.suffix == ".dat" and p.parent.name == "minecraft" and p.parent.parent.name == "data"


def document(path: Path) -> dict[str, Any]:
    before = stable(path)
    if before["size"] > NBT_LIMIT:
        raise ValueError("COMPARE_NBT_SIZE")
    with gzip.open(path, "rb") as compressed:
        raw = compressed.read(NBT_LIMIT + 1)
    if len(raw) > NBT_LIMIT:
        raise ValueError("COMPARE_NBT_SIZE")
    value = typed_nbt(raw)
    if before != stable(path):
        raise ValueError("COMPARE_UNSTABLE")
    return {
        "fingerprint": before,
        "expanded_sha256": hashlib.sha256(raw).hexdigest(),
        "typed": value,
    }


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"added": {}, "deleted": {}, "changed": {}, "unchanged": 0}
    for name in sorted(before.keys() | after.keys()):
        if name not in before:
            result["added"][name] = after[name]
        elif name not in after:
            result["deleted"][name] = before[name]
        elif before[name] != after[name]:
            result["changed"][name] = {"before": before[name], "after": after[name]}
        else:
            result["unchanged"] += 1
    if sum(len(result[k]) for k in ("added", "deleted", "changed")) > MAX_CHANGES:
        raise ValueError("COMPARE_CHANGE_LIMIT")
    return result


def compare_documents(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if before["fingerprint"] == after["fingerprint"]:
        return {"classification": "identical_bytes"}
    if before["expanded_sha256"] == after["expanded_sha256"]:
        return {"classification": "compression_representation"}
    if before["typed"] == after["typed"]:
        return {"classification": "nbt_representation", "typed_equal": True}
    # Typed values are preserved in the private snapshot. This is a fact about
    # change, never an automatic normal-save judgment or an array interpretation.
    return {"classification": "typed_values_changed", "requires_explanation": True}


def typed_changes(before: Any, after: Any) -> list[dict[str, Any]]:
    """Private evidence only: exact changed fields, without semantic exclusions."""
    result: list[dict[str, Any]] = []

    def visit(left: Any, right: Any, path: list[Any]) -> None:
        if left == right:
            return
        if len(result) >= MAX_CHANGES:
            raise ValueError("COMPARE_CHANGE_LIMIT")
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                if key not in left or key not in right:
                    result.append(
                        {"path": path + [key], "before": left.get(key), "after": right.get(key)}
                    )
                else:
                    visit(left[key], right[key], path + [key])
        elif (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right) == 2
            and left[0] == right[0] == 10
        ):
            visit(left[1], right[1], path)
        else:
            result.append({"path": path, "before": left, "after": right})

    visit(before, after, [])
    if len(result) > MAX_CHANGES:
        raise ValueError("COMPARE_CHANGE_LIMIT")
    return result


def snapshot(world: Path) -> dict[str, Any]:
    """Freeze metadata and level.dat separately; never parse player save groups."""
    before = manifest(world)
    selected = {name: value for name, value in before.items() if is_metadata(name)}
    docs = {name: document(world / name) for name in selected}
    level = document(world / "level.dat")
    level_old = (
        document(world / "level.dat_old") if "level.dat_old" in before else {"state": "missing"}
    )
    if before != manifest(world):
        raise ValueError("COMPARE_UNSTABLE")
    return {
        "world_path": str(world),
        "world_files": aggregate(before),
        "metadata_group": aggregate(selected),
        "metadata_manifest": selected,
        "metadata_documents": docs,
        "level_dat": level,
        "level_dat_old": level_old,
        "stable": True,
    }


def compare_worlds(before: Path, after: Path) -> dict[str, Any]:
    left, right = manifest(before), manifest(after)
    result = changes(left, right)
    if left != manifest(before) or right != manifest(after):
        raise ValueError("COMPARE_UNSTABLE")
    return {
        "before_path": str(before),
        "after_path": str(after),
        "before_files": aggregate(left),
        "after_files": aggregate(right),
        "difference": result,
        "stable": True,
    }


def paper_overrides(before: Path, after: Path) -> dict[str, Any]:
    """Separate, fixed Paper saved-data selection; never widen the Minecraft group."""
    result = []
    names = [
        f"dimensions/minecraft/{dimension}/data/paper/level_overrides.dat"
        for dimension in ("overworld", "the_nether", "the_end")
    ]
    for world in (before, after):
        files = reader.bounded_files(world)
        if any(world / name not in files for name in names):
            raise ValueError("COMPARE_PAPER_OVERRIDE_MISSING")
        docs = {name: document(world / name) for name in names}
        for name, doc in docs.items():
            if stable(world / name) != doc["fingerprint"]:
                raise ValueError("COMPARE_UNSTABLE")
        result.append({"world_path": str(world), "documents": docs, "stable": True})
    return {"paper_overrides": result}
