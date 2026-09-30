"""Host-only fixture export. The isolated driver receives JSON, never tests or pytest."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tests.unit.test_retention_dynamodb_numbers import recovery_wire


def encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    raise TypeError("unsupported synthetic fixture")


def export(path: Path) -> None:
    api, aws, args = recovery_wire()
    # All values are synthetic unit fixtures; no sessions, clients or real records.
    result = dict(
        tables=api.tables,
        record=args["record"].item(),
        context=asdict(aws.fixture["context"]),
        now=args["now"],
        snapshots=aws.fixture["snapshots"],
        execution=aws.describe_execution(),
        history=aws.get_execution_history(),
        function={k: v for k, v in aws.get_function_configuration().items() if k != "Environment"},
    )
    result["function"]["Handler"] = "wishicraft.retention_workflow_lambda.handler"
    path.write_text(json.dumps(result, default=encode, sort_keys=True))


if __name__ == "__main__":
    export(Path(sys.argv[1]))
