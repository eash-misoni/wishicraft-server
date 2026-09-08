from __future__ import annotations

import io
import json
from typing import cast

import pytest

from wishicraft.retention_operator import admit_retention


class Lambda:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {
            "Payload": io.BytesIO(
                json.dumps(
                    {
                        "schema_version": 1,
                        "operation_id": "op-retention",
                        "created": True,
                        "lease_id": "lease-retention",
                    }
                ).encode()
            )
        }


def test_operator_uses_admin_shared_admission_with_stable_key() -> None:
    api = Lambda()
    result = admit_retention(
        api, function_name="wc-dev-admission", idempotency_key="retention:2026-09-08-001"
    )
    assert result["operation_id"] == "op-retention"
    assert len(api.calls) == 1
    request = json.loads(cast(bytes, api.calls[0]["Payload"]))
    assert request == {
        "schema_version": 1,
        "operation": "admit",
        "operation_type": "RETENTION",
        "idempotency_key": "retention:2026-09-08-001",
        "requested_by": "ADMIN",
    }


def test_operator_rejects_unstable_or_wrong_namespace_key() -> None:
    with pytest.raises(ValueError, match="idempotency"):
        admit_retention(Lambda(), function_name="admission", idempotency_key="random")
