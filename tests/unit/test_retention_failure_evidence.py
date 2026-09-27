from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.retention_failure_evidence import CASES, collect, match_create_snapshot_event, project

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


def test_terminal_retention_codes_remain_visible() -> None:
    assert project({"error": {"code": "RETENTION_DRY_RUN_FAILED"}})["errors"] == [
        "RETENTION_DRY_RUN_FAILED"
    ]


VOLUME = "vol-03ac9f534326c345c"
OPERATION = "op-433438bf-d775-4799-8016-ff0bdcb361a7"


def create_event() -> dict[str, Any]:
    return {
        "eventSource": "ec2.amazonaws.com",
        "eventName": "CreateSnapshot",
        "recipientAccountId": "385526546525",
        "awsRegion": "ap-northeast-1",
        "requestParameters": {
            "volumeId": VOLUME,
            "description": SECRET,
            "tagSpecificationSet": {
                "items": [
                    {
                        "resourceType": "snapshot",
                        "tags": [{"key": "WishicraftOperationId", "value": OPERATION}],
                    }
                ]
            },
        },
    }


def matches(event: object) -> dict[str, Any]:
    return match_create_snapshot_event(
        event,
        operation_id=OPERATION,
        volume_id=VOLUME,
        account="385526546525",
        region="ap-northeast-1",
    )


def test_exact_create_snapshot_fields() -> None:
    result = matches(create_event())
    assert result["target_matches"]
    assert result["operation_tag_matches"] and result["source_volume_matches"]
    assert result["account_region_matches"] and result["event_source_name_matches"]
    assert result["match_issues"] == []
    assert SECRET not in str(result)


@pytest.mark.parametrize("location", ["description", "other-tag", "other-resource"])
def test_operation_id_in_other_fields_is_not_operation_tag(location: str) -> None:
    event = create_event()
    request = event["requestParameters"]
    item = request["tagSpecificationSet"]["items"][0]
    item["tags"] = []
    if location == "description":
        request["description"] = OPERATION
    elif location == "other-tag":
        item["tags"] = [{"key": "Unrelated", "value": OPERATION}]
    else:
        item["resourceType"] = "volume"
        item["tags"] = [{"key": "WishicraftOperationId", "value": OPERATION}]
    result = matches(event)
    assert not result["operation_tag_matches"] and not result["target_matches"]
    assert result["match_issues"]


def test_other_volume_cannot_match_description_or_unrelated_tags() -> None:
    event = create_event()
    request = event["requestParameters"]
    request["volumeId"] = "vol-0123456789abcdef0"
    request["description"] = VOLUME + OPERATION
    request["tagSpecificationSet"]["items"][0]["tags"] = [
        {"key": "UnrelatedOperation", "value": OPERATION},
        {"key": "UnrelatedVolume", "value": VOLUME},
    ]
    result = matches(event)
    assert not result["source_volume_matches"]
    assert not result["operation_tag_matches"] and not result["target_matches"]


@pytest.mark.parametrize("field", ["volume", "operation"])
@pytest.mark.parametrize("prefix,suffix", [("prefix-", ""), ("", "-suffix")])
def test_substring_values_do_not_match(field: str, prefix: str, suffix: str) -> None:
    event = create_event()
    request = event["requestParameters"]
    if field == "volume":
        request["volumeId"] = prefix + VOLUME + suffix
    else:
        request["tagSpecificationSet"]["items"][0]["tags"][0]["value"] = prefix + OPERATION + suffix
    assert not matches(event)["target_matches"]


