from __future__ import annotations

import ast
import gzip
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from wishicraft import restore_reader_payload as payload
from wishicraft.artifacts import restore_reader as reader
from wishicraft.artifacts import world_import, world_nbt


def string(value: str) -> bytes:
    data = value.encode()
    return struct.pack(">H", len(data)) + data


def compound(fields: list[tuple[int, str, bytes]]) -> bytes:
    return b"".join(bytes([tag]) + string(key) + value for tag, key, value in fields) + b"\0"


def fixture(root: Path) -> Path:
    world = root / "world"
    region = world / "dimensions/minecraft/overworld/region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_bytes(b"terrain-fixture")
    (world / "playerdata").mkdir()
    (world / "playerdata/private.dat").write_bytes(b"NEVER_OUTPUT_PLAYER")
    (root / "server.properties").write_text("rcon.password=NEVER_OUTPUT_SECRET\n")
    document = compound(
        [
            (
                10,
                "Data",
                compound(
                    [
                        (10, "Version", compound([(8, "Name", string("26.2"))])),
                        (3, "DataVersion", struct.pack(">i", 4903)),
                        (8, "LevelName", string("world")),
                        (4, "Time", struct.pack(">q", 123)),
                        (
                            10,
                            "spawn",
                            compound(
                                [
                                    (8, "dimension", string("minecraft:overworld")),
                                    (11, "pos", struct.pack(">iiii", 3, -1, 70, 8)),
                                ]
                            ),
                        ),
                    ]
                ),
            ),
        ]
    )
    (world / "level.dat").write_bytes(gzip.compress(b"\x0a" + string("") + document))
    return root


def test_real_nbt_bytes_to_json_roundtrip_and_exact_import_hash(tmp_path: Path) -> None:
    root = fixture(tmp_path / "server")
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    parsed = world_nbt.read(root / "world/level.dat")
    assert type(parsed["Data"]["spawn"]["pos"]) is bytes
    with pytest.raises(TypeError):
        json.dumps(parsed["Data"]["spawn"])  # Exact previous diagnostic defect.
    result = json.loads(reader.output(reader.inspect_server(root, "world", full_tree=True)))
    pos = result["nbt"]["spawn"]["selected_fields"]["pos"]
    assert pos["state"] == "unsupported" and pos["type"] == "bytes" and pos["length"] == 12
    assert len(pos["sha256"]) == 64 and "value" not in pos
    assert result["nbt"]["legacy_seed"]["state"] == "missing"
    assert result["terrain_region_count"] == 1
    assert result["server_tree"] == world_import.tree(root)
    assert result["world_tree"] == world_import.tree(root / "world")
    assert (
        result["terrain_samples"]["dimensions/minecraft/overworld/region/r.0.0.mca"]["state"]
        == "read"
    )
    assert "NEVER_OUTPUT" not in reader.output(result)
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_missing_null_unsupported_and_read_failure_are_distinct(tmp_path: Path) -> None:
    assert reader.field({}, "x", int) == {"state": "missing"}
    assert reader.field({"x": None}, "x", int) == {"state": "null"}
    assert reader.field({"x": True}, "x", int)["state"] == "unsupported"
    assert reader.field({"x": 0}, "x", int) == {"state": "value", "value": 0}
    assert reader.field({"x": "a" * 129}, "x", str)["state"] == "unsupported"
    path = tmp_path / "level.dat"
    assert reader.nbt_summary(path)["state"] == "missing"
    path.write_bytes(b"invalid gzip")
    assert reader.nbt_summary(path)["state"] == "read_failed"


@pytest.mark.parametrize("link", ["symbolic", "hard"])
def test_unsafe_tree_rejected(tmp_path: Path, link: str) -> None:
    root = fixture(tmp_path / "server")
    if link == "symbolic":
        (root / "bad").symlink_to(root / "server.properties")
    else:
        os.link(root / "server.properties", root / "bad")
    with pytest.raises(ValueError, match="READER_TREE_TYPE"):
        reader.inspect_server(root, "world", full_tree=True)


