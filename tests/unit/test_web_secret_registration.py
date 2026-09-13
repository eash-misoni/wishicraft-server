"""Secret registration never overwrites and requires an actual non-echo terminal."""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from web.register_secrets import RegistrationStopped, register


class Api:
    def __init__(self, existing: bool = False, fail: bool = False) -> None:
        self.existing, self.fail = existing, fail
        self.writes: list[str] = []
        self.sizes: list[int] = []

    def describe_parameters(self, **kwargs: Any) -> dict[str, Any]:
        name = kwargs["ParameterFilters"][0]["Values"][0]
        return {"Parameters": [{"Name": name, "Type": "SecureString"}] if self.existing else []}

    def put_parameter(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["Overwrite"] is False and kwargs["Type"] == "SecureString"
        self.writes.append(kwargs["Name"])
        self.sizes.append(len(kwargs["Value"]))
        if self.fail:
            raise RuntimeError(kwargs["Value"])
        return {"Version": 1}


def test_existing_secrets_never_read_or_written() -> None:
    api = Api(existing=True)
    register(api, "/oauth", "/signing")
    assert not api.writes


def test_no_tty_no_write(monkeypatch: pytest.MonkeyPatch) -> None:
    api = Api()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(RegistrationStopped):
        register(api, "/oauth", "/signing")
    assert not api.writes


@pytest.mark.parametrize("fail", [False, True])
def test_non_echo_registration_and_unknown_write_stop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail: bool,
) -> None:
    api = Api(fail=fail)
    value = secrets.token_urlsafe(32)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: value)
    if fail:
        with pytest.raises(RegistrationStopped) as error:
            register(api, "/oauth", "/signing")
        assert value not in str(error.value)
        assert api.writes == ["/oauth"]
    else:
        register(api, "/oauth", "/signing")
        assert api.writes == ["/oauth", "/signing"]
        assert api.sizes[1] >= 64
    capture = capsys.readouterr()
    assert value not in capture.out + capture.err
