"""Build the deterministic Run Command payload for the Minecraft initial migration."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build(source: Path, output_root: Path) -> None:
    output_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    wrapper = source.read_bytes()
    if not wrapper.endswith(b"\n") or b"\r\n" in wrapper:
        raise SystemExit("wrapper must have one LF-terminated Unix representation")
    wrapper_path = output_root / "minecraft-initial-migration.sh"
    wrapper_path.write_bytes(wrapper)
    wrapper_path.chmod(0o700)
    payload = {
        "DocumentName": "AWS-RunShellScript",
        "InstanceIds": ["i-021eaa7f33ddaf0a6"],
        "TimeoutSeconds": 60,
        "Parameters": {"commands": [wrapper.decode("utf-8")], "executionTimeout": ["900"]},
    }
    payload_bytes = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    payload_path = output_root / "minecraft-initial-payload.json"
    payload_path.write_bytes(payload_bytes)
    payload_path.chmod(0o644)
    manifest = {
        "version": "minecraft-initial-v1",
        "wrapper": {"bytes": len(wrapper), "sha256": hashlib.sha256(wrapper).hexdigest()},
        "payload": {
            "bytes": len(payload_bytes),
            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
        },
        "target": "i-021eaa7f33ddaf0a6",
        "document": "AWS-RunShellScript",
        "commands": 1,
    }
    manifest_path = output_root / "minecraft-initial-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest_path.chmod(0o644)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if (
        not args.output_root.is_absolute()
        or args.output_root.exists()
        or args.output_root.is_symlink()
    ):
        raise SystemExit("output root must be a new absolute path")
    build(args.source.resolve(strict=True), args.output_root)


if __name__ == "__main__":
    main()
