"""Offline checks for an explicitly selected dedicated sandbox target."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from wishicraft.config import load_configuration, load_web_public_url

_SANDBOX_ENVIRONMENT = "dedicated-sandbox"


@dataclass(frozen=True)
class DeploymentIdentity:
    environment: str
    account_id: str
    region: str
    namespace: str


@dataclass(frozen=True)
class SandboxReferences:
    resource_ids: tuple[str, ...]
    secret_paths: tuple[str, ...]
    dns_names: tuple[str, ...]


@dataclass(frozen=True)
class LegacyBoundaries:
    account_id: str
    resource_ids: frozenset[str]
    secret_prefix: str
    dns_parent: str
    dns_names: frozenset[str]

    @classmethod
    def from_repository(cls, root: Path) -> LegacyBoundaries:
        """Load public configuration only; dev names the current legacy live stage."""
        configuration = load_configuration(root, "dev")
        stage = configuration.stage
        parent = configuration.project.values["domain"]
        assert isinstance(parent, dict)
        parent_name = parent["preferred_domain"]
        assert isinstance(parent_name, str)
        ids = (
            stage.host_runtime_value("target_host.existing_data_volume_id"),
            stage.host_runtime_value("target_host.vpc_id"),
            stage.host_runtime_value("target_host.subnet_id"),
            stage.route53_hosted_zone_id,
        )
        if not all(isinstance(value, str) and value for value in ids):
            raise ValueError("legacy live boundary is incomplete")
        # Cover all names below the legacy stage, not only those currently enumerated.
        token_name = configuration.secrets.discord_bot_token_parameter_name("dev")
        secret_prefix = token_name.rsplit("/", 2)[0] + "/"
        return cls(
            account_id=stage.aws_account_id,
            resource_ids=frozenset(value.casefold() for value in ids if isinstance(value, str)),
            secret_prefix=secret_prefix,
            dns_parent=parent_name,
            dns_names=frozenset(
                (
                    stage.route53_record_name,
                    load_web_public_url(root, "dev").removeprefix("https://"),
                )
            ),
        )


def validate_sandbox(
    *,
    requested: DeploymentIdentity | None,
    expected: DeploymentIdentity,
    references: SandboxReferences,
    legacy: LegacyBoundaries,
) -> DeploymentIdentity:
    """Compare against trusted expected values; no default or credential lookup."""
    if (
        expected.environment != _SANDBOX_ENVIRONMENT
        or re.fullmatch(r"[0-9]{12}", expected.account_id) is None
        or re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", expected.region) is None
        or re.fullmatch(r"wc2-sandbox(?:-[a-z0-9]+)*", expected.namespace) is None
        or expected.account_id == legacy.account_id
        or requested != expected
    ):
        raise ValueError("explicit dedicated sandbox deployment identity does not match")

    # Identifiers are literal references, not arbitrary URLs or AWS ARNs.
    for resource_id in references.resource_ids:
        if (
            re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", resource_id) is None
            or resource_id.casefold() in legacy.resource_ids
        ):
            raise ValueError("invalid sandbox resource reference")

    sandbox_parameter_prefix = f"/wishicraft/{expected.namespace}/"
    for path in references.secret_paths:
        if (
            not path.startswith(sandbox_parameter_prefix)
            or path.startswith(legacy.secret_prefix)
            or re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_.-]+", path) is None
            or path.rsplit("/", 1)[-1] in {".", ".."}
        ):
            raise ValueError("invalid sandbox parameter path")

    for name in references.dns_names:
        normalized = name.removesuffix(".").lower()
        zone = f"sandbox.{legacy.dns_parent}"
        if (
            not (normalized == zone or normalized.endswith(f".{zone}"))
            or normalized in legacy.dns_names
            or len(normalized) > 253
            or any(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                for label in normalized.split(".")
            )
        ):
            raise ValueError("invalid sandbox DNS reference")
    return expected
