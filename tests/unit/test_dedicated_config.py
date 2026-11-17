from dataclasses import replace
from pathlib import Path

import pytest

from infrastructure.dedicated.deployment import (
    DeploymentIdentity,
    LegacyBoundaries,
    SandboxReferences,
    validate_sandbox,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = DeploymentIdentity("dedicated-sandbox", "000000000001", "ap-northeast-1", "wc2-sandbox")
SANDBOX = SandboxReferences(
    ("test-resource-id",),
    ("/wishicraft/wc2-sandbox/secret/rcon-password",),
    ("example.sandbox.wishicraft.net.",),
)


@pytest.fixture(scope="module")
def legacy() -> LegacyBoundaries:
    return LegacyBoundaries.from_repository(ROOT)


def test_explicit_sandbox(legacy: LegacyBoundaries) -> None:
    assert (
        validate_sandbox(requested=EXPECTED, expected=EXPECTED, references=SANDBOX, legacy=legacy)
        == EXPECTED
    )


@pytest.mark.parametrize(
    "requested",
    [
        None,
        replace(EXPECTED, environment=""),
        replace(EXPECTED, environment="dev"),
        replace(EXPECTED, environment="dedicated-live"),
        replace(EXPECTED, account_id=""),
        replace(EXPECTED, account_id="000000000002"),
        replace(EXPECTED, region=""),
        replace(EXPECTED, region="ap-northeast-2"),
        replace(EXPECTED, namespace=""),
        replace(EXPECTED, namespace="wc2-live"),
    ],
)
def test_missing_or_mismatched_identity_is_rejected(
    legacy: LegacyBoundaries, requested: DeploymentIdentity | None
) -> None:
    with pytest.raises(ValueError, match="deployment identity does not match"):
        validate_sandbox(requested=requested, expected=EXPECTED, references=SANDBOX, legacy=legacy)


def test_trusted_expectation_itself_cannot_select_live(legacy: LegacyBoundaries) -> None:
    for identity in (
        replace(EXPECTED, account_id=legacy.account_id),
        replace(EXPECTED, namespace="wc2-live"),
        replace(EXPECTED, environment="dev"),
    ):
        with pytest.raises(ValueError, match="deployment identity does not match"):
            validate_sandbox(
                requested=identity, expected=identity, references=SANDBOX, legacy=legacy
            )


def test_canonical_legacy_references_are_rejected(legacy: LegacyBoundaries) -> None:
    assert len(legacy.resource_ids) == 4
    assert len(legacy.dns_names) == 2
    invalid = (
        *(replace(SANDBOX, resource_ids=(value.upper(),)) for value in legacy.resource_ids),
        *(replace(SANDBOX, dns_names=(f"{name.upper()}.",)) for name in legacy.dns_names),
        replace(SANDBOX, dns_names=(legacy.dns_parent,)),
        replace(SANDBOX, dns_names=(f"play.{legacy.dns_parent}",)),
        replace(SANDBOX, dns_names=(f"evil-sandbox.{legacy.dns_parent}",)),
        replace(SANDBOX, secret_paths=(f"{legacy.secret_prefix}secret/rcon-password",)),
        replace(SANDBOX, secret_paths=("/wishicraft/wc2-live/secret/rcon-password",)),
        replace(SANDBOX, secret_paths=("/wishicraft/wc2-sandbox/../../dev/secret/rcon-password",)),
    )
    for references in invalid:
        with pytest.raises(ValueError, match="invalid sandbox"):
            validate_sandbox(
                requested=EXPECTED, expected=EXPECTED, references=references, legacy=legacy
            )
