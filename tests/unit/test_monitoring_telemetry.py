from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from boto3.dynamodb.types import TypeSerializer  # type: ignore[import-untyped]

from wishicraft import monitoring_lambda
from wishicraft.monitoring_telemetry import evaluate_telemetry, integer, timestamp

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
INSTANCE = "i-04fc0629dc4ea466e"
BOOT = "12345678-1234-1234-1234-123456789abc"
VOLUME = "vol-03ac9f534326c345c"
UUID = "420cea6d-0520-4436-bb5a-db1191f1e63b"


def inputs() -> dict[str, Any]:
    return {
        "state": {
            "system_id": "wishicraft-main",
            "game_id": "game-vanilla-main",
            "desired_state": "RUNNING",
            "desired_updated_at": (NOW - timedelta(hours=1)).isoformat(),
            "desired_revision": 42,
            "current_operation_id": None,
            "target_instance_id": INSTANCE,
            "observed_at": NOW.isoformat(),
            "health": "HEALTHY",
            "discrepancies": [],
            "observation_errors": [],
            "observation": {
                "runtime_ready": True,
                "ec2_state": "running",
                "telemetry": {
                    "schema_version": 1,
                    "observed_at": NOW.isoformat(),
                    "boot_id": BOOT,
                    "state": "observed",
                    "error": None,
                    "mount_path": "/srv/minecraft",
                    "source": "/dev/nvme1n1",
                    "volume_id": VOLUME,
                    "filesystem_uuid": UUID,
                    "total_bytes": 1000,
                    "used_bytes": 750,
                    "available_bytes": 200,
                },
            },
        },
        "heartbeat": {
            "schema_version": 1,
            "system_id": "wishicraft-main",
            "instance_id": INSTANCE,
            "runtime_id": "wishicraft-host-runtime",
            "boot_id": BOOT,
            "active_game_id": "game-vanilla-main",
            "protocol_state": "ready",
            "player_count": 0,
            "observed_at": NOW.isoformat(),
            "expires_at": 0,
        },
        "lock": {},
        "instance": {
            "InstanceId": INSTANCE,
            "State": {"Name": "running"},
            "LaunchTime": NOW - timedelta(hours=1),
        },
        "now": NOW,
        "system_id": "wishicraft-main",
        "game_id": "game-vanilla-main",
        "volume_id": VOLUME,
        "filesystem_uuid": UUID,
        "mount_path": "/srv/minecraft",
        "observation_freshness_seconds": 600,
        "startup_grace_seconds": 600,
        "shutdown_grace_seconds": 420,
        "usage_warning_percent": 80,
    }


def test_capacity_uses_available_space_and_ttl_never_controls_freshness() -> None:
    metrics, reasons = evaluate_telemetry(**inputs())
    assert reasons == {"heartbeat": "fresh", "runtime": "ready", "filesystem": "observed"}
    assert metrics["DataFilesystemUsagePercent"] == pytest.approx(100 * 750 / 950)
    assert metrics["DataFilesystemUsageHigh"] == 0


@pytest.mark.parametrize("age,expected", [(299.9, 0), (300, 0), (300.1, 1), (-0.1, 1)])
def test_heartbeat_exact_freshness_boundary(age: float, expected: int) -> None:
    values = inputs()
    values["heartbeat"]["observed_at"] = (NOW - timedelta(seconds=age)).isoformat()
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["RuntimeHeartbeatUnavailable"] == expected


def test_missing_heartbeat_is_not_zero_players_or_zero_capacity() -> None:
    values = inputs()
    values["heartbeat"] = {}
    metrics, reasons = evaluate_telemetry(**values)
    assert reasons["heartbeat"] == "missing"
    assert metrics["RuntimeHeartbeatUnavailable"] == 1
    assert metrics["RuntimeObservationUnknown"] == 1
    assert "DataFilesystemUsagePercent" not in metrics


