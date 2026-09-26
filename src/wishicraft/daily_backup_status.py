"""Read-only operator view; never invokes evaluation or publishes metrics."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import boto3  # type: ignore[import-untyped]

from wishicraft.config import load_configuration, load_daily_backup_configuration
from wishicraft.daily_backup import status
from wishicraft.daily_backup_lambda import observe, reconcile_intent
from wishicraft.naming import resource_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    config = load_configuration(Path(__file__).resolve().parents[2], args.stage)
    project, stage = config.project, config.stage
    session = boto3.Session(profile_name=args.profile, region_name=stage.aws_region)
    if session.client("sts").get_caller_identity()["Account"] != stage.aws_account_id:
        raise ValueError("caller account mismatch")
    os.environ.update(
        SYSTEM_ID=project.system_id,
        GLOBAL_LOCK_NAME=stage.global_lock_name,
        SYSTEM_STATE_TABLE=resource_name(project.resource_prefix, stage.stage, "system-state"),
        LOCKS_TABLE=resource_name(project.resource_prefix, stage.stage, "locks"),
        OPERATIONS_TABLE=resource_name(project.resource_prefix, stage.stage, "operations"),
        PROTECTION_VOLUME_ID=str(stage.host_runtime_value("target_host.existing_data_volume_id")),
    )
    now = datetime.now(UTC)
    state, protection, actual, locked = observe(
        session.client("dynamodb"), session.client("ec2"), now
    )
    protection = reconcile_intent(session.client("dynamodb"), protection, now)
    flags = load_daily_backup_configuration(Path(__file__).resolve().parents[2], args.stage)
    enabled = isinstance(flags, dict) and flags.get("enabled") is True
    result = status(protection, state, now=now, enabled=enabled, actual=actual, locked=locked)
    result["initialized"] = "backup_protection" in state
    result["configuration_source"] = (
        "local stage supplement; deployed flag must be compared at release"
    )
    if not result["initialized"]:
        result["protection"]["unknown_since"] = None
        result["history_unknown"] = True
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
