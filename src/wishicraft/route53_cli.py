"""Restricted Phase 1 Route 53 management for one configured Minecraft record."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wishicraft.config import Configuration, ConfigValidationError, load_configuration

AwsCall = Callable[[str, str, list[str]], dict[str, Any]]
Clock = Callable[[], float]
Sleep = Callable[[float], None]

_INSTANCE_ID = re.compile(r"^i-(?:[0-9a-f]{8}|[0-9a-f]{17})$")
_HOSTED_ZONE_ID = re.compile(r"^Z[A-Z0-9]{1,31}$")
_POLL_INTERVAL_SECONDS = 2.0


class Route53CliError(RuntimeError):
    """An expected operational or validation failure of this restricted CLI."""


@dataclass(frozen=True)
class Route53Result:
    stage: str
    action: str
    account: str
    region: str
    stack: str
    instance_id: str | None
    hosted_zone_id: str
    record_name: str
    record_type: str
    ttl: int
    public_ipv4: str | None
    changed: bool
    change_id: str | None
    final_status: str


@dataclass(frozen=True)
class Route53Settings:
    stage: str
    account: str
    region: str
    stack: str
    hosted_zone_id: str
    record_name: str
    record_type: str
    ttl: int
    timeout: int
    expected_tags: Mapping[str, str]


def _aws(profile: str, region: str, arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", "--profile", profile, "--region", region, *arguments, "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Route53CliError("AWS CLI request failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise Route53CliError("AWS CLI returned invalid JSON") from error
    if not isinstance(value, dict):
        raise Route53CliError("AWS CLI response was not an object")
    return value


def _normalized_name(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Route53CliError(f"{label} is missing or invalid")
    name = value.strip().lower().rstrip(".")
    if not name or any(character.isspace() for character in name):
        raise Route53CliError(f"{label} is missing or invalid")
    return f"{name}."


def _settings(configuration: Configuration) -> Route53Settings:
    stage = configuration.stage
    project = configuration.project
    try:
        hosted_zone_id = stage.route53_hosted_zone_id
        record_name = _normalized_name(stage.route53_record_name, label="Route 53 record name")
        record_type = project.route53_record_type
        ttl = project.route53_ttl_seconds
        timeout = stage.route53_insync_timeout_seconds
        account = stage.aws_account_id
        region = stage.aws_region
    except (AssertionError, ConfigValidationError) as error:
        raise Route53CliError("stage configuration is incomplete") from error
    if not _HOSTED_ZONE_ID.fullmatch(hosted_zone_id):
        raise Route53CliError("Route 53 hosted zone ID is missing or invalid")
    if record_type != "A":
        raise Route53CliError("Phase 1 Route 53 record type must be A")
    raw_tags = project.values.get("resource_tags")
    if not isinstance(raw_tags, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw_tags.items()
    ):
        raise Route53CliError("project resource tags are invalid")
    expected_tags = {
        key: value
        for key, value in raw_tags.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    return Route53Settings(
        stage=stage.stage,
        account=account,
        region=region,
        stack=f"{project.stack_name}-{stage.stage}",
        hosted_zone_id=hosted_zone_id,
        record_name=record_name,
        record_type=record_type,
        ttl=ttl,
        timeout=timeout,
        expected_tags={**expected_tags, "Stage": stage.stage},
    )


def _require_caller_account(settings: Route53Settings, profile: str, aws: AwsCall) -> None:
    account = aws(profile, settings.region, ["sts", "get-caller-identity"]).get("Account")
    if account != settings.account:
        raise Route53CliError("caller account differs from configured stage account")


def _require_hosted_zone(settings: Route53Settings, profile: str, aws: AwsCall) -> None:
    response = aws(
        profile, settings.region, ["route53", "get-hosted-zone", "--id", settings.hosted_zone_id]
    )
    zone = response.get("HostedZone")
    if not isinstance(zone, dict):
        raise Route53CliError("Route 53 hosted zone response is invalid")
    zone_name = _normalized_name(zone.get("Name"), label="Route 53 hosted zone name")
    record = settings.record_name.rstrip(".")
    zone_suffix = zone_name.rstrip(".")
    if record == zone_suffix or not record.endswith(f".{zone_suffix}"):
        raise Route53CliError("configured record name is outside the configured hosted zone")


def _resolve_instance(settings: Route53Settings, profile: str, aws: AwsCall) -> tuple[str, str]:
    stack_response = aws(
        profile,
        settings.region,
        ["cloudformation", "describe-stacks", "--stack-name", settings.stack],
    )
    stacks = stack_response.get("Stacks")
    if not isinstance(stacks, list) or len(stacks) != 1 or not isinstance(stacks[0], dict):
        raise Route53CliError("CloudFormation stack response is invalid")
    outputs = stacks[0].get("Outputs")
    if not isinstance(outputs, list):
        raise Route53CliError("Minecraft instance output is missing")
    instance_ids = [
        output.get("OutputValue")
        for output in outputs
        if isinstance(output, dict) and output.get("OutputKey") == "MinecraftInstanceId"
    ]
    if (
        len(instance_ids) != 1
        or not isinstance(instance_ids[0], str)
        or not _INSTANCE_ID.fullmatch(instance_ids[0])
    ):
        raise Route53CliError("Minecraft instance output is missing or invalid")
    instance_id = instance_ids[0]
    ec2_response = aws(
        profile, settings.region, ["ec2", "describe-instances", "--instance-ids", instance_id]
    )
    reservations = ec2_response.get("Reservations")
    if not isinstance(reservations, list):
        raise Route53CliError("EC2 instance response is invalid")
    instances = [
        instance
        for reservation in reservations
        if isinstance(reservation, dict)
        for instance in reservation.get("Instances", [])
        if isinstance(instance, dict)
    ]
    if len(instances) != 1 or instances[0].get("InstanceId") != instance_id:
        raise Route53CliError(
            "Minecraft instance response did not contain exactly the configured instance"
        )
    instance = instances[0]
    if instance.get("State", {}).get("Name") != "running":
        raise Route53CliError("Minecraft instance is not running")
    tags = {
        tag.get("Key"): tag.get("Value")
        for tag in instance.get("Tags", [])
        if isinstance(tag, dict)
        and isinstance(tag.get("Key"), str)
        and isinstance(tag.get("Value"), str)
    }
    if any(tags.get(key) != value for key, value in settings.expected_tags.items()):
        raise Route53CliError(
            "Minecraft instance tags do not match the configured project and stage"
        )
    address = instance.get("PublicIpAddress")
    if not isinstance(address, str):
        raise Route53CliError("Minecraft public IPv4 is missing or invalid")
    try:
        parsed_address = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as error:
        raise Route53CliError("Minecraft public IPv4 is missing or invalid") from error
    if not parsed_address.is_global:
        raise Route53CliError("Minecraft public IPv4 is not globally routable")
    return instance_id, str(parsed_address)


def _find_record(settings: Route53Settings, profile: str, aws: AwsCall) -> dict[str, Any] | None:
    response = aws(
        profile,
        settings.region,
        [
            "route53",
            "list-resource-record-sets",
            "--hosted-zone-id",
            settings.hosted_zone_id,
            "--start-record-name",
            settings.record_name,
            "--start-record-type",
            settings.record_type,
            "--max-items",
            "1",
        ],
    )
    records = response.get("ResourceRecordSets")
    if not isinstance(records, list):
        raise Route53CliError("Route 53 record response is invalid")
    for record in records:
        if not isinstance(record, dict):
            continue
        if (
            _normalized_name(record.get("Name"), label="Route 53 record name")
            == settings.record_name
            and record.get("Type") == settings.record_type
        ):
            return record
    return None


def _require_simple_record(record: Mapping[str, Any], *, expected_ipv4: str | None = None) -> None:
    complex_fields = (
        "AliasTarget",
        "SetIdentifier",
        "Failover",
        "GeoLocation",
        "Region",
        "Weight",
        "MultiValueAnswer",
        "CidrRoutingConfig",
        "HealthCheckId",
    )
    if any(field in record for field in complex_fields):
        raise Route53CliError("refusing complex Route 53 record")
    ttl = record.get("TTL")
    values = record.get("ResourceRecords")
    if not isinstance(ttl, int) or ttl <= 0 or not isinstance(values, list) or len(values) != 1:
        raise Route53CliError("refusing unexpected Route 53 record")
    value = values[0]
    if not isinstance(value, dict) or not isinstance(value.get("Value"), str):
        raise Route53CliError("refusing unexpected Route 53 record")
    try:
        address = ipaddress.IPv4Address(value["Value"])
    except ipaddress.AddressValueError as error:
        raise Route53CliError("refusing unexpected Route 53 record") from error
    if not address.is_global or (expected_ipv4 is not None and str(address) != expected_ipv4):
        raise Route53CliError("refusing unexpected Route 53 record")


def _desired_record(settings: Route53Settings, address: str) -> dict[str, Any]:
    return {
        "Name": settings.record_name,
        "Type": settings.record_type,
        "TTL": settings.ttl,
        "ResourceRecords": [{"Value": address}],
    }


def _wait_change(
    settings: Route53Settings,
    profile: str,
    change_id: str,
    aws: AwsCall,
    *,
    clock: Clock = time.monotonic,
    sleep: Sleep = time.sleep,
) -> str:
    deadline = clock() + settings.timeout
    while True:
        response = aws(profile, settings.region, ["route53", "get-change", "--id", change_id])
        change = response.get("ChangeInfo")
        status = change.get("Status") if isinstance(change, dict) else None
        if status == "INSYNC":
            return status
        if status != "PENDING":
            raise Route53CliError("Route 53 change response is invalid")
        remaining = deadline - clock()
        if remaining <= 0:
            raise Route53CliError("Route 53 change did not reach INSYNC before timeout")
        sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _change_record(
    settings: Route53Settings,
    profile: str,
    action: str,
    record: Mapping[str, Any],
    aws: AwsCall,
) -> str:
    response = aws(
        profile,
        settings.region,
        [
            "route53",
            "change-resource-record-sets",
            "--hosted-zone-id",
            settings.hosted_zone_id,
            "--change-batch",
            json.dumps({"Changes": [{"Action": action, "ResourceRecordSet": record}]}),
        ],
    )
    change = response.get("ChangeInfo")
    change_id = change.get("Id") if isinstance(change, dict) else None
    if not isinstance(change_id, str) or not change_id:
        raise Route53CliError("Route 53 change ID is missing")
    return change_id


def manage(
    configuration: Configuration,
    operation: str,
    profile: str,
    *,
    aws: AwsCall = _aws,
    clock: Clock = time.monotonic,
    sleep: Sleep = time.sleep,
) -> Route53Result:
    """Apply one allowlisted DNS operation without accepting mutable target inputs."""
    if operation not in {"UPSERT", "DELETE"}:
        raise Route53CliError("operation must be UPSERT or DELETE")
    if not profile:
        raise Route53CliError("AWS profile is required")
    settings = _settings(configuration)
    _require_caller_account(settings, profile, aws)
    _require_hosted_zone(settings, profile, aws)
    if operation == "UPSERT":
        instance_id, address = _resolve_instance(settings, profile, aws)
        desired = _desired_record(settings, address)
        current = _find_record(settings, profile, aws)
        if current is not None:
            _require_simple_record(current)
            if current == desired:
                return Route53Result(
                    **_result_values(
                        settings, operation, instance_id, address, False, None, "INSYNC"
                    )
                )
        change_id = _change_record(settings, profile, operation, desired, aws)
        status = _wait_change(settings, profile, change_id, aws, clock=clock, sleep=sleep)
        final = _find_record(settings, profile, aws)
        if final != desired:
            raise Route53CliError("Route 53 UPSERT postcondition failed")
        return Route53Result(
            **_result_values(settings, operation, instance_id, address, True, change_id, status)
        )

    current = _find_record(settings, profile, aws)
    if current is None:
        return Route53Result(
            **_result_values(settings, operation, None, None, False, None, "INSYNC")
        )
    _require_simple_record(current)
    change_id = _change_record(settings, profile, operation, current, aws)
    status = _wait_change(settings, profile, change_id, aws, clock=clock, sleep=sleep)
    if _find_record(settings, profile, aws) is not None:
        raise Route53CliError("Route 53 DELETE postcondition failed")
    return Route53Result(**_result_values(settings, operation, None, None, True, change_id, status))


def _result_values(
    settings: Route53Settings,
    operation: str,
    instance_id: str | None,
    address: str | None,
    changed: bool,
    change_id: str | None,
    status: str,
) -> dict[str, Any]:
    return {
        "stage": settings.stage,
        "action": operation,
        "account": settings.account,
        "region": settings.region,
        "stack": settings.stack,
        "instance_id": instance_id,
        "hosted_zone_id": settings.hosted_zone_id,
        "record_name": settings.record_name.rstrip("."),
        "record_type": settings.record_type,
        "ttl": settings.ttl,
        "public_ipv4": address,
        "changed": changed,
        "change_id": change_id,
        "final_status": status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage only the configured Minecraft A record")
    parser.add_argument("operation", choices=("UPSERT", "DELETE"))
    parser.add_argument("--stage", choices=("dev", "prod"), default="dev")
    parser.add_argument("--profile", required=True)
    arguments = parser.parse_args(argv)
    if shutil.which("aws") is None:
        print("route53-cli: AWS CLI is required", file=sys.stderr)
        return 2
    try:
        configuration = load_configuration(Path(__file__).resolve().parents[2], arguments.stage)
        result = manage(configuration, arguments.operation, arguments.profile)
    except (ConfigValidationError, Route53CliError) as error:
        print(f"route53-cli: {error}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
