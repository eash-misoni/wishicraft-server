from __future__ import annotations

import base64
import gzip
import hashlib
import json
import lzma
import os
import shlex
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_restore_reader import compound, string
from wishicraft import restore_compare_payload as payload
from wishicraft.artifacts import restore_compare as compare
from wishicraft.artifacts import restore_reader as reader


def nbt(value: int, *, tag: int = 4) -> bytes:
    return b"\x0a\0\0" + compound([(tag, "ticks", struct.pack(">q", value))])


def world(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "data/minecraft").mkdir(parents=True)
    for name in ("level.dat", "data/minecraft/world_clocks.dat"):
        (root / name).write_bytes(gzip.compress(nbt(2**60 + 1), mtime=0))
    (root / "region").mkdir()
    (root / "region/r.0.0.mca").write_bytes(b"terrain")
    return root


def test_aggregate_reconstruction_and_level_separation(tmp_path: Path) -> None:
    root = world(tmp_path / "wishinkaiwai")
    before = compare.snapshot(root)
    assert before["level_dat_old"] == {"state": "missing"}
    (root / "level.dat_old").write_bytes((root / "level.dat").read_bytes())
    assert compare.snapshot(root)["level_dat_old"] == before["level_dat"]
    selected = list((root / "data/minecraft").iterdir())
    assert before["metadata_group"] == reader.file_group(root, selected)
    assert before["metadata_group"] == compare.aggregate(before["metadata_manifest"])
    (root / "level.dat").write_bytes(gzip.compress(nbt(2**60 + 2), mtime=0))
    after = compare.snapshot(root)
    assert before["metadata_group"] == after["metadata_group"]
    assert compare.compare_documents(before["level_dat"], after["level_dat"]) == {
        "classification": "typed_values_changed",
        "requires_explanation": True,
    }
    fields = compare.typed_changes(before["level_dat"]["typed"], after["level_dat"]["typed"])
    assert fields == [
        {"path": ["root", "ticks"], "before": [4, str(2**60 + 1)], "after": [4, str(2**60 + 2)]}
    ]


def test_changes_add_delete_and_unchanged(tmp_path: Path) -> None:
    left, right = world(tmp_path / "a"), world(tmp_path / "b")
    assert compare.compare_worlds(left, right)["difference"]["unchanged"] == 3
    (right / "level.dat").write_bytes(gzip.compress(nbt(7), mtime=0))
    (right / "region/r.0.0.mca").unlink()
    (right / "region/r.1.0.mca").write_bytes(b"new")
    diff = compare.compare_worlds(left, right)["difference"]
    assert list(diff["changed"]) == ["level.dat"]
    assert list(diff["added"]) == ["region/r.1.0.mca"]
    assert list(diff["deleted"]) == ["region/r.0.0.mca"]
    assert diff["unchanged"] == 1


def test_compression_difference_requires_expanded_equality(tmp_path: Path) -> None:
    p = tmp_path / "file.dat"
    p.write_bytes(gzip.compress(nbt(99), mtime=0))
    before = compare.document(p)
    p.write_bytes(gzip.compress(nbt(99), mtime=1))
    after = compare.document(p)
    assert (
        compare.compare_documents(before, after)["classification"] == "compression_representation"
    )
    p.write_bytes(gzip.compress(nbt(100), mtime=1))
    assert compare.compare_documents(before, compare.document(p))["requires_explanation"]


def test_tag_types_arrays_and_rejections() -> None:
    data = b"\x0a\0\0" + compound([(11, "opaque", struct.pack(">ii", 1, -123))])
    value = compare.typed_nbt(data)["root"][1]["opaque"]
    assert value[0] == 11 and value[1]["count"] == 1
    assert "opaque_sha256" in value[1] and "value" not in value[1]
    for invalid in (data[:-1], data + b"bad", nbt(0, tag=13)):
        with pytest.raises(ValueError):
            compare.typed_nbt(invalid)
    nonfinite = b"\x0a\0\0" + compound([(5, "not_a_normal_value", struct.pack(">f", float("nan")))])
    with pytest.raises(ValueError, match="COMPARE_NBT_NONFINITE"):
        compare.typed_nbt(nonfinite)


def test_multiple_metadata_changes_are_individually_preserved(tmp_path: Path) -> None:
    root = world(tmp_path / "world")
    second = root / "data/minecraft/weather.dat"
    second.write_bytes(gzip.compress(nbt(9), mtime=0))
    before = compare.snapshot(root)
    for name in before["metadata_manifest"]:
        (root / name).write_bytes(gzip.compress(nbt(10), mtime=0))
    after = compare.snapshot(root)
    delta = compare.changes(before["metadata_manifest"], after["metadata_manifest"])
    assert len(delta["changed"]) == 2 and delta["unchanged"] == 0
    assert not delta["added"] and not delta["deleted"]
    assert before["level_dat"] == after["level_dat"]


