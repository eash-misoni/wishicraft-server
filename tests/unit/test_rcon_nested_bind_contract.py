from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/phase6/rcon_nested_bind_running.yaml"
PREFLIGHT = ROOT / "infrastructure/host_runtime/filesystem_preflight.sh"
STOP = ROOT / "infrastructure/host_runtime/stop-v1.sh"

GAME_ROOT = "/srv/minecraft/games/game-vanilla-main/server"
PLACEHOLDERS = {
    f"{GAME_ROOT}/.rcon-cli.env",
    f"{GAME_ROOT}/.rcon-cli.yaml",
}
MOUNTS = {
    ("/run/wishicraft/rcon-password", "/run/secrets/rcon-password"): False,
    ("/run/wishicraft/rcon-cli.env", "/data/.rcon-cli.env"): True,
    ("/run/wishicraft/rcon-cli.yaml", "/data/.rcon-cli.yaml"): True,
}


def fixture() -> dict[str, object]:
    value = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def validate(value: dict[str, object]) -> None:
    assert value["game_root"] == GAME_ROOT
    identity = value["runtime_identity"]
    assert isinstance(identity, dict)
    uid, gid = identity["uid"], identity["gid"]
    container = value["container"]
    assert isinstance(container, dict)
    assert container["project"] == "wishicraft-host-runtime"
    assert container["service"] == "minecraft"

    placeholders = value["placeholders"]
    assert isinstance(placeholders, list)
    assert {item["path"] for item in placeholders} == PLACEHOLDERS
    for item in placeholders:
        assert item == {
            "path": item["path"],
            "type": "regular",
            "symlink": False,
            "uid": 0,
            "gid": 0,
            "mode": 0o644,
            "size": 0,
            "nlink": 1,
        }

    if not container["running"]:
        return

    sources = value["runtime_sources"]
    assert isinstance(sources, list)
    expected_source_modes = {
        "/run/wishicraft/rcon-password": 0o400,
        "/run/wishicraft/rcon-cli.env": 0o600,
        "/run/wishicraft/rcon-cli.yaml": 0o600,
    }
    assert {item["path"] for item in sources} == set(expected_source_modes)
    for item in sources:
        assert item["type"] == "regular"
        assert item["symlink"] is False
        assert item["uid"] == uid and item["gid"] == gid
        assert item["mode"] == expected_source_modes[item["path"]]

    mounts = value["mounts"]
    assert isinstance(mounts, list)
    actual: dict[tuple[object, object], object] = {}
    for mount in mounts:
        assert mount["type"] == "bind"
        key = (mount["source"], mount["destination"])
        assert key not in actual
        actual[key] = mount["rw"]
    assert actual == MOUNTS


def changed(path: str, value: object) -> dict[str, object]:
    data = copy.deepcopy(fixture())
    current: object = data
    parts = path.split(".")
    for part in parts[:-1]:
        assert isinstance(current, (dict, list))
        current = current[int(part)] if isinstance(current, list) else current[part]
    assert isinstance(current, (dict, list))
    if isinstance(current, list):
        current[int(parts[-1])] = value
    else:
        current[parts[-1]] = value
    return data


def test_exact_production_fixture_passes() -> None:
    validate(fixture())


@pytest.mark.parametrize(
    ("path", "value"),
    (
        ("mounts.1.rw", False),
        ("mounts.0.rw", True),
        ("mounts.1.source", "/run/wishicraft/other"),
        ("mounts.1.destination", "/data/other"),
        ("container.project", "unknown"),
        ("container.service", "unknown"),
        ("placeholders.0.size", 1),
        ("placeholders.0.symlink", True),
        ("placeholders.0.type", "directory"),
        ("placeholders.0.nlink", 2),
        ("placeholders.0.uid", 993),
        ("placeholders.0.mode", 0o600),
        ("runtime_sources.1.uid", 0),
        ("runtime_sources.1.mode", 0o644),
        ("runtime_sources.1.symlink", True),
    ),
)
def test_contract_rejects_invalid_production_topology(path: str, value: object) -> None:
    with pytest.raises(AssertionError):
        validate(changed(path, value))


def test_contract_rejects_extra_or_missing_config_mount() -> None:
    extra = fixture()
    mounts = extra["mounts"]
    assert isinstance(mounts, list)
    mounts.append(
        {
            "source": "/run/wishicraft/extra",
            "destination": "/data/.rcon-cli.extra",
            "rw": True,
            "type": "bind",
        }
    )
    with pytest.raises(AssertionError):
        validate(extra)
    missing = fixture()
    missing["mounts"] = mounts[:2]
    with pytest.raises(AssertionError):
        validate(missing)


def test_contract_rejects_wrong_game_root_and_third_placeholder() -> None:
    with pytest.raises(AssertionError):
        validate(changed("game_root", "/srv/minecraft/games/other/server"))
    data = fixture()
    placeholders = data["placeholders"]
    assert isinstance(placeholders, list)
    third = copy.deepcopy(placeholders[0])
    third["path"] = f"{GAME_ROOT}/.rcon-cli.other"
    placeholders.append(third)
    with pytest.raises(AssertionError):
        validate(data)


def test_stopped_container_accepts_strict_zero_size_placeholders() -> None:
    data = fixture()
    container = data["container"]
    assert isinstance(container, dict)
    container["running"] = False
    data["runtime_sources"] = []
    data["mounts"] = []
    validate(data)


def test_preflight_and_stop_never_mutate_live_mountpoints() -> None:
    preflight = PREFLIGHT.read_text(encoding="utf-8")
    stop = STOP.read_text(encoding="utf-8")
    for forbidden in ("rm ", "unlink", "truncate", "mv ", "install ", "touch "):
        assert forbidden not in preflight
    assert "placeholder" not in stop
    assert "rm -f" not in stop
    assert preflight.index("validate_mount_contract") < preflight.index("while IFS= read")


def test_preflight_requires_password_ro_and_cli_config_rw() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    assert '"$rw" == false' in source
    assert source.count('"$rw" == true') == 2
    assert "required RCON mounts are missing or duplicated" in source
    assert "unexpected RCON mount" in source


def test_running_preflight_preserves_cli_config_for_rcon_use() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    stop = STOP.read_text(encoding="utf-8")
    assert "validate_mount_contract" in source
    assert "rcon-cli list" in stop
    assert "rcon-cli save-all flush" in stop


def test_unknown_filesystem_artifact_remains_fail_closed() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    assert 'fail "unknown owner"' in source
    assert "GAME_DIRECTORY/.rcon-cli.env" in source
    assert "GAME_DIRECTORY/.rcon-cli.yaml" in source
