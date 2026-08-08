"""Unit tests for the deliberately restricted Phase 1 Route 53 CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wishicraft.config import Configuration, load_configuration
from wishicraft.route53_cli import (
    Route53CliError,
    Route53Result,
    _settings,
    _wait_change,
    main,
    manage,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INSTANCE_ID = "i-0123456789abcdef0"
ADDRESS = "8.8.8.8"


def _record(address: str = ADDRESS, ttl: int = 60) -> dict[str, Any]:
    return {
        "Name": "mc-dev.wishicraft.net.",
        "Type": "A",
        "TTL": ttl,
        "ResourceRecords": [{"Value": address}],
    }


def _identity() -> dict[str, Any]:
    return {"Account": "385526546525"}


def _zone() -> dict[str, Any]:
    return {"HostedZone": {"Name": "wishicraft.net."}}


def _instance(address: str = ADDRESS, state: str = "running") -> dict[str, Any]:
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": INSTANCE_ID,
                        "State": {"Name": state},
                        "PublicIpAddress": address,
                        "Tags": [
                            {"Key": "Project", "Value": "wishicraft"},
                            {"Key": "ManagedBy", "Value": "cdk"},
                            {"Key": "Owner", "Value": "project-owner"},
                            {"Key": "Stage", "Value": "dev"},
                        ],
                    }
                ]
            }
        ]
    }


def _stack(instance_id: object = INSTANCE_ID) -> dict[str, Any]:
    return {
        "Stacks": [{"Outputs": [{"OutputKey": "MinecraftInstanceId", "OutputValue": instance_id}]}]
    }


class FakeAws:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses.copy()
        self.calls: list[list[str]] = []

    def __call__(self, profile: str, region: str, arguments: list[str]) -> dict[str, Any]:
        assert profile == "test-profile"
        assert region == "ap-northeast-1"
        self.calls.append(arguments)
        assert self.responses, arguments
        return self.responses.pop(0)


def _configuration() -> Configuration:
    return load_configuration(REPOSITORY_ROOT, "dev")


def test_settings_reads_dev_route53_values_from_canonical_configuration() -> None:
    settings = _settings(_configuration())

    assert settings.hosted_zone_id == "Z077818024BJUAUBFMTKV"
    assert settings.record_name == "mc-dev.wishicraft.net."
    assert settings.record_type == "A"
    assert settings.ttl == 60
    assert settings.timeout == 120


def test_prod_null_hosted_zone_is_rejected_without_guessing() -> None:
    with pytest.raises(Route53CliError, match="stage configuration is incomplete"):
        _settings(load_configuration(REPOSITORY_ROOT, "prod"))


def test_upsert_new_record_uses_only_configured_target_and_checks_postcondition() -> None:
    aws = FakeAws(
        [
            _identity(),
            _zone(),
            _stack(),
            _instance(),
            {"ResourceRecordSets": []},
            {"ChangeInfo": {"Id": "/change/C1"}},
            {"ChangeInfo": {"Status": "PENDING"}},
            {"ChangeInfo": {"Status": "INSYNC"}},
            {"ResourceRecordSets": [_record()]},
        ]
    )
    result = manage(_configuration(), "UPSERT", "test-profile", aws=aws, sleep=lambda _: None)

    assert result.changed is True
    assert result.change_id == "/change/C1"
    assert result.public_ipv4 == ADDRESS
    change = next(call for call in aws.calls if call[1] == "change-resource-record-sets")
    assert change[:4] == [
        "route53",
        "change-resource-record-sets",
        "--hosted-zone-id",
        "Z077818024BJUAUBFMTKV",
    ]
    batch = json.loads(change[5])
    assert batch == {"Changes": [{"Action": "UPSERT", "ResourceRecordSet": _record()}]}


def test_upsert_same_record_is_idempotent() -> None:
    aws = FakeAws(
        [_identity(), _zone(), _stack(), _instance(), {"ResourceRecordSets": [_record()]}]
    )

    result = manage(_configuration(), "UPSERT", "test-profile", aws=aws)

    assert result.changed is False
    assert result.change_id is None
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


def test_upsert_replaces_an_old_simple_public_ipv4() -> None:
    aws = FakeAws(
        [
            _identity(),
            _zone(),
            _stack(),
            _instance(),
            {"ResourceRecordSets": [_record("1.1.1.1")]},
            {"ChangeInfo": {"Id": "/change/C-old"}},
            {"ChangeInfo": {"Status": "INSYNC"}},
            {"ResourceRecordSets": [_record()]},
        ]
    )

    result = manage(_configuration(), "UPSERT", "test-profile", aws=aws)

    assert result.changed is True
    assert result.public_ipv4 == ADDRESS


@pytest.mark.parametrize(
    "record",
    [
        {**_record(), "AliasTarget": {"DNSName": "example.net."}},
        {**_record(), "SetIdentifier": "blue", "Weight": 1},
        {**_record(), "ResourceRecords": [{"Value": ADDRESS}, {"Value": "1.1.1.1"}]},
    ],
)
def test_upsert_refuses_complex_records_without_changing(record: dict[str, Any]) -> None:
    aws = FakeAws([_identity(), _zone(), _stack(), _instance(), {"ResourceRecordSets": [record]}])

    with pytest.raises(Route53CliError, match="refusing"):
        manage(_configuration(), "UPSERT", "test-profile", aws=aws)
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


def test_delete_uses_complete_read_record_and_verifies_absence() -> None:
    existing = _record(ADDRESS, ttl=300)
    aws = FakeAws(
        [
            _identity(),
            _zone(),
            {"ResourceRecordSets": [existing]},
            {"ChangeInfo": {"Id": "/change/C2"}},
            {"ChangeInfo": {"Status": "INSYNC"}},
            {"ResourceRecordSets": []},
        ]
    )

    result = manage(_configuration(), "DELETE", "test-profile", aws=aws)

    assert result.changed is True
    change = next(call for call in aws.calls if call[1] == "change-resource-record-sets")
    assert json.loads(change[5]) == {
        "Changes": [{"Action": "DELETE", "ResourceRecordSet": existing}]
    }


def test_delete_missing_record_is_idempotent_and_does_not_call_change() -> None:
    aws = FakeAws([_identity(), _zone(), {"ResourceRecordSets": []}])

    result = manage(_configuration(), "DELETE", "test-profile", aws=aws)

    assert result.changed is False
    assert result.final_status == "INSYNC"
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


@pytest.mark.parametrize(
    "record",
    [
        {**_record(), "AliasTarget": {"DNSName": "example.net."}},
        {**_record(), "SetIdentifier": "blue", "Weight": 1},
        {**_record(), "ResourceRecords": [{"Value": ADDRESS}, {"Value": "1.1.1.1"}]},
    ],
)
def test_delete_refuses_complex_records_without_changing(record: dict[str, Any]) -> None:
    aws = FakeAws([_identity(), _zone(), {"ResourceRecordSets": [record]}])

    with pytest.raises(Route53CliError, match="refusing"):
        manage(_configuration(), "DELETE", "test-profile", aws=aws)
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


def test_other_record_returned_at_list_position_is_not_deleted() -> None:
    other = {**_record(), "Name": "mc-prod.wishicraft.net."}
    aws = FakeAws([_identity(), _zone(), {"ResourceRecordSets": [other]}])

    result = manage(_configuration(), "DELETE", "test-profile", aws=aws)

    assert result.changed is False
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


@pytest.mark.parametrize(
    "stack_response,instance_response",
    [
        ({"Stacks": [{"Outputs": []}]}, None),
        (_stack("not-an-instance"), None),
        (_stack(), {"Reservations": []}),
        (_stack(), _instance(state="stopped")),
        (_stack(), _instance(address="10.0.0.1")),
    ],
)
def test_upsert_rejects_invalid_authoritative_instance_resolution(
    stack_response: dict[str, Any], instance_response: dict[str, Any] | None
) -> None:
    responses = [_identity(), _zone(), stack_response]
    if instance_response is not None:
        responses.append(instance_response)
    aws = FakeAws(responses)

    with pytest.raises(Route53CliError):
        manage(_configuration(), "UPSERT", "test-profile", aws=aws)
    assert all(call[1] != "change-resource-record-sets" for call in aws.calls if len(call) > 1)


def test_caller_account_mismatch_is_rejected_before_other_aws_calls() -> None:
    aws = FakeAws([{"Account": "000000000000"}])

    with pytest.raises(Route53CliError, match="caller account"):
        manage(_configuration(), "DELETE", "test-profile", aws=aws)
    assert len(aws.calls) == 1


def test_wait_handles_pending_then_insync_and_timeout_and_invalid_response() -> None:
    settings = _settings(_configuration())
    ticks = iter([0.0, 0.0, 1.0, 1.0])
    aws = FakeAws([{"ChangeInfo": {"Status": "PENDING"}}, {"ChangeInfo": {"Status": "INSYNC"}}])
    assert (
        _wait_change(
            settings,
            "test-profile",
            "/change/C3",
            aws,
            clock=lambda: next(ticks),
            sleep=lambda _: None,
        )
        == "INSYNC"
    )

    timeout_ticks = iter([0.0, 120.0])
    timeout_aws = FakeAws([{"ChangeInfo": {"Status": "PENDING"}}])
    with pytest.raises(Route53CliError, match="timeout"):
        _wait_change(
            settings,
            "test-profile",
            "/change/C4",
            timeout_aws,
            clock=lambda: next(timeout_ticks),
        )

    invalid_aws = FakeAws([{"ChangeInfo": {"Status": "FAILED"}}])
    with pytest.raises(Route53CliError, match="invalid"):
        _wait_change(settings, "test-profile", "/change/C5", invalid_aws)


def test_postconditions_reject_unexpected_route53_state() -> None:
    upsert_aws = FakeAws(
        [
            _identity(),
            _zone(),
            _stack(),
            _instance(),
            {"ResourceRecordSets": []},
            {"ChangeInfo": {"Id": "/change/C6"}},
            {"ChangeInfo": {"Status": "INSYNC"}},
            {"ResourceRecordSets": [_record("1.1.1.1")]},
        ]
    )
    with pytest.raises(Route53CliError, match="UPSERT postcondition"):
        manage(_configuration(), "UPSERT", "test-profile", aws=upsert_aws)

    delete_aws = FakeAws(
        [
            _identity(),
            _zone(),
            {"ResourceRecordSets": [_record()]},
            {"ChangeInfo": {"Id": "/change/C7"}},
            {"ChangeInfo": {"Status": "INSYNC"}},
            {"ResourceRecordSets": [_record()]},
        ]
    )
    with pytest.raises(Route53CliError, match="DELETE postcondition"):
        manage(_configuration(), "DELETE", "test-profile", aws=delete_aws)


def test_main_emits_stable_json_and_keeps_diagnostics_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("wishicraft.route53_cli.shutil.which", lambda _: "aws")
    expected = Route53Result(
        stage="dev",
        action="DELETE",
        account="385526546525",
        region="ap-northeast-1",
        stack="MinecraftStack-dev",
        instance_id=None,
        hosted_zone_id="Z077818024BJUAUBFMTKV",
        record_name="mc-dev.wishicraft.net",
        record_type="A",
        ttl=60,
        public_ipv4=None,
        changed=False,
        change_id=None,
        final_status="INSYNC",
    )
    monkeypatch.setattr(
        "wishicraft.route53_cli.manage",
        lambda configuration, operation, profile: expected,
    )
    assert main(["DELETE", "--stage", "dev", "--profile", "test-profile"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "account": "385526546525",
        "action": "DELETE",
        "change_id": None,
        "changed": False,
        "final_status": "INSYNC",
        "hosted_zone_id": "Z077818024BJUAUBFMTKV",
        "instance_id": None,
        "public_ipv4": None,
        "record_name": "mc-dev.wishicraft.net",
        "record_type": "A",
        "region": "ap-northeast-1",
        "stack": "MinecraftStack-dev",
        "stage": "dev",
        "ttl": 60,
    }
    assert captured.err == ""


def test_main_returns_nonzero_error_without_success_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("wishicraft.route53_cli.shutil.which", lambda _: "aws")
    monkeypatch.setattr(
        "wishicraft.route53_cli.manage",
        lambda configuration, operation, profile: (_ for _ in ()).throw(
            Route53CliError("AWS failed")
        ),
    )

    assert main(["DELETE", "--stage", "dev", "--profile", "test-profile"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "route53-cli: AWS failed\n"
