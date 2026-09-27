"""Candidate-scoped AWS read checks. Injected clients only; never creates AWS clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from wishicraft.retention_execution_inventory import digest
from wishicraft.retention_workflow_lambda import _rule_matches, _validate_recycle_bin_rule


@dataclass(frozen=True)
class AwsChecks:
    issues: tuple[str, ...]
    revision: str


def pages(
    api: Any, method: str, request: dict[str, Any], field: str, key: str
) -> list[dict[str, Any]]:
    """Bounded pagination: even an empty intermediate page must be followed."""
    allowed = {
        "describe_images",
        "describe_snapshots",
        "describe_locked_snapshots",
        "list_snapshots_in_recycle_bin",
        "list_rules",
    }
    if method not in allowed:
        raise ValueError("READ_ONLY_METHOD_REQUIRED")
    rows = []
    seen_tokens: set[str] = set()
    ids: set[str] = set()
    args = dict(request)
    for _ in range(1000):
        response = getattr(api, method)(**args)
        batch = response.get(field) if isinstance(response, dict) else None
        if not isinstance(batch, list):
            raise ValueError("INVALID_READ_PAGE")
        for row in batch:
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or row[key] in ids:
                raise ValueError("INVALID_OR_DUPLICATE_READ_IDENTITY")
            ids.add(row[key])
            rows.append(row)
        token = response.get("NextToken")
        if token is None:
            return rows
        if not isinstance(token, str) or not token or token in seen_tokens:
            raise ValueError("INVALID_READ_PAGINATION")
        seen_tokens.add(token)
        args["NextToken"] = token
    raise ValueError("READ_PAGE_LIMIT")


def inspect_candidate(
    ec2: Any, rbin: Any, *, snapshot_id: str, account: str, tags: dict[str, str]
) -> AwsChecks:
    """A failed domain never becomes an empty domain. No raw response/error is returned.

    Client account/region binding is verified by the future reader. This is a read-only
    predicate, not a fence against out-of-band AWS administrators. Release needs that
    operational exclusion independently of the formal Wishicraft global lock.
    """
    issues: list[str] = []
    summary: dict[str, Any] = {"snapshot_id": snapshot_id}
    try:
        images = pages(
            ec2,
            "describe_images",
            {
                "Owners": [account],
                "IncludeDeprecated": True,
                "IncludeDisabled": True,
                "Filters": [{"Name": "block-device-mapping.snapshot-id", "Values": [snapshot_id]}],
                "MaxResults": 1000,
            },
            "Images",
            "ImageId",
        )
        if images:
            issues.append("ami-reference-present")
        summary["ami_count"] = len(images)
    except Exception:
        issues.append("ami-reference-unknown")
    try:
        permissions = ec2.describe_snapshot_attribute(
            SnapshotId=snapshot_id, Attribute="createVolumePermission"
        )
        if (
            not isinstance(permissions, dict)
            or permissions.get("SnapshotId") != snapshot_id
            or not isinstance(permissions.get("CreateVolumePermissions"), list)
        ):
            raise ValueError("UNKNOWN_SHARING")
        if permissions["CreateVolumePermissions"]:
            issues.append("snapshot-shared")
        summary["sharing_count"] = len(permissions["CreateVolumePermissions"])
    except Exception:
        issues.append("sharing-unknown")
    try:
        locks = pages(
            ec2,
            "describe_locked_snapshots",
            {
                "SnapshotIds": [snapshot_id],
                "MaxResults": 1000,
            },
            "Snapshots",
            "SnapshotId",
        )
        if any(r["SnapshotId"] != snapshot_id or r.get("LockState") != "expired" for r in locks):
            issues.append("snapshot-locked-or-unknown")
        summary["expired_lock_count"] = len(locks)
    except Exception:
        issues.append("snapshot-lock-unknown")
    try:
        rules = pages(
            rbin,
            "list_rules",
            {
                "ResourceType": "EBS_SNAPSHOT",
                "MaxResults": 100,
            },
            "Rules",
            "Identifier",
        )
        rule_view = []
        for row in rules:
            rid = row["Identifier"]
            rule = _validate_recycle_bin_rule(rbin.get_rule(Identifier=rid), rid)
            if rule.get("Status") != "available":
                raise ValueError("RULE_NOT_AVAILABLE")
            rule_view.append(
                [
                    rid,
                    cast(dict[str, Any], rule["RetentionPeriod"])["RetentionPeriodValue"],
                    rule.get("LockState"),
                    _rule_matches(rule, tags),
                ]
            )
        binned = pages(
            ec2,
            "list_snapshots_in_recycle_bin",
            {
                "SnapshotIds": [snapshot_id],
                "MaxResults": 1000,
            },
            "Snapshots",
            "SnapshotId",
        )
        if binned:
            issues.append("candidate-already-in-recycle-bin")
        summary["rules"] = sorted(rule_view)
    except Exception:
        issues.append("recycle-bin-unknown")
    return AwsChecks(tuple(issues), digest(summary))
