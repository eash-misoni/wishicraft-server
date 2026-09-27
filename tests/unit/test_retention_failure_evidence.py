from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.retention_failure_evidence import CASES, collect, project

ROOT = Path(__file__).resolve().parents[2]
SECRET = "private-value-not-for-evidence"


class ReadOnly:
    region_name = "ap-northeast-1"
    mismatch = False
    fail = False

    def __init__(self) -> None:
        self.meta = SimpleNamespace(
            service_model=SimpleNamespace(shape_for=lambda _: SimpleNamespace(enum=["TaskFailed"]))
        )

    def client(self, _: str) -> "ReadOnly":
        return self

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": "385526546525"}

    def describe_table(self, **_: Any) -> dict[str, Any]:
        return {
            "Table": {
                "TableArn": "arn:aws:dynamodb:ap-northeast-1:385526546525:table/wc-dev-operations"
            }
        }

    def get_item(self, **args: Any) -> dict[str, Any]:
        op = args["Key"]["operation_id"]["S"]
        assert args["ConsistentRead"] is True
        return {
            "Item": {
                key: {"S": value}
                for key, value in {
                    "operation_id": op,
                    "operation_type": "START" if self.mismatch else CASES[op],
                    "workflow_execution_arn": (
                        "arn:aws:states:ap-northeast-1:385526546525:execution:"
                        f"wc-dev-{CASES[op].lower()}:{op}"
                    ),
                    "status": "FAILED",
                    "requested_at": "2026-09-07T08:38:29.797365Z",
                    "completed_at": "2026-09-07T08:38:35.736752Z",
                    "recovery_json": '{"runtime_env":"' + SECRET + '"}',
                }.items()
            }
        }

    def describe_execution(self, **args: Any) -> dict[str, str]:
        arn = args["executionArn"]
        return {
            "executionArn": arn,
            "name": arn.split(":")[-1],
            "status": "FAILED",
            "input": SECRET,
        }

    def lookup_events(self, **_: Any) -> dict[str, Any]:
        return {"Events": []}

    def get_execution_history(self, **_: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError(SECRET)
        return {
            "events": [
                {
                    "id": 1,
                    "type": "TaskFailed",
                    "timestamp": datetime.now(UTC),
                    "cause": '{"error":"UnauthorizedOperation","secret":"' + SECRET + '"}',
                }
            ]
        }


def test_projection_omits_wire_nested_payloads() -> None:
    result = project(
        {
            "Environment": {"Variables": {"TOKEN": SECRET}},
            "M": {"payload": {"S": '{"credentials":"' + SECRET + '","error":"ValueError"}'}},
        }
    )
    assert SECRET not in str(result)
    assert result["errors"] == ["ValueError"]


@pytest.mark.parametrize("failure", [False, True])
def test_collection_never_resolves_failed_or_exposes_errors(failure: bool, capsys: Any) -> None:
    client = ReadOnly()
    client.fail = failure
    result = collect(client, ROOT)
    assert SECRET not in str(result) + str(capsys.readouterr())
    assert result["automatic_resolution"] is False
    assert result["status"] == "NO_DELETE"
    assert result["planned_delete_ids"] == []
    assert result["deletion_authorized"] is False
    for item in result["operations"]:
        assert item["identity_matches"]
        assert bool(item["issues"]) == failure
        assert "side_effect_free" not in item


def test_same_id_with_wrong_target_type_does_not_follow_execution() -> None:
    client = ReadOnly()
    client.mismatch = True
    result = collect(client, ROOT)
    assert all(not item["identity_matches"] for item in result["operations"])
    assert all(not item["history"] for item in result["operations"])


def test_new_reference_remains_visible_and_is_not_resolved() -> None:
    old = project({"status": "FAILED"})
    new = project({"status": "FAILED", "backup_snapshot_id": "snap-0123456789abcdef0"})
    assert new != old
    assert new["snapshot_ids"] == ["snap-0123456789abcdef0"]
    assert "resolved" not in new


def test_cloudtrail_projection_and_exception_do_not_save_raw(capsys: Any) -> None:
    import json

    class Trail(ReadOnly):
        def lookup_events(self, **_: Any) -> dict[str, Any]:
            return {
                "Events": [
                    {
                        "CloudTrailEvent": json.dumps(
                            {
                                "eventID": "79df13b0-e4a9-4d98-b471-a8be51ea2c10",
                                "eventTime": "2026-09-07T08:38:35Z",
                                "recipientAccountId": "385526546525",
                                "awsRegion": "ap-northeast-1",
                                "userIdentity": {"credentials": SECRET},
                                "errorMessage": SECRET,
                                "requestParameters": {"volumeId": "vol-03ac9f534326c345c"},
                                "errorCode": "Client.UnauthorizedOperation",
                            }
                        )
                    }
                ]
            }

    result = collect(Trail(), ROOT)
    assert SECRET not in str(result) + str(capsys.readouterr())
    for record in result["operations"]:
        assert record["cloudtrail"][0]["records"][0]["explicit_denial"]
        assert record["cloudtrail"][0]["records"][0]["account_region_matches"]


def test_history_token_cycle_is_not_complete() -> None:
    class Cycling(ReadOnly):
        def get_execution_history(self, **_: Any) -> dict[str, Any]:
            return {"events": [], "nextToken": SECRET}

    result = collect(Cycling(), ROOT)
    assert SECRET not in str(result)
    assert all(item["issues"] and not item.get("history_complete") for item in result["operations"])


def test_absent_history_is_not_proof_of_no_side_effects() -> None:
    class Empty(ReadOnly):
        def get_execution_history(self, **_: Any) -> dict[str, Any]:
            return {"events": []}

    result = collect(Empty(), ROOT)
    assert result["automatic_resolution"] is False
    assert all(item["history"] == [] for item in result["operations"])