def test_bounds_and_no_full_hash_for_live_content(tmp_path: Path, monkeypatch: Any) -> None:
    root = fixture(tmp_path / "server")
    value = reader.inspect_server(root, "world", full_tree=False)
    assert "server_tree" not in value and "world_tree" not in value
    with pytest.raises(ValueError, match="READER_OUTPUT_LIMIT"):
        reader.output({"large": "a" * reader.MAX_OUTPUT})
    with pytest.raises(TypeError):
        reader.output({"unexpected": b"not stringified"})
    with pytest.raises(ValueError, match="READER_LEVEL_NAME"):
        reader.inspect_server(root, "..", full_tree=False)
    monkeypatch.setattr(reader, "MAX_ENTRIES", 1)
    with pytest.raises(ValueError, match="READER_ENTRY_LIMIT"):
        reader.inspect_server(root, "world", full_tree=True)
    monkeypatch.setattr(reader, "MAX_ENTRIES", 100)
    monkeypatch.setattr(reader, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="READER_BYTE_LIMIT"):
        reader.inspect_server(root, "world", full_tree=True)


def test_live_fingerprint_marks_change(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "region.mca"
    path.write_bytes(b"before")
    sha = world_import.sha

    def changed(p: Path) -> str:
        value = sha(p)
        p.write_bytes(b"after with new size")
        return value

    monkeypatch.setattr(world_import, "sha", changed)
    assert reader.fingerprint(path)["state"] == "changed_during_read"


def test_fixed_payload_rejects_arbitrary_paths_and_timeout() -> None:
    target = {
        "game_id": "game-vanilla-secondary",
        "server": "/etc",
        "level": "world",
        "full_tree": True,
    }
    with pytest.raises(ValueError):
        payload.command({"test": target})
    with pytest.raises(ValueError, match="READER_REQUEST_LIMIT"):
        payload.command({}, timeout=99999)


def test_payload_execution_form_and_no_bytecode(tmp_path: Path, monkeypatch: Any) -> None:
    root = fixture(tmp_path / "server")
    # Only test path authorization is relocated; generated reader/import/bootstrap
    # bytes and invocation form are the production builder's exact output.
    monkeypatch.setattr(payload, "validate_source", lambda game, value: value)
    target = {
        "game_id": "game-vanilla-secondary",
        "server": str(root),
        "level": "world",
        "full_tree": True,
    }
    command = payload.command({"previous": target}, timeout=20)
    arguments = shlex.split(command)
    ast.parse(Path(reader.__file__).read_text(), feature_version=(3, 9))
    interpreters = [sys.executable]
    candidate = os.environ.get("WISHICRAFT_READER_PYTHON39")
    if candidate:
        assert shutil.which(candidate)
        interpreters.append(candidate)
    for executable in interpreters:
        result = subprocess.run(
            [executable, *arguments[1:]],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        value = json.loads(result.stdout)
        assert value["previous"]["server_tree"] == world_import.tree(root)
        assert value["previous"]["nbt"]["spawn"]["selected_fields"]["pos"]["state"] == "unsupported"
        assert "NEVER_OUTPUT" not in result.stdout and not result.stderr
    assert not list(tmp_path.rglob("__pycache__"))


def test_paper_dimension_player_privacy_and_payload_roundtrip(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from tests.unit.test_world_import import nbt

    root = fixture(tmp_path / "server")
    (root / "world").rename(root / "wishinkaiwai")
    level = root / "wishinkaiwai"
    for dimension in ("overworld", "the_nether", "the_end"):
        d = level / "dimensions/minecraft" / dimension
        (d / "region").mkdir(parents=True, exist_ok=True)
        for i in range(6):
            (d / "region" / f"r.{i}.0.mca").write_bytes(dimension.encode() + bytes([i]))
        (d / "paper-world.yml").write_text("_version: 31\n")
        metadata = d / "data/minecraft"
        metadata.mkdir(parents=True)
        (metadata / "world_border.dat").write_bytes(nbt({"data": {"size": 123}}))
    for group in ("data", "stats", "advancements"):
        folder = level / "players" / group
        folder.mkdir(parents=True)
        for player in ("private-one", "private-two", "private-three"):
            (folder / (player + (".dat" if group == "data" else ".json"))).write_bytes(
                nbt(
                    {
                        "Inventory": {"id": "private-item"},
                        "EnderItems": {},
                        "Pos": {"opaque": -(2**63) + 1},
                        "Dimension": "minecraft:overworld",
                    }
                )
                if group == "data"
                else b'{"secret-progress":true}'
            )
    for name in world_import.CONFIGS:
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("_version: 31\n")
    before = world_import.tree(root)
    monkeypatch.setattr(payload, "validate_source", lambda game, value: value)
    command = payload.command(
        {
            "paper": {
                "game_id": "game-test",
                "server": str(root),
                "level": "wishinkaiwai",
                "full_tree": True,
            }
        }
    )
    interpreters = [sys.executable]
    if candidate := os.environ.get("WISHICRAFT_READER_PYTHON39"):
        assert shutil.which(candidate)
        interpreters.append(candidate)
    for executable in interpreters:
        run = subprocess.run(
            [executable, *shlex.split(command)[1:]],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=tmp_path,
        )
        parsed = json.loads(run.stdout)["paper"]["paper"]
        assert all(
            v["region_count"] == 6 and len(v["samples"]) == 2 for v in parsed["dimensions"].values()
        )
        assert all(v["count"] == 3 for v in parsed["players"].values())
        assert parsed["players"]["data"]["decoded_count"] == 3
        assert len(parsed["saved_metadata"]) == 3
        assert all(v["state"] == "read" for v in parsed["configs"].values())
        assert all(
            word not in run.stdout for word in ("private-", "secret-progress", "NEVER_OUTPUT")
        )
        assert not run.stderr
    assert world_import.tree(root) == before
    assert not list(tmp_path.rglob("__pycache__"))
    first = reader.paper_content(root, reader.bounded_files(root))["players"]["stats"]
    (level / "players/stats/private-one.json").write_text('{"changed":true}')
    second = reader.paper_content(root, reader.bounded_files(root))["players"]["stats"]
    assert first["sha256"] != second["sha256"]
    assert first["names_sha256"] == second["names_sha256"]
    assert reader.canonical_nbt(-(2**63) + 1) == {"integer": "-9223372036854775807"}
    assert "opaque_bytes" in reader.canonical_nbt(b"\0" * 12)


def test_managed_record_identity_and_allowlist(tmp_path: Path, monkeypatch: Any) -> None:
    from types import SimpleNamespace

    server = fixture(tmp_path / "worlds/op-test/server")
    owner = server.parent.parent / "op-test.owner.json"
    owner.write_text(
        json.dumps({"phase": "prepared", "protected": True, "future_secret": "HIDDEN"})
    )
    owner.chmod(0o600)
    stat_before = Path.lstat

    def root_stat(path: Path) -> Any:
        info = stat_before(path)
        if path == owner:
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_uid=0,
                st_gid=0,
                st_size=info.st_size,
                st_nlink=info.st_nlink,
            )
        return info

    monkeypatch.setattr(Path, "lstat", root_stat)
    result = reader.managed_records(server)
    assert result["owner"]["record"] == {"phase": "prepared", "protected": True}
    assert result["validated"]["state"] == "missing"
    assert "HIDDEN" not in reader.output(result)
    owner.chmod(0o644)
    with pytest.raises(ValueError, match="READER_RECORD_IDENTITY"):
        reader.managed_records(server)


def test_host_evidence_excludes_environment_and_secret_receipt_fields(
    tmp_path: Path, monkeypatch: Any
) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("# reviewed fixture\n")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {"phase": "ready", "target": {"data_source": "/test/server"}, "secret": "DO_NOT_OUTPUT"}
        )
    )
    read_text = Path.read_text
    stat_method, lstat_method = Path.stat, Path.lstat

    def mapped(path: Path) -> Path:
        if str(path).startswith("/usr/local/libexec/wishicraft/"):
            return helper
        if str(path) == "/var/lib/wishicraft/runtime/receipt.json":
            return receipt
        return path

    monkeypatch.setattr(Path, "stat", lambda path, **kw: stat_method(mapped(path), **kw))
    monkeypatch.setattr(Path, "lstat", lambda path: lstat_method(mapped(path)))
    monkeypatch.setattr(Path, "read_text", lambda path, **kw: read_text(mapped(path), **kw))
    sha = world_import.sha
    monkeypatch.setattr(world_import, "sha", lambda path: sha(mapped(path)))
    calls = []

    def output(args: list[str], **kw: Any) -> str:
        calls.append(args)
        assert kw["timeout"] == 15
        if args[0] in {"findmnt", "lsblk"}:
            return "{}"
        if args == ["docker", "ps", "-q"]:
            return "abcdef123456\n"
        assert args == ["docker", "inspect", "abcdef123456"]
        return json.dumps(
            [
                {
                    "Config": {"Image": "pinned-image", "Env": ["SECRET=DO_NOT_OUTPUT"]},
                    "State": {"Running": True},
                    "Mounts": [
                        {
                            "Type": "bind",
                            "Source": "/test/server",
                            "Destination": "/data",
                            "RW": True,
                        }
                    ],
                }
            ]
        )

    monkeypatch.setattr(subprocess, "check_output", output)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: (100, 20, 80))
    result = reader.host_evidence()
    assert result["containers"][0]["mounts"][0]["Source"] == "/test/server"
    assert result["runtime_receipt"]["phase"] == "ready"
    assert "DO_NOT_OUTPUT" not in reader.output(result)
    assert len(calls) == 4
    assert result["data_space"] == {"total": 100, "used": 20, "free": 80}
    assert calls[2] == [
        "findmnt",
        "--json",
        "--mountpoint",
        "/srv/minecraft",
        "--output",
        "SOURCE,FSTYPE,OPTIONS",
    ]
    assert calls[3] == ["lsblk", "--json", "--output", "PATH,SERIAL,TYPE,FSTYPE,MOUNTPOINTS,RO"]


