import io
import json
from pathlib import Path

import pytest

from tools.release_evidence import REDACTED, run_safely, sanitize, save_evidence


def test_domain_stage_environment_is_not_lambda_configuration() -> None:
    state = {"environment": {"S": "dev"}, "system_id": {"S": "wishicraft-main"}}
    assert sanitize(state) == state


def test_embedded_contexts_and_lambda_values_removed_before_write(tmp_path: Path) -> None:
    variables = {
        "SECRET": "mock-sensitive-123",
        "PUBLIC": "mock-public-456",
        "DAILY_BACKUP_ENABLED": "1",
    }
    context = {"Properties": {"Environment": {"Variables": variables}, "Role": "arn:mock"}}
    original = {
        "Configuration": {"Environment": {"Variables": variables}},
        "BeforeContext": json.dumps(context),
        "AfterContext": json.dumps(json.dumps(context)),
        "ChangeSetId": "arn:mock:change-set",
        "Details": [
            {
                "Target": {"Name": "Definition", "RequiresRecreation": "Never"},
                "Evaluation": "Static",
            }
        ],
    }
    path = tmp_path / "evidence.json"
    save_evidence(path, original)
    result = path.read_text()
    assert "mock-sensitive-123" not in result and "mock-public-456" not in result
    assert '"DAILY_BACKUP_ENABLED": "1"' in result
    assert json.loads(result)["Details"] == original["Details"]
    assert json.loads(result)["ChangeSetId"] == original["ChangeSetId"]
    assert variables["SECRET"] == "mock-sensitive-123"  # comparison input stays in memory


@pytest.mark.parametrize("suffix", ["/Variables/SECRET", "/Variables", ""])
def test_property_values_and_paths(tmp_path: Path, suffix: str) -> None:
    detail = {
        "Target": {"Path": "/Properties/Environment" + suffix},
        "BeforeValue": "mock-value",
        "AfterValue": "mock-next",
    }
    save_evidence(tmp_path / "detail.json", detail)
    stored = json.loads((tmp_path / "detail.json").read_text())
    assert stored["Target"] == detail["Target"]
    assert stored["BeforeValue"] == REDACTED and stored["AfterValue"] == REDACTED


def test_only_explicit_daily_flag_values_are_retained() -> None:
    assert sanitize({"Variables": {"DAILY_BACKUP_ENABLED": "mock-secret"}}) == {
        "Variables": {"DAILY_BACKUP_ENABLED": REDACTED}
    }
    detail = {
        "Target": {"Path": "/Properties/Environment/Variables/DAILY_BACKUP_ENABLED"},
        "BeforeValue": "0",
        "AfterValue": "1",
    }
    assert sanitize(detail) == detail


def test_exception_output_and_failed_serialization_do_not_leak(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    errors = io.StringIO()

    def failure() -> None:
        raise ValueError('Environment {"SECRET": "mock-sensitive"}')

    assert run_safely(failure, errors) == 1
    assert errors.getvalue() == "Evidence collection stopped: ValueError\n"
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
    assert "mock-sensitive" not in errors.getvalue()
    assert run_safely(lambda: save_evidence(tmp_path / "never.json", object()), errors) == 1
    assert not (tmp_path / "never.json").exists()


def test_malformed_context_and_no_overwrite(tmp_path: Path) -> None:
    assert sanitize('{"Environment": {"SECRET": "mock-sensitive"') == REDACTED
    path = tmp_path / "once.json"
    save_evidence(path, {"safe": True})
    errors = io.StringIO()
    assert (
        run_safely(
            lambda: save_evidence(
                path, {"Environment": {"Variables": {"SECRET": "mock-sensitive"}}}
            ),
            errors,
        )
        == 1
    )
    assert json.loads(path.read_text()) == {"safe": True}
    assert "mock-sensitive" not in errors.getvalue()
