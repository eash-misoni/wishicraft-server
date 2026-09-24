"""Generate a fixed supplemental read-only SSM payload from this checkout's sources."""

from __future__ import annotations

import ast
import base64
import json
import shlex
import zlib
from pathlib import Path
from typing import Any

from wishicraft.world_reference import validate_source


def command(
    targets: dict[str, dict[str, Any]], *, timeout: int = 600, include_host: bool = False
) -> str:
    if not 1 <= len(targets) <= 8 or not 1 <= timeout <= 900:
        raise ValueError("READER_REQUEST_LIMIT")
    for name, target in targets.items():
        if name == "host" or not name.isascii() or not name.replace("-", "").isalnum():
            raise ValueError("READER_LABEL")
        if set(target) != {"game_id", "server", "level", "full_tree"}:
            raise ValueError("READER_TARGET_FIELDS")
        validate_source(target["game_id"], target["server"])
        if type(target["full_tree"]) is not bool or target["level"] not in {
            "world",
            "wishinkaiwai",
        }:
            raise ValueError("READER_TARGET")
    artifacts = Path(__file__).with_name("artifacts")

    def selected(file: str, names: set[str]) -> str:
        source = (artifacts / file).read_text()
        return "\n\n".join(
            ast.get_source_segment(source, node) or ""
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name in names
        )

    reader = (artifacts / "restore_reader.py").read_text()
    reader = reader.replace("from wishicraft.artifacts import world_import as imported", "")
    reader = reader.replace("from wishicraft.artifacts import world_nbt", "")
    bootstrap = (
        "import sys\nsys.dont_write_bytecode=True\n"
        "import types,signal,hashlib,json,stat\nfrom pathlib import Path\nfrom typing import Any\n"
        "def deadline(signum,frame):\n raise TimeoutError('READER_TIME_LIMIT')\n"
        f"signal.signal(signal.SIGALRM,deadline)\nsignal.alarm({timeout})\n"
        + selected("game_package.py", {"canonical", "digest"})
        + "\npackages=types.SimpleNamespace(digest=digest)\n"
        + selected("world_import.py", {"sha", "tree"})
        + "\nimported=types.SimpleNamespace(sha=sha,tree=tree)\n"
        + "world_nbt=types.ModuleType('world_nbt')\nexec("
        + repr((artifacts / "world_nbt.py").read_text())
        + ",world_nbt.__dict__)\n"
        + "reader=types.ModuleType('restore_reader')\n"
        + "reader.imported=imported\nreader.world_nbt=world_nbt\nexec("
        + repr(reader)
        + ",reader.__dict__)\n"
        + "targets=json.loads("
        + repr(json.dumps(targets))
        + ")\nresult={name:reader.inspect_server(Path(t['server']),t['level'],"
        + "full_tree=t['full_tree']) for name,t in targets.items()}\n"
        + "for name,t in targets.items():\n"
        + " result[name]['managed_records']=reader.managed_records(Path(t['server']))\n"
        + ("result['host']=reader.host_evidence()\n" if include_host else "")
        + "print(reader.output(result))\n"
    )
    encoded = base64.b64encode(zlib.compress(bootstrap.encode())).decode()
    return "python3 -c " + shlex.quote(
        "import base64,zlib;exec(zlib.decompress(base64.b64decode(" + repr(encoded) + ")))"
    )
