"""Actual CLI envelope -> host item reader -> authoritative empty projection."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from wishicraft.artifacts import targeted_runtime as host
from wishicraft.artifacts import whitelist_policy as policy
from wishicraft.operation import _attribute_map

GAME = "game-fixture"
KEY = policy.policy_key(GAME)
CONFIG = {"region": "ap-northeast-1", "games_table": "fixture-games"}


def response(monkeypatch: pytest.MonkeyPatch, stdout: str, code: int = 0, stderr: str = "") -> None:
    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["aws", "dynamodb", "get-item"]
        assert "--query" not in args and args[-2:] == ["--output", "json"]
        return subprocess.CompletedProcess(args, code, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)


def read(identity: str = KEY) -> dict[str, Any]:
    raw = host.item(CONFIG, "games_table", "game_id", identity)
    return policy.from_item(_attribute_map(raw), None if identity == policy.COMMON else GAME)


@pytest.mark.parametrize("stdout", ["", " \n\t", "{}"])
def test_absent_specific_is_empty(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    response(monkeypatch, stdout)
    assert read() == policy.empty()
    with pytest.raises(ValueError, match="migration required"):
        read(policy.COMMON)


@pytest.mark.parametrize("members", [{}, {"00000000-0000-0000-0000-000000000001": "FixturePlayer"}])
def test_present_policy(monkeypatch: pytest.MonkeyPatch, members: dict[str, str]) -> None:
    value = {"revision": 1, "members": members}
    raw = _attribute_map({"game_id": KEY, "policy_json": policy.encoded(value)})
    response(monkeypatch, json.dumps({"Item": raw}))
    assert read() == value


@pytest.mark.parametrize(
    "stdout,code,stderr",
    [
        ("", 1, "AccessDenied"),
        ("{}", 1, ""),
        ("", 0, "credential error"),
        ("{}", 0, "network error"),
        ("not-json", 0, ""),
        ("null", 0, ""),
        ("[]", 0, ""),
        ('{"Item": null}', 0, ""),
        ('{"Item": {}}', 0, ""),
        ('{"unexpected": true}', 0, ""),
        ('{"Item": {"game_id": {"S": "wrong"}}}', 0, ""),
        ('{"Item": {"game_id": {"S": "x", "NULL": true}}}', 0, ""),
    ],
)
def test_read_failure_is_not_absence(
    monkeypatch: pytest.MonkeyPatch, stdout: str, code: int, stderr: str
) -> None:
    response(monkeypatch, stdout, code, stderr)
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        read()


def test_absent_specific_projects_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    response(monkeypatch, "\n")
    specific = read()
    common = policy.empty()
    # Synthetic process ownership only; real projection uses actual temporary files/atomic replace.
    import os

    monkeypatch.setattr(policy, "UID", os.getuid())
    monkeypatch.setattr(policy, "GID", os.getgid())
    (tmp_path / "server.properties").write_text(
        "online-mode=true\nwhite-list=true\nenforce-whitelist=true\n"
    )
    (tmp_path / "whitelist.json").write_text("[]\n")
    for path in tmp_path.iterdir():
        path.chmod(0o640)
    actual = policy.project({"data_source": str(tmp_path)}, common, specific, host.atomic)
    assert actual == policy.digest({})
    assert (tmp_path / "whitelist.json").read_bytes() == b"[]\n"


def test_same_manifest_reader_bundle_preserves_registered_game(tmp_path: Path) -> None:
    import copy
    import hashlib

    from tests.unit.test_full_game_binding import GAMES, full_game
    from tests.unit.test_runtime_memory import receipt
    from wishicraft.game_creation import REGISTRY_KEY
    from wishicraft.game_package_migration import prepare_reader_fix

    root = Path(__file__).resolve().parents[2]
    evidence = json.loads(
        (root / "docs/evidence/neoforge_package_production_2026-09-14.json").read_text()
    )
    digest = evidence["migration"]["after_digest"]
    legacy = json.loads((root / "config/two-game-dev.json").read_text())
    records = []
    for index, identity in enumerate([*legacy, GAMES[2]]):
        game = full_game(GAMES[index])
        game["game_id"] = identity
        if index == 2:
            game["creation"]["config_digest"] = digest
        records.append(_attribute_map(game))
    records.extend(
        [
            {"game_id": {"S": REGISTRY_KEY}, "registered_ids": {"SS": [GAMES[2]]}},
            _attribute_map(
                {"game_id": policy.COMMON, "policy_json": policy.encoded(policy.empty())}
            ),
        ]
    )
    inventory: dict[str, Any] = {"Items": records}
    before = copy.deepcopy(inventory)
    result = prepare_reader_fix(root, tmp_path / "bundle", receipt(), inventory)
    assert inventory == before
    assert result["old_digest"] == result["new_digest"] == digest
    assert not result["durable_record_updates"] and not result["package_catalog_changed"]
    assert len(result["plan"]["files"]) == 1
    entry = result["plan"]["files"][0]
    assert entry["destination"] == "/usr/local/libexec/wishicraft/operation-v2"
    assert entry["sha256"] != entry["predecessor"]
    assert (
        hashlib.sha256((tmp_path / "bundle/reader.artifact").read_bytes()).hexdigest()
        == entry["sha256"]
    )
    assert (tmp_path / "bundle/install.py").read_bytes() == (
        root / "src/wishicraft/artifacts/runtime_install.py"
    ).read_bytes()
    damaged = copy.deepcopy(inventory)
    damaged["Items"][2]["creation"]["M"]["config_digest"] = {"S": "f" * 64}
    with pytest.raises(ValueError, match="REGISTRATION_MISMATCH"):
        prepare_reader_fix(root, tmp_path / "bad-digest", receipt(), damaged)
    damaged = copy.deepcopy(inventory)
    damaged["Items"][2]["materialization_state"] = {"S": "MATERIALIZED"}
    with pytest.raises(ValueError, match="unmaterialized"):
        prepare_reader_fix(root, tmp_path / "materialized", receipt(), damaged)
    with pytest.raises(ValueError, match="complete registry"):
        prepare_reader_fix(
            root, tmp_path / "incomplete", receipt(), {**inventory, "LastEvaluatedKey": {"k": "x"}}
        )
