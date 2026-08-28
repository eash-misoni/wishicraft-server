"""Read-only Route 53 observation and endpoint discrepancy derivation."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from wishicraft.status import Ec2State, PublicIpv4State


class DnsState(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"
    UNKNOWN = "unknown"


class EndpointDiscrepancy(StrEnum):
    DNS_MISSING_WHEN_REQUIRED = "dns-missing-when-required"
    DNS_WRONG_IPV4 = "dns-points-to-wrong-ipv4"
    DNS_PRESENT_WHEN_ABSENT = "dns-present-while-endpoint-should-be-absent"
    PUBLIC_IPV4_UNKNOWN = "public-ipv4-unknown"
    DNS_OBSERVATION_UNKNOWN = "dns-observation-unknown"


@dataclass(frozen=True)
class DnsObservation:
    record_name: str
    state: DnsState
    ipv4_values: tuple[str, ...]
    source: str = "route53-list-resource-record-sets"


class Route53Api(Protocol):
    def list_resource_record_sets(self, **kwargs: object) -> object: ...


class Route53Observer:
    def __init__(self, api: Route53Api, *, hosted_zone_id: str, record_name: str) -> None:
        self._api = api
        self._zone = hosted_zone_id
        self._name = record_name.rstrip(".").lower() + "."

    def observe(self) -> DnsObservation:
        try:
            response = self._api.list_resource_record_sets(
                HostedZoneId=self._zone,
                StartRecordName=self._name,
                StartRecordType="A",
                MaxItems="2",
            )
            return _parse_record_sets(response, self._name)
        except Exception:  # noqa: BLE001 - AWS boundary is fail-closed.
            return DnsObservation(self._name, DnsState.UNKNOWN, ())


def _parse_record_sets(response: object, expected_name: str) -> DnsObservation:
    if not isinstance(response, dict) or not isinstance(response.get("ResourceRecordSets"), list):
        return DnsObservation(expected_name, DnsState.UNKNOWN, ())
    matches: list[dict[object, object]] = []
    raw_records = cast(list[object], response["ResourceRecordSets"])
    for raw in raw_records:
        if not isinstance(raw, dict):
            return DnsObservation(expected_name, DnsState.UNKNOWN, ())
        record = cast(dict[object, object], raw)
        name, record_type = record.get("Name"), record.get("Type")
        if not isinstance(name, str) or not isinstance(record_type, str):
            return DnsObservation(expected_name, DnsState.UNKNOWN, ())
        if name.rstrip(".").lower() + "." == expected_name:
            if record_type != "A":
                return DnsObservation(expected_name, DnsState.UNKNOWN, ())
            matches.append(record)
    if not matches:
        return DnsObservation(expected_name, DnsState.ABSENT, ())
    if len(matches) != 1:
        return DnsObservation(expected_name, DnsState.UNKNOWN, ())
    record = matches[0]
    ttl = record.get("TTL")
    if (
        "AliasTarget" in record
        or not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or ttl <= 0
        or not isinstance(record.get("ResourceRecords"), list)
    ):
        return DnsObservation(expected_name, DnsState.UNKNOWN, ())
    values: list[str] = []
    raw_values = cast(list[object], record["ResourceRecords"])
    for raw_value in raw_values:
        if not isinstance(raw_value, dict) or not isinstance(raw_value.get("Value"), str):
            return DnsObservation(expected_name, DnsState.UNKNOWN, ())
        value = raw_value["Value"]
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError:
            return DnsObservation(expected_name, DnsState.UNKNOWN, ())
        if parsed.version != 4:
            return DnsObservation(expected_name, DnsState.UNKNOWN, ())
        values.append(value)
    if not values or len(values) != len(set(values)):
        return DnsObservation(expected_name, DnsState.UNKNOWN, ())
    return DnsObservation(expected_name, DnsState.PRESENT, tuple(sorted(values)))


def derive_endpoint_discrepancies(
    *,
    ec2_state: Ec2State,
    public_state: PublicIpv4State,
    public_ipv4: str | None,
    dns: DnsObservation,
) -> tuple[EndpointDiscrepancy, ...]:
    if dns.state is DnsState.UNKNOWN:
        return (EndpointDiscrepancy.DNS_OBSERVATION_UNKNOWN,)
    if public_state is PublicIpv4State.UNKNOWN:
        return (EndpointDiscrepancy.PUBLIC_IPV4_UNKNOWN,)
    should_be_absent = ec2_state in {Ec2State.STOPPED, Ec2State.TERMINATED}
    if should_be_absent:
        return (
            (EndpointDiscrepancy.DNS_PRESENT_WHEN_ABSENT,) if dns.state is DnsState.PRESENT else ()
        )
    if ec2_state is not Ec2State.RUNNING:
        return ()
    if public_state is PublicIpv4State.ABSENT or public_ipv4 is None:
        return (EndpointDiscrepancy.PUBLIC_IPV4_UNKNOWN,)
    if dns.state is DnsState.ABSENT:
        return (EndpointDiscrepancy.DNS_MISSING_WHEN_REQUIRED,)
    if dns.ipv4_values != (public_ipv4,):
        return (EndpointDiscrepancy.DNS_WRONG_IPV4,)
    return ()