def test_fresh_unknown_runtime_is_separate_from_heartbeat_and_system_state_stale() -> None:
    values = inputs()
    values["heartbeat"]["protocol_state"] = "unknown"
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["RuntimeHeartbeatUnavailable"] == 0
    assert metrics["RuntimeObservationUnknown"] == 1
    assert metrics["SystemStateObservationStale"] == 0
    values["heartbeat"]["protocol_state"] = "ready"
    values["state"]["observed_at"] = (NOW - timedelta(seconds=601)).isoformat()
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["RuntimeObservationUnknown"] == 0
    assert metrics["SystemStateObservationStale"] == 1
    assert metrics["DataFilesystemObservationUnknown"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ("runtime_id", "other"),
        ("instance_id", "i-other"),
        ("active_game_id", "game-other"),
    ],
)
def test_identity_mismatch(field: str, value: str) -> None:
    values = inputs()
    values["heartbeat"][field] = value
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["RuntimeIdentityMismatch"] == 1
    assert "DataFilesystemUsagePercent" not in metrics


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "unknown"),
        ("volume_id", "vol-other"),
        ("mount_path", "/"),
        ("source", "/dev/root"),
        ("filesystem_uuid", "other"),
        ("used_bytes", None),
        ("used_bytes", True),
        ("total_bytes", 0),
        ("available_bytes", -1),
        ("available_bytes", Decimal("1.5")),
        ("error", "FAILED"),
        ("observed_at", "invalid"),
    ],
)
def test_untrusted_capacity_never_publishes_percent(field: str, value: object) -> None:
    values = inputs()
    values["state"]["observation"]["telemetry"][field] = value
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["DataFilesystemObservationUnknown"] == 1
    assert "DataFilesystemUsagePercent" not in metrics


@pytest.mark.parametrize("state", ["stopped", "pending", "stopping"])
def test_ec2_stopped_or_transient_has_no_capacity_value(state: str) -> None:
    values = inputs()
    values["instance"]["State"]["Name"] = state
    values["state"]["desired_state"] = "STOPPED" if state != "pending" else "RUNNING"
    metrics, reasons = evaluate_telemetry(**values)
    assert metrics["RuntimeHeartbeatUnavailable"] == 0
    assert "DataFilesystemUsagePercent" not in metrics
    assert reasons["filesystem"] in {"transition", "not-expected"}


@pytest.mark.parametrize("desired,limit", [("RUNNING", 600), ("STOPPED", 420)])
def test_grace_requires_owned_unexpired_operation_and_ends_at_boundary(
    desired: str, limit: int
) -> None:
    values = inputs()
    values["heartbeat"] = {}
    values["state"].update(
        desired_state=desired,
        current_operation_id="op-test",
        desired_updated_at=(NOW - timedelta(seconds=limit - 1)).isoformat(),
    )
    values["lock"] = {
        "owner_operation_id": "op-test",
        "lease_expires_at": Decimal(str(int(NOW.timestamp()) + 60)),
    }
    assert evaluate_telemetry(**values)[0]["RuntimeHeartbeatUnavailable"] == 0
    values["state"]["desired_updated_at"] = (NOW - timedelta(seconds=limit)).isoformat()
    assert evaluate_telemetry(**values)[0]["RuntimeHeartbeatUnavailable"] == 1


@pytest.mark.parametrize("used,available,expected", [(799, 201, 0), (800, 200, 1), (0, 1000, 0)])
def test_usage_warning_boundary_and_real_zero(used: int, available: int, expected: int) -> None:
    values = inputs()
    values["state"]["observation"]["telemetry"].update(used_bytes=used, available_bytes=available)
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["DataFilesystemUsageHigh"] == expected


@pytest.mark.parametrize(
    "value", [None, True, 1.0, "1", Decimal("1.1"), Decimal("NaN"), Decimal("Infinity")]
)
def test_integer_decoder_rejects_unknown_and_lossy_values(value: object) -> None:
    assert integer(value) is None


def test_timestamp_requires_timezone() -> None:
    assert timestamp("2026-09-10T12:00:00") is None


def test_unknown_capacity_does_not_emit_false_recovery_after_high_usage() -> None:
    values = inputs()
    telemetry = values["state"]["observation"]["telemetry"]
    telemetry.update(used_bytes=900, available_bytes=100)
    assert evaluate_telemetry(**values)[0]["DataFilesystemUsageHigh"] == 1
    telemetry["used_bytes"] = None
    unknown, _ = evaluate_telemetry(**values)
    assert "DataFilesystemUsageHigh" not in unknown
    assert unknown["DataFilesystemObservationUnknown"] == 1
    telemetry.update(used_bytes=700, available_bytes=300)
    assert evaluate_telemetry(**values)[0]["DataFilesystemUsageHigh"] == 0


@pytest.mark.parametrize("count", [None, True, Decimal("0.5"), -1])
def test_unknown_player_count_is_not_trusted_zero(count: object) -> None:
    values = inputs()
    values["heartbeat"]["player_count"] = count
    metrics, _ = evaluate_telemetry(**values)
    assert metrics["RuntimeHeartbeatUnavailable"] == 0
    assert metrics["RuntimeObservationUnknown"] == 1


