from __future__ import annotations

import pytest

from wishicraft.stop_workflow import StopErrorCode, StopWorkflowError
from wishicraft.stop_workflow_lambda import (
    _command_result,
    _delete_dns,
    _dns_change_complete,
)


class Ssm:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def get_command_invocation(self, **kwargs: object) -> object:
        del kwargs
        return self.response


class Route53:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.changes: list[dict[str, object]] = []
        self.change_status = "INSYNC"

    def list_resource_record_sets(self, **kwargs: object) -> object:
        del kwargs
        return {"ResourceRecordSets": self.records}

    def change_resource_record_sets(self, **kwargs: object) -> object:
        self.changes.append(kwargs)
        return {"ChangeInfo": {"Id": "/change/change-1"}}

    def get_change(self, **kwargs: object) -> object:
        del kwargs
        return {"ChangeInfo": {"Status": self.change_status}}


class Runtime:
    hosted_zone_id = "ZONE"
    record_name = "mc-dev.wishicraft.net"


def test_command_poll_classifies_save_failure_from_fixed_wrapper_json() -> None:
    with pytest.raises(StopWorkflowError) as captured:
        _command_result(
            Ssm(
                {
                    "Status": "Failed",
                    "ResponseCode": 73,
                    "StandardOutputContent": (
                        '{"schema_version":1,"error_code":"MINECRAFT_SAVE_FAILED"}\n'
                    ),
                }
            ),
            instance_id="i-0123456789abcdef0",
            command_id="command-1",
        )
    assert captured.value.code is StopErrorCode.SAVE_FAILED


def test_command_poll_distinguishes_pending_and_success() -> None:
    assert (
        _command_result(
            Ssm({"Status": "InProgress"}),
            instance_id="i-0123456789abcdef0",
            command_id="command-1",
        )["complete"]
        is False
    )
    assert (
        _command_result(
            Ssm({"Status": "Success", "ResponseCode": 0}),
            instance_id="i-0123456789abcdef0",
            command_id="command-1",
        )["complete"]
        is True
    )


def test_dns_delete_is_idempotent_when_record_is_absent() -> None:
    api = Route53([])
    assert _delete_dns(api, Runtime()) == {"absent": True}  # type: ignore[arg-type]
    assert api.changes == []


def test_dns_delete_uses_exact_observed_record_and_waits_for_insync() -> None:
    record = {
        "Name": "mc-dev.wishicraft.net.",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": "203.0.113.10"}],
    }
    api = Route53([record])
    result = _delete_dns(api, Runtime())  # type: ignore[arg-type]
    assert result == {"absent": False, "change_id": "/change/change-1"}
    assert api.changes[0]["ChangeBatch"]["Changes"] == [  # type: ignore[index]
        {"Action": "DELETE", "ResourceRecordSet": record}
    ]
    assert _dns_change_complete(api, "/change/change-1")


def test_dns_pending_is_not_success() -> None:
    api = Route53([])
    api.change_status = "PENDING"
    assert not _dns_change_complete(api, "/change/change-1")