def test_six_game_evidence_budget_and_plan_hashes(tmp_path: Path, monkeypatch: Any) -> None:
    from types import SimpleNamespace

    from wishicraft.artifacts.game_package import digest

    prior = json.loads(
        (
            Path(__file__).parents[2] / "docs/evidence/game_restore_prepared_2026-09-23.json"
        ).read_text()
    )
    stat_before = Path.lstat
    records = set()

    def root_stat(path: Path) -> Any:
        info = stat_before(path)
        if path in records:
            return SimpleNamespace(
                st_mode=info.st_mode,
                st_uid=0,
                st_gid=0,
                st_size=info.st_size,
                st_nlink=info.st_nlink,
            )
        return info

    monkeypatch.setattr(Path, "lstat", root_stat)
    evidence = {}
    for index in range(6):
        server = fixture(
            tmp_path / ("game-" + "a" * 64 + str(index)) / "worlds" / ("op-" + "b" * 64) / "server"
        )
        for label, value in [
            ("owner", next(reversed(prior["retained_owners"].values()))["record"]),
            (
                "validated",
                {
                    "restore": prior["plan"],
                    "candidate": "staging-fixture",
                    "future_secret": "HIDDEN",
                },
            ),
        ]:
            path = (
                server.parent.parent / (server.parent.name + ".owner.json")
                if label == "owner"
                else server.parent / "validated.json"
            )
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            records.add(path)
        result = reader.inspect_server(server, "world", full_tree=True, content=index < 2)
        result["managed_records"] = reader.managed_records(server)
        assert result["managed_records"]["validated"]["record"]["restore_sha256"] == digest(
            prior["plan"]
        )
        assert "restore" not in result["managed_records"]["owner"]["record"]
        if index >= 2:
            assert "nbt" not in result and "terrain_samples" not in result
        evidence["game-" + str(index)] = result
    encoded = reader.output(evidence)
    assert len(encoded.encode()) < reader.MAX_OUTPUT
    assert json.loads(encoded) == evidence and "HIDDEN" not in encoded
    with pytest.raises(ValueError, match="READER_EMPTY_SELECTION"):
        reader.inspect_server(server, "world", full_tree=False, content=False)