class Aws:
    def __init__(self, values: dict[str, Any], *, fail_metrics: bool = False) -> None:
        self.values = values
        self.fail_metrics = fail_metrics
        self.published: list[dict[str, Any]] = []

    def client(self, name: str) -> Aws:
        assert name in {"dynamodb", "ec2", "cloudwatch"}
        return self

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["ConsistentRead"] is True
        item = self.values[kwargs["TableName"]]
        return {"Item": {key: TypeSerializer().serialize(value) for key, value in item.items()}}

    def describe_instances(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["InstanceIds"] == [INSTANCE]
        return {"Reservations": [{"Instances": [self.values["instance"]]}]}

    def put_metric_data(self, **kwargs: Any) -> None:
        if self.fail_metrics:
            raise RuntimeError("metric publication failed")
        self.published.append(kwargs)


def setup_handler(monkeypatch: pytest.MonkeyPatch, *, fail_metrics: bool = False) -> Aws:
    values = inputs()
    values["lock"] = {"lease_expires_at": int(NOW.timestamp()) - 1}
    aws = Aws(values, fail_metrics=fail_metrics)
    monkeypatch.setattr(monitoring_lambda, "boto3", aws)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Clock:
            return cls.fromtimestamp(NOW.timestamp(), tz=UTC)

    monkeypatch.setattr(monitoring_lambda, "datetime", Clock)
    for key, value in {
        "SYSTEM_STATE_TABLE": "state",
        "LOCKS_TABLE": "lock",
        "RUNTIME_HEARTBEATS_TABLE": "heartbeat",
        "SYSTEM_ID": "wishicraft-main",
        "GLOBAL_LOCK_NAME": "minecraft-control",
        "STAGE": "dev",
        "METRIC_NAMESPACE": "Wishicraft/ControlPlane",
        "GAME_ID": "game-vanilla-main",
        "DATA_VOLUME_ID": VOLUME,
        "DATA_FILESYSTEM_UUID": UUID,
        "DATA_MOUNT_PATH": "/srv/minecraft",
        "EC2_RUNNING_WARNING_SECONDS": "28800",
        "DESIRED_STOPPED_RUNNING_WARNING_SECONDS": "900",
        "DESIRED_RUNNING_NOT_READY_WARNING_SECONDS": "1200",
        "OBSERVATION_FRESHNESS_SECONDS": "600",
        "MONITORING_STARTUP_GRACE_SECONDS": "600",
        "MONITORING_SHUTDOWN_GRACE_SECONDS": "420",
        "DATA_USAGE_WARNING_PERCENT": "80",
    }.items():
        monkeypatch.setenv(key, value)
    return aws


def test_real_handler_decodes_attribute_values_decimal_and_publishes_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aws = setup_handler(monkeypatch)
    result = monitoring_lambda.handler({}, None)
    assert result["metric_count"] == 16
    metrics = {metric["MetricName"]: metric for metric in aws.published[0]["MetricData"]}
    assert metrics["ExpiredOperationLock"]["Value"] == 1
    assert metrics["DataFilesystemUsedBytes"]["Value"] == 750
    assert metrics["DataFilesystemUsedBytes"]["Unit"] == "Bytes"
    assert metrics["DataFilesystemUsagePercent"]["Unit"] == "Percent"
    assert metrics["RuntimeHeartbeatUnavailable"]["Value"] == 0


def test_metric_publication_failure_propagates_to_lambda_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_handler(monkeypatch, fail_metrics=True)
    with pytest.raises(RuntimeError, match="metric publication failed"):
        monitoring_lambda.handler({}, None)


@pytest.mark.parametrize(
    "key",
    [
        "GAME_ID",
        "DATA_VOLUME_ID",
        "DATA_FILESYSTEM_UUID",
        "DATA_MOUNT_PATH",
        "MONITORING_STARTUP_GRACE_SECONDS",
        "MONITORING_SHUTDOWN_GRACE_SECONDS",
        "DATA_USAGE_WARNING_PERCENT",
    ],
)
def test_handler_missing_required_configuration_does_not_publish_success(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    aws = setup_handler(monkeypatch)
    monkeypatch.delenv(key)
    with pytest.raises(KeyError):
        monitoring_lambda.handler({}, None)
    assert not aws.published
