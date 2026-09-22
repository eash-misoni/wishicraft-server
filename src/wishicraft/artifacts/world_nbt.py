"""Bounded, read-only Java NBT inspection; never serialize or upgrade world data."""

from __future__ import annotations

import gzip
import io
import struct
from pathlib import Path
from typing import Any

LIMIT = 16 * 1024 * 1024


def read(path: Path) -> dict[str, Any]:
    if path.stat().st_size > LIMIT:
        raise ValueError("NBT_SIZE")
    with gzip.open(path, "rb") as compressed:
        data = compressed.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("NBT_SIZE")
    stream = io.BytesIO(data)
    nodes = 0

    def take(size: int) -> bytes:
        if size < 0 or size > LIMIT:
            raise ValueError("NBT_LENGTH")
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("NBT_TRUNCATED")
        return value

    def number(fmt: str) -> Any:
        return struct.unpack(">" + fmt, take(struct.calcsize(">" + fmt)))[0]

    def string() -> str:
        return take(number("H")).decode("utf-8", errors="surrogatepass")

    def payload(tag: int, depth: int = 0) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > 64 or nodes > 500_000:
            raise ValueError("NBT_COMPLEXITY")
        if 1 <= tag <= 6:
            return number({1: "b", 2: "h", 3: "i", 4: "q", 5: "f", 6: "d"}[tag])
        if tag == 8:
            return string()
        if tag in (7, 11, 12):
            count = number("i")
            return take(count * {7: 1, 11: 4, 12: 8}[tag])
        if tag == 9:
            child, count = number("B"), number("i")
            if not 0 <= count <= 500_000:
                raise ValueError("NBT_LENGTH")
            return [payload(child, depth + 1) for _ in range(count)]
        if tag == 10:
            result = {}
            while child := number("B"):
                name = string()
                if name in result:
                    raise ValueError("NBT_DUPLICATE")
                result[name] = payload(child, depth + 1)
            return result
        raise ValueError("NBT_TAG")

    if number("B") != 10:
        raise ValueError("NBT_ROOT")
    string()
    result = payload(10)
    if stream.read(1) or not isinstance(result, dict):
        raise ValueError("NBT_TRAILING")
    return result