@pytest.mark.parametrize(
    "case",
    [
        "missing-request",
        "string-request",
        "missing-volume",
        "invalid-volume",
        "missing-specifications",
        "invalid-items",
        "empty-items",
        "duplicate-specifications",
        "missing-tags",
        "invalid-tags",
        "invalid-tag",
        "missing-tag-value",
        "invalid-tag-value",
        "duplicate-same",
        "duplicate-conflicting",
        "duplicate-other-key",
    ],
)
def test_incomplete_or_ambiguous_shape_is_not_a_match(case: str) -> None:
    event = create_event()
    request = event["requestParameters"]
    items = request["tagSpecificationSet"]["items"]
    tags = items[0]["tags"]
    if case == "missing-request":
        del event["requestParameters"]
    elif case == "string-request":
        event["requestParameters"] = str(request)
    elif case == "missing-volume":
        del request["volumeId"]
    elif case == "invalid-volume":
        request["volumeId"] = [VOLUME]
    elif case == "missing-specifications":
        del request["tagSpecificationSet"]
    elif case == "invalid-items":
        request["tagSpecificationSet"]["items"] = items[0]
    elif case == "empty-items":
        items.clear()
    elif case == "duplicate-specifications":
        items.append(dict(items[0]))
    elif case == "missing-tags":
        del items[0]["tags"]
    elif case == "invalid-tags":
        items[0]["tags"] = {"WishicraftOperationId": OPERATION}
    elif case == "invalid-tag":
        tags.append(SECRET)
    elif case == "missing-tag-value":
        del tags[0]["value"]
    elif case == "invalid-tag-value":
        tags[0]["value"] = [OPERATION]
    elif case == "duplicate-same":
        tags.append(dict(tags[0]))
    elif case == "duplicate-conflicting":
        tags.append({"key": "WishicraftOperationId", "value": SECRET})
    else:
        tags.extend([{"key": "Other", "value": SECRET}] * 2)
    result = matches(event)
    assert not result["target_matches"] and result["match_issues"]
    assert SECRET not in str(result)


@pytest.mark.parametrize("field", ["eventSource", "eventName", "recipientAccountId", "awsRegion"])
@pytest.mark.parametrize("value", [None, "wrong", ["ec2.amazonaws.com"]])
def test_event_identity_mismatch_is_not_target_match(field: str, value: Any) -> None:
    event = create_event()
    event[field] = value
    result = matches(event)
    assert not result["target_matches"] and result["match_issues"]


@pytest.mark.parametrize("attack", [False, True])
def test_collector_uses_exact_match_and_saves_no_raw_values(attack: bool, tmp_path: Path) -> None:
    import json

    from tools.retention_inventory import save

    class Trail(ReadOnly):
        def lookup_events(self, **_: Any) -> dict[str, Any]:
            event = create_event()
            event.update(
                eventID="79df13b0-e4a9-4d98-b471-a8be51ea2c10",
                eventTime="2026-09-07T08:38:35Z",
                credentials=SECRET,
                Environment={"Variables": {"TOKEN": SECRET}},
                errorMessage=SECRET,
            )
            if attack:
                request = event["requestParameters"]
                request["volumeId"] = "vol-0123456789abcdef0"
                request["description"] = VOLUME + OPERATION
                request["tagSpecificationSet"]["items"][0]["tags"] = []
            return {"Events": [{"CloudTrailEvent": json.dumps(event)}]}

    result = collect(Trail(), ROOT)
    record = result["operations"][0]["cloudtrail"][0]["records"][0]
    assert record["target_matches"] is not attack
    path = tmp_path / "projection.json"
    save(path, result)
    assert SECRET not in path.read_text()
    assert result["planned_delete_ids"] == [] and not result["deletion_authorized"]


def test_cloudtrail_exception_is_not_persisted(tmp_path: Path, capsys: Any) -> None:
    from tools.retention_inventory import save

    class Trail(ReadOnly):
        def lookup_events(self, **_: Any) -> dict[str, Any]:
            raise RuntimeError(SECRET)

    result = collect(Trail(), ROOT)
    path = tmp_path / "failed-read.json"
    save(path, result)
    assert SECRET not in path.read_text() + str(capsys.readouterr())
    assert all(op["cloudtrail"][0]["issues"] for op in result["operations"])
