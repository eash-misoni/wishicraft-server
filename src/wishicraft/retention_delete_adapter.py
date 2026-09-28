"""One-send EC2 adapter. Construction is not permission; canonical handler never binds it."""

from __future__ import annotations

import re
from typing import Any

from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from wishicraft.retention import DeleteRequestOutcome


def delete_client(session: Any, *, region: str) -> Any:
    return session.client(
        "ec2",
        region_name=region,
        config=Config(
            retries={"mode": "standard", "total_max_attempts": 1},
            connect_timeout=5,
            read_timeout=10,
            ignore_configured_endpoint_urls=True,
        ),
    )


class Ec2DeleteAdapter:
    def __init__(self, client: Any, *, region: str) -> None:
        retries = client.meta.config.retries
        if (
            client.meta.region_name != region
            or retries.get("total_max_attempts") != 1
            or retries.get("mode") != "standard"
        ):
            raise ValueError("ONE_SEND_CLIENT_REQUIRED")
        self.client = client

    def delete_once(self, *, snapshot_id: str) -> DeleteRequestOutcome:
        if not re.fullmatch(r"snap-[0-9a-f]{8,17}", snapshot_id):
            raise ValueError("INVALID_SNAPSHOT_ID")
        try:
            result = self.client.delete_snapshot(SnapshotId=snapshot_id)
            # Boto's EC2 result has no Return field. Require positive transport success.
            status = result.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if type(status) is int and 200 <= status < 300:
                return DeleteRequestOutcome.EXPLICIT_SUCCESS
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {
                "AccessDenied",
                "AccessDeniedException",
                "UnauthorizedOperation",
            }:
                return DeleteRequestOutcome.EXPLICIT_ACCESS_DENIED
            # Service NotFound is AFTER sending, not pre-request absence. No blind retry.
        except Exception:
            pass
        return DeleteRequestOutcome.OUTCOME_UNKNOWN
