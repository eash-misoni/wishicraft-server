from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import ModuleType, SimpleNamespace

import pytest

from wishicraft import stop_workflow_lambda
from wishicraft.operation import OperationStatus
from wishicraft.stop_workflow import StopErrorCode, StopWorkflowError
from wishicraft.stop_workflow_lambda import (
    _automatic_gate_reason,
    _command_result,
    _delete_dns,
    _dns_change_complete,
    _integer,
    _load_intent,
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


def test_stop_side_effects_publish_progress_only_after_lease_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None]] = []

    class Leases:
        def verify_owned(self, proof: object, *, now: object) -> None:
            del proof, now
            calls.append(("verify", None))

    class Operations:
        def update_step(self, **kwargs: object) -> None:
            calls.append(("progress", str(kwargs["current_step"])))

    class HostStop:
        def stop(self, *, instance_id: str) -> str:
            assert instance_id == "i-target"
            calls.append(("host_stop", None))
            return "command-1"

    class Ec2Stop:
        def stop_if_needed(self, *, instance_id: str, observation: object) -> bool:
            assert instance_id == "i-target"
            del observation
            calls.append(("ec2_stop", None))
            return True

    class Resolver:
        def resolve(self) -> str:
            return "i-target"

    route53 = Route53([])
    runtime = SimpleNamespace(
        system_id="wishicraft-main",
        coordinator=SimpleNamespace(leases=Leases()),
        operations=Operations(),
        host_stop=HostStop(),
        ec2_stop=Ec2Stop(),
        resolver=Resolver(),
        route53=route53,
        hosted_zone_id="ZONE",
        record_name="mc-dev.wishicraft.net",
    )
    monkeypatch.setattr(stop_workflow_lambda, "_runtime", runtime)
    base = {
        "schema_version": 1,
        "operation_id": "op-stop-001",
        "lease_id": "lease-stop-001",
    }

    assert stop_workflow_lambda.handler({**base, "action": "run_host_stop"}, None) == {
        "command_id": "command-1"
    }
    assert stop_workflow_lambda.handler(
        {
            **base,
            "action": "stop_ec2",
            "state": {
                "observation": {
                    "ec2_state": "running",
                    "ssm_state": "online",
                    "host_runtime_state": "not-running",
                    "minecraft_service_state": "not-running",
                    "minecraft_protocol_state": "not-applicable",
                    "public_ipv4": "203.0.113.10",
                    "dns_ipv4_values": ["203.0.113.10"],
                },
                "health": "DEGRADED",
                "observation_errors": [],
                "discrepancies": [],
            },
        },
        None,
    ) == {"stopped": True}
    assert stop_workflow_lambda.handler({**base, "action": "delete_dns"}, None) == {"absent": True}

    assert calls == [
        ("verify", None),
        ("progress", "HOST_RUNTIME_STOPPING"),
        ("host_stop", None),
        ("verify", None),
        ("progress", "EC2_STOPPING"),
        ("ec2_stop", None),
        ("verify", None),
        ("progress", "ENDPOINT_CLEANUP"),
    ]


def test_automatic_gate_cancels_and_releases_before_any_stop_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class Leases:
        def verify_owned(self, proof: object, *, now: object) -> None:
            calls.append(("verify", proof))

    class Operations:
        def complete_owned(self, **kwargs: object) -> None:
            calls.append(("complete", kwargs["status"]))

    runtime = SimpleNamespace(
        system_id="wishicraft-main",
        coordinator=SimpleNamespace(leases=Leases()),
        operations=Operations(),
    )
    monkeypatch.setattr(stop_workflow_lambda, "_runtime", runtime)
    monkeypatch.setattr(
        stop_workflow_lambda,
        "_automatic_gate_reason",
        lambda *args, **kwargs: "PLAYER_RECONNECTED",
    )
    monkeypatch.setattr(
        stop_workflow_lambda,
        "_cancel_intent",
        lambda *args, **kwargs: calls.append(("intent", kwargs["reason"])),
    )
    result = stop_workflow_lambda.handler(
        {
            "schema_version": 1,
            "action": "automatic_final_gate",
            "operation_id": "op-stop-001",
            "lease_id": "lease-001",
            "requested_by": "SCHEDULE",
            "auto_stop_intent_id": "asi-example",
            "state": {},
        },
        None,
    )
    assert result == {
        "proceed": False,
        "automatic": True,
        "reason": "PLAYER_RECONNECTED",
    }
    assert calls[1] == ("complete", OperationStatus.CANCELLED)
    assert calls[2] == ("intent", "PLAYER_RECONNECTED")


@pytest.mark.parametrize("value", [30, Decimal("30"), Decimal("30.0")])
def test_integer_decoder_accepts_exact_positive_integer_semantics(value: object) -> None:
    assert _integer({"value": value}, "value") == 30


