"""Offline validation of a captured archive; never register a Game or write a Game path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from wishicraft.artifacts import game_package as packages
from wishicraft.artifacts import world_import


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package = next(p for p in packages.load() if p["package_id"] == "vps-survival")
    manifest = world_import.validate(json.loads(args.manifest.read_text()), package)
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    # An offline copy can belong to the invoking operator. Production host paths
    # still require UID/GID 0 in the independently executed host module.
    packages.OWNER_UID, packages.OWNER_GID = os.getuid(), os.getgid()
    extracted = world_import.extract(args.archive, args.output, manifest)
    report = {
        "archive_sha256": world_import.sha(args.archive),
        "tree": world_import.tree(extracted),
        "world": world_import.inspect_world(extracted, manifest),
        "package_digest": packages.digest(package),
        "same_runtime": True,
        "isolated_runtime_boot": "not_performed",
    }
    (args.output / "validation.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps({"validated": True, "output": str(args.output), "runtime_boot": False}))


if __name__ == "__main__":
    main()