def test_cross_read_change_is_rejected(tmp_path: Path, monkeypatch: Any) -> None:
    root = world(tmp_path / "world")
    original = compare.document

    def changed(path: Path) -> dict[str, Any]:
        value = original(path)
        (root / "region/r.0.0.mca").write_bytes(b"changed during metadata inspection")
        return value

    monkeypatch.setattr(compare, "document", changed)
    with pytest.raises(ValueError, match="COMPARE_UNSTABLE"):
        compare.snapshot(root)


def test_unstable_and_bounds_do_not_succeed(tmp_path: Path, monkeypatch: Any) -> None:
    root = world(tmp_path / "world")
    with monkeypatch.context() as m:
        m.setattr(reader, "fingerprint", lambda p: {"state": "changed_during_read"})
        with pytest.raises(ValueError, match="COMPARE_UNSTABLE"):
            compare.snapshot(root)
    with monkeypatch.context() as m:
        m.setattr(reader, "MAX_ENTRIES", 1)
        with pytest.raises(ValueError, match="READER_ENTRY_LIMIT"):
            compare.manifest(root)
    with monkeypatch.context() as m:
        m.setattr(compare, "MAX_CHANGES", 1)
        with pytest.raises(ValueError, match="COMPARE_CHANGE_LIMIT"):
            compare.changes({}, {"a": {}, "b": {}})
    with monkeypatch.context() as m:
        m.setattr(compare, "NBT_LIMIT", 4)
        with pytest.raises(ValueError, match="COMPARE_NBT_SIZE"):
            compare.document(root / "level.dat")


def test_generated_private_parts_roundtrip_python39(tmp_path: Path, monkeypatch: Any) -> None:
    roots = [world(tmp_path / n / "wishinkaiwai") for n in ("a", "b")]
    original = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(payload, "validate_source", lambda game, server: server)
    interpreters = [sys.executable]
    if os.environ.get("WISHICRAFT_READER_PYTHON39"):
        interpreters.append(os.environ["WISHICRAFT_READER_PYTHON39"])
    for python in interpreters:
        parts = []
        for part in range(3):
            args = shlex.split(
                payload.command(
                    "game-test", [str(p.parent) for p in roots], mode="snapshot", part=part
                )
            )
            run = subprocess.run([python, *args[1:]], capture_output=True, check=True, timeout=30)
            assert not run.stderr and len(run.stdout) <= reader.MAX_OUTPUT
            parts.append(json.loads(run.stdout))
        assert len({p["sha256"] for p in parts}) == 1
        raw = lzma.decompress(base64.b64decode("".join(p["private_evidence"] for p in parts)))
        assert hashlib.sha256(raw).hexdigest() == parts[0]["sha256"]
        value = json.loads(raw)
        assert value == {"worlds": [compare.snapshot(p) for p in roots]}
        assert payload.decode_parts(parts) == value
        with pytest.raises(ValueError):
            payload.decode_parts(parts[:2])
        with pytest.raises(ValueError):
            payload.decode_parts(list(reversed(parts)))
        bad = [dict(p) for p in parts]
        bad[1]["sha256"] = "0" * 64
        with pytest.raises(ValueError):
            payload.decode_parts(bad)
    assert original == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_payload_selection_is_fixed() -> None:
    with pytest.raises(ValueError):
        payload.command("game-test", ["/etc", "/tmp"], mode="compare")
    with pytest.raises(ValueError):
        payload.command("game-test", [], mode="snapshot")
    with pytest.raises(ValueError):
        payload.command("game-test", ["a", "b"], mode="snapshot", part=3)


def test_private_output_overflow_fails_without_partial_success(
    tmp_path: Path, monkeypatch: Any
) -> None:
    roots = [world(tmp_path / n / "wishinkaiwai") for n in ("a", "b")]
    fields = [(8, str(i), string(os.urandom(16000).hex())) for i in range(4)]
    (roots[0] / "data/minecraft/large.dat").write_bytes(
        gzip.compress(b"\x0a\0\0" + compound(fields))
    )
    monkeypatch.setattr(payload, "validate_source", lambda game, server: server)
    args = shlex.split(
        payload.command("game-test", [str(p.parent) for p in roots], mode="snapshot")
    )
    result = subprocess.run([sys.executable, *args[1:]], capture_output=True, timeout=30)
    assert result.returncode != 0 and not result.stdout
    assert b"READER_OUTPUT_LIMIT" in result.stderr