@pytest.mark.parametrize(
    "value",
    [
        Decimal("30.5"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        True,
        30.0,
        "30",
        None,
    ],
)
def test_integer_decoder_rejects_non_integer_semantics(value: object) -> None:
    with pytest.raises(ValueError, match="invalid value"):
        _integer({"value": value}, "value")


def test_integer_decoder_rejects_missing_value() -> None:
    with pytest.raises(ValueError, match="invalid value"):
        _integer({}, "value")


def _intent_item(*, now: datetime, number: str = "30") -> dict[str, object]:
    empty_since = now - timedelta(minutes=31)
    delivered_at = now - timedelta(minutes=6)
    return {
        "game_id": {"S": "game-vanilla-main"},
        "intent_id": {"S": "asi-decimal-regression"},
        "boot_id": {"S": "boot-001"},
        "empty_since": {"S": empty_since.isoformat().replace("+00:00", "Z")},
        "idle_timeout_minutes": {"N": number},
        "warning_lead_minutes": {"N": "5"},
        "warning_delivery_id": {"S": "asw-decimal-regression"},
        "warning_delivery_state": {"S": "DELIVERED"},
        "warning_delivered_at": {"S": delivered_at.isoformat().replace("+00:00", "Z")},
        "status": {"S": "STOP_REQUESTED"},
        "created_at": {"S": empty_since.isoformat().replace("+00:00", "Z")},
        "updated_at": {"S": delivered_at.isoformat().replace("+00:00", "Z")},
        "block_reason": {"NULL": True},
    }


def _heartbeat_item(*, now: datetime) -> dict[str, object]:
    empty_since = now - timedelta(minutes=31)
    return {
        "system_id": {"S": "wishicraft-main"},
        "schema_version": {"N": "1"},
        "instance_id": {"S": "i-0123456789abcdef0"},
        "runtime_id": {"S": "wishicraft-host-runtime"},
        "boot_id": {"S": "boot-001"},
        "active_game_id": {"S": "game-vanilla-main"},
        "protocol_state": {"S": "ready"},
        "player_count": {"N": "0"},
        "empty_since": {"S": empty_since.isoformat().replace("+00:00", "Z")},
        "observed_at": {"S": now.isoformat().replace("+00:00", "Z")},
        "expires_at": {"N": str(int(now.timestamp()) + 86400)},
    }


def _install_type_deserializer(monkeypatch: pytest.MonkeyPatch) -> None:
    class TypeDeserializer:
        def deserialize(self, value: object) -> object:
            assert isinstance(value, dict)
            if "S" in value:
                return value["S"]
            if "N" in value:
                return Decimal(value["N"])
            if value.get("NULL") is True:
                return None
            raise AssertionError("unsupported test AttributeValue")

    boto3 = ModuleType("boto3")
    dynamodb = ModuleType("boto3.dynamodb")
    types = ModuleType("boto3.dynamodb.types")
    types.TypeDeserializer = TypeDeserializer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "boto3.dynamodb", dynamodb)
    monkeypatch.setitem(sys.modules, "boto3.dynamodb.types", types)


def test_real_attribute_values_decode_decimal_intent_and_pass_final_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_type_deserializer(monkeypatch)
    now = datetime(2026, 9, 10, 10, 45, tzinfo=UTC)
    intent_item = _intent_item(now=now)
    heartbeat_item = _heartbeat_item(now=now)

    class Dynamo:
        def get_item(self, **kwargs: object) -> object:
            table = kwargs["TableName"]
            return {"Item": intent_item if table == "intents" else heartbeat_item}

    class Resolver:
        def resolve(self) -> str:
            return "i-0123456789abcdef0"

    class Ec2:
        def describe_volumes(self, **kwargs: object) -> object:
            del kwargs
            return {
                "Volumes": [
                    {
                        "VolumeId": "vol-0123456789abcdef0",
                        "Attachments": [
                            {
                                "InstanceId": "i-0123456789abcdef0",
                                "Device": "/dev/sdf",
                                "State": "attached",
                                "DeleteOnTermination": False,
                            }
                        ],
                    }
                ]
            }

    direct = SimpleNamespace(
        ready=True,
        observed_active_game_id="game-vanilla-main",
        player_count=0,
    )
    runtime = SimpleNamespace(
        game_id="game-vanilla-main",
        system_id="wishicraft-main",
        runtime_id="wishicraft-host-runtime",
        intents_table="intents",
        heartbeats_table="heartbeats",
        dynamodb=Dynamo(),
        resolver=Resolver(),
        ec2=Ec2(),
        data_volume_id="vol-0123456789abcdef0",
        data_volume_device="/dev/sdf",
        status_factory=SimpleNamespace(
            create=lambda instance_id: SimpleNamespace(observe=lambda **kwargs: direct)
        ),
    )
    state = {
        "game_id": "game-vanilla-main",
        "desired_state": "RUNNING",
        "health": "HEALTHY",
        "discrepancies": [],
        "observation_errors": [],
        "target_instance_id": "i-0123456789abcdef0",
    }

    intent = _load_intent(runtime, "asi-decimal-regression")  # type: ignore[arg-type]
    assert intent.idle_timeout_minutes == 30
    assert intent.warning_lead_minutes == 5
    assert (
        _automatic_gate_reason(
            runtime,  # type: ignore[arg-type]
            {"state": state},
            intent_id="asi-decimal-regression",
            now=now,
        )
        is None
    )


def test_real_attribute_values_fail_closed_for_fractional_intent_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_type_deserializer(monkeypatch)
    now = datetime(2026, 9, 10, 10, 45, tzinfo=UTC)

    class Dynamo:
        def get_item(self, **kwargs: object) -> object:
            del kwargs
            return {"Item": _intent_item(now=now, number="30.5")}

    runtime = SimpleNamespace(
        game_id="game-vanilla-main", intents_table="intents", dynamodb=Dynamo()
    )
    with pytest.raises(ValueError, match="invalid idle_timeout_minutes"):
        _load_intent(runtime, "asi-decimal-regression")  # type: ignore[arg-type]
