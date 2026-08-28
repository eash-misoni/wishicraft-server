from __future__ import annotations

from wishicraft.endpoint import (
    DnsObservation,
    DnsState,
    EndpointDiscrepancy,
    Route53Observer,
    derive_endpoint_discrepancies,
)
from wishicraft.status import Ec2State, PublicIpv4State


class FakeRoute53:
    def __init__(self, response: object) -> None:
        self.response = response

    def list_resource_record_sets(self, **kwargs: object) -> object:
        return self.response


def observe(response: object) -> DnsObservation:
    return Route53Observer(
        FakeRoute53(response), hosted_zone_id="Z0123456789", record_name="mc-dev.example.test"
    ).observe()


def test_absent_record_is_distinct_from_failure() -> None:
    assert observe({"ResourceRecordSets": []}).state is DnsState.ABSENT


def test_exact_a_record_is_normalized() -> None:
    result = observe(
        {
            "ResourceRecordSets": [
                {
                    "Name": "mc-dev.example.test.",
                    "Type": "A",
                    "TTL": 60,
                    "ResourceRecords": [{"Value": "203.0.113.8"}],
                }
            ]
        }
    )
    assert result.state is DnsState.PRESENT
    assert result.ipv4_values == ("203.0.113.8",)


def test_malformed_or_duplicate_record_is_unknown() -> None:
    duplicate = {
        "ResourceRecordSets": [
            {
                "Name": "mc-dev.example.test.",
                "Type": "A",
                "TTL": 60,
                "ResourceRecords": [{"Value": "203.0.113.8"}],
            },
            {
                "Name": "mc-dev.example.test.",
                "Type": "A",
                "TTL": 60,
                "ResourceRecords": [{"Value": "203.0.113.9"}],
            },
        ]
    }
    assert observe(duplicate).state is DnsState.UNKNOWN
    assert (
        observe({"ResourceRecordSets": [{"Name": "mc-dev.example.test.", "Type": "A"}]}).state
        is DnsState.UNKNOWN
    )


def test_a_record_without_valid_ttl_is_unknown() -> None:
    for ttl in (None, 0, True, "60"):
        record: dict[str, object] = {
            "Name": "mc-dev.example.test.",
            "Type": "A",
            "ResourceRecords": [{"Value": "203.0.113.8"}],
        }
        if ttl is not None:
            record["TTL"] = ttl
        assert observe({"ResourceRecordSets": [record]}).state is DnsState.UNKNOWN


def test_route53_api_error_is_unknown() -> None:
    class Failing:
        def list_resource_record_sets(self, **kwargs: object) -> object:
            raise RuntimeError("hidden AWS detail")

    result = Route53Observer(Failing(), hosted_zone_id="Z1", record_name="mc.example").observe()
    assert result.state is DnsState.UNKNOWN


def test_stopped_without_ip_or_dns_has_no_endpoint_discrepancy() -> None:
    assert (
        derive_endpoint_discrepancies(
            ec2_state=Ec2State.STOPPED,
            public_state=PublicIpv4State.ABSENT,
            public_ipv4=None,
            dns=DnsObservation("mc.example.", DnsState.ABSENT, ()),
        )
        == ()
    )


def test_running_correct_endpoint_has_no_discrepancy() -> None:
    assert (
        derive_endpoint_discrepancies(
            ec2_state=Ec2State.RUNNING,
            public_state=PublicIpv4State.ASSIGNED,
            public_ipv4="203.0.113.8",
            dns=DnsObservation("mc.example.", DnsState.PRESENT, ("203.0.113.8",)),
        )
        == ()
    )


def test_endpoint_discrepancies_are_specific() -> None:
    dns = DnsObservation("mc.example.", DnsState.PRESENT, ("203.0.113.9",))
    assert derive_endpoint_discrepancies(
        ec2_state=Ec2State.RUNNING,
        public_state=PublicIpv4State.ASSIGNED,
        public_ipv4="203.0.113.8",
        dns=dns,
    ) == (EndpointDiscrepancy.DNS_WRONG_IPV4,)
    assert derive_endpoint_discrepancies(
        ec2_state=Ec2State.STOPPED,
        public_state=PublicIpv4State.ABSENT,
        public_ipv4=None,
        dns=dns,
    ) == (EndpointDiscrepancy.DNS_PRESENT_WHEN_ABSENT,)
    assert derive_endpoint_discrepancies(
        ec2_state=Ec2State.RUNNING,
        public_state=PublicIpv4State.UNKNOWN,
        public_ipv4=None,
        dns=DnsObservation("mc.example.", DnsState.ABSENT, ()),
    ) == (EndpointDiscrepancy.PUBLIC_IPV4_UNKNOWN,)
