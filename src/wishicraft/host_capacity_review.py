"""Offline artifact checks for an operator-reviewed resize; never calls AWS."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from wishicraft.config import SUPPORTED_TARGET_INSTANCE_TYPES


def review(
    live: dict[str, Any],
    candidate: dict[str, Any],
    change_set: dict[str, Any],
    policy_response: dict[str, Any],
    canonical_policy: dict[str, Any],
    *,
    stack_id: str,
    instance_id: str,
) -> None:
    """Require the exact resize shape and policy. This does not verify live freshness."""
    if json.loads(policy_response.get("StackPolicyBody", "null")) != canonical_policy:
        raise ValueError("missing or noncanonical Target stack policy")
    before = live["Resources"]["TargetInstance"]["Properties"]["InstanceType"]
    after = candidate["Resources"]["TargetInstance"]["Properties"]["InstanceType"]
    if (
        before not in SUPPORTED_TARGET_INSTANCE_TYPES
        or after not in SUPPORTED_TARGET_INSTANCE_TYPES
    ):
        raise ValueError("unsupported instance type")
    if before == after:
        raise ValueError("no resize requested")
    expected = deepcopy(live)
    expected["Resources"]["TargetInstance"]["Properties"]["InstanceType"] = after
    if expected != candidate:
        raise ValueError("template changes beyond InstanceType")
    if (
        change_set.get("StackId") != stack_id
        or change_set.get("Status") != "CREATE_COMPLETE"
        or change_set.get("ExecutionStatus") != "AVAILABLE"
        or change_set.get("NextToken")
        or change_set.get("IncludeNestedStacks") is not False
    ):
        raise ValueError("wrong stack, incomplete or unavailable ChangeSet")
    seen: set[str] = set()
    for change in change_set["Changes"]:
        rc = change["ResourceChange"]
        logical = rc["LogicalResourceId"]
        if (
            change.get("Type") != "Resource"
            or logical in seen
            or logical not in {"TargetInstance", "TargetDataVolumeAttachment"}
            or rc.get("Action") != "Modify"
            or rc.get("Replacement") not in {"False", "Conditional"}
            or rc.get("Scope") != ["Properties"]
            or not rc.get("Details")
        ):
            raise ValueError("unexpected resource action")
        seen.add(logical)
        instance = logical == "TargetInstance"
        expected_type = "AWS::EC2::Instance" if instance else "AWS::EC2::VolumeAttachment"
        data_volume = live["Resources"]["TargetDataVolumeAttachment"]["Properties"]["VolumeId"]
        physical = instance_id if instance else f"{instance_id}|{data_volume}"
        if rc.get("ResourceType") != expected_type or rc.get("PhysicalResourceId") != physical:
            raise ValueError("resource identity mismatch")
        for detail in rc["Details"]:
            target = detail["Target"]
            expected_name = "InstanceType" if instance else "InstanceId"
            if (
                target.get("Attribute") != "Properties"
                or target.get("Name") != expected_name
                or target.get("RequiresRecreation") != ("Conditionally" if instance else "Always")
                or detail.get("Evaluation") != ("Static" if instance else "Dynamic")
            ):
                raise ValueError("unexpected replacement trigger")
            source = detail.get("ChangeSource")
            cause = detail.get("CausingEntity")
            if not (
                (source == "DirectModification" and cause is None)
                or (not instance and source == "ResourceReference" and cause == "TargetInstance")
            ):
                raise ValueError("unexpected change source")
            if instance and (
                target.get("BeforeValue") != before or target.get("AfterValue") != after
            ):
                raise ValueError("ChangeSet type differs from reviewed template")
    if "TargetInstance" not in seen:
        raise ValueError("missing instance change")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("live", "candidate", "change-set", "policy"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--stack-id", required=True)
    parser.add_argument("--instance-id", required=True)
    args = parser.parse_args()
    canonical = Path(__file__).resolve().parents[2] / "config/stack-policies/target.json"
    review(
        json.loads(args.live.read_text()),
        json.loads(args.candidate.read_text()),
        json.loads(args.change_set.read_text()),
        json.loads(args.policy.read_text()),
        json.loads(canonical.read_text()),
        stack_id=args.stack_id,
        instance_id=args.instance_id,
    )
    print("Artifact checks passed. Live preflight and approval are still required; no AWS action.")


if __name__ == "__main__":
    main()
