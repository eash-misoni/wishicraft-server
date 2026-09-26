"""Compare captured AWS inventory with the new policy without AWS calls or writes."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from wishicraft.retention import RetentionContext, _parse_inventory_snapshot, plan_retention
from wishicraft.retention_daily import POLICY, ProtectionInventory, plan
from wishicraft.retention_workflow_lambda import RetentionDynamoApi, _load_complete_provenance


class CapturedProvenance:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    def scan(self, **kwargs: object) -> dict[str, Any]:
        return {"Items": self.items}


def compare(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("policy") != POLICY:
        raise ValueError("explicit policy version required")
    context = RetentionContext(**document["context"])
    snapshots = [
        _parse_inventory_snapshot(
            {**item, "StartTime": datetime.fromisoformat(item["StartTime"].replace("Z", "+00:00"))}
        )
        for item in document["snapshots"]
    ]
    proofs = _load_complete_provenance(
        cast(RetentionDynamoApi, CapturedProvenance(document["provenance_items"])),
        "captured",
        context,
    )
    protection = document.get("protection_inventory", {})
    # An offline artifact is not self-authenticating. Keep completeness false until a
    # separately reviewed collector reconciles historical holds and active journals.
    protections = ProtectionInventory(
        {k: tuple(v) for k, v in protection.get("reasons", {}).items()}, complete=False
    )
    now = datetime.fromisoformat(document["evaluated_at"].replace("Z", "+00:00"))
    old = plan_retention(
        snapshots,
        proofs,
        context=context,
        recycle_bin_preflight_complete=document.get("recycle_bin_complete") is True,
    )
    new = plan(
        snapshots,
        proofs,
        context=context,
        now=now,
        protections=protections,
        inventory_complete=document.get("inventory_complete") is True,
        recycle_bin_preflight_complete=document.get("recycle_bin_complete") is True,
    )
    return {"deployed_newest_seven": asdict(old), "proposed_days14_or_seven": asdict(new)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.input.read_text())), indent=2, default=str))


if __name__ == "__main__":
    main()
