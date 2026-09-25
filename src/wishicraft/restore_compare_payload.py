"""Fixed, bounded read-only Paper comparison payload; no host installation."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import lzma
import shlex
import zlib
from pathlib import Path
from typing import Any

from wishicraft.world_reference import validate_source


def decode_parts(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts or len(parts) not in (1, 3):
        raise ValueError("COMPARE_PARTS")
    for i, part in enumerate(parts):
        if (
            part.get("part") != i
            or part.get("parts") != len(parts)
            or part.get("encoding") != "xz-base64-json"
            or part.get("sha256") != parts[0].get("sha256")
            or part.get("bytes") != parts[0].get("bytes")
            or len(part.get("private_evidence", "")) > 18000
        ):
            raise ValueError("COMPARE_PART_IDENTITY")
    packed = base64.b64decode("".join(p["private_evidence"] for p in parts), validate=True)
    decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
    raw = decoder.decompress(packed, max_length=1048577)
    if (
        len(raw) > 1048576
        or not decoder.eof
        or decoder.unused_data
        or len(raw) != parts[0]["bytes"]
        or hashlib.sha256(raw).hexdigest() != parts[0]["sha256"]
    ):
        raise ValueError("COMPARE_PART_CONTENT")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("COMPARE_PART_CONTENT")
    return value


def command(
    game_id: str, servers: list[str], *, mode: str, part: int = 0, timeout: int = 600
) -> str:
    if mode not in {"snapshot", "compare", "paper-overrides"} or len(servers) != 2:
        raise ValueError("COMPARE_SELECTION")
    if (
        not 1 <= timeout <= 900
        or len(set(servers)) != len(servers)
        or part not in range(3)
        or (mode != "snapshot" and part != 0)
    ):
        raise ValueError("COMPARE_REQUEST")
    for server in servers:
        validate_source(game_id, server)
    artifacts = Path(__file__).with_name("artifacts")
    imported = (artifacts / "world_import.py").read_text()
    sha = next(
        ast.get_source_segment(imported, node)
        for node in ast.parse(imported).body
        if isinstance(node, ast.FunctionDef) and node.name == "sha"
    )
    reader = (artifacts / "restore_reader.py").read_text()
    reader = reader.replace("from wishicraft.artifacts import world_import as imported", "")
    reader = reader.replace("from wishicraft.artifacts import world_nbt", "")
    comparison = (
        (artifacts / "restore_compare.py")
        .read_text()
        .replace("from wishicraft.artifacts import restore_reader as reader", "")
    )
    bootstrap = (
        "import sys;sys.dont_write_bytecode=True\n"
        "import types,signal,hashlib,json,base64,lzma\nfrom pathlib import Path\n"
        "def deadline(signum,frame):\n raise TimeoutError('READER_TIME_LIMIT')\n"
        f"signal.signal(signal.SIGALRM,deadline)\nsignal.alarm({timeout})\n"
        + str(sha)
        + "\nreader=types.ModuleType('reader')\n"
        + "reader.imported=types.SimpleNamespace(sha=sha)\nexec("
        + repr(reader)
        + ",reader.__dict__)\ncomparison=types.ModuleType('comparison')\n"
        + "comparison.reader=reader\nexec("
        + repr(comparison)
        + ",comparison.__dict__)\n"
        + "paths=[Path(p)/'wishinkaiwai' for p in json.loads("
        + repr(json.dumps(servers))
        + ")]\nvalue="
        + (
            "{'worlds':[comparison.snapshot(p) for p in paths]}"
            if mode == "snapshot"
            else "comparison.paper_overrides(*paths)"
            if mode == "paper-overrides"
            else "comparison.compare_worlds(*paths)"
        )
        + "\nraw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()\n"
        + "if len(raw)>1048576: raise ValueError('COMPARE_PRIVATE_OUTPUT_LIMIT')\n"
        + "packed=base64.b64encode(lzma.compress(raw)).decode()\n"
        + f"parts={3 if mode == 'snapshot' else 1}\npart={part}\n"
        + "if len(packed)>18000*parts: raise ValueError('READER_OUTPUT_LIMIT')\n"
        + "envelope={'encoding':'xz-base64-json','bytes':len(raw),'part':part,'parts':parts,"
        + "'sha256':hashlib.sha256(raw).hexdigest(),"
        + "'private_evidence':packed[part*18000:(part+1)*18000]}\n"
        + "print(reader.output(envelope))\n"
    )
    encoded = base64.b64encode(zlib.compress(bootstrap.encode())).decode()
    return "python3 -c " + shlex.quote(
        "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(encoded) + ")))"
    )
