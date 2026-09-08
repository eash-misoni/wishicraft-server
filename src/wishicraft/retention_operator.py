"""Canonical operator entrypoint for shared RETENTION admission."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Protocol, cast

from wishicraft.config import load_configuration
from wishicraft.naming import resource_name


class LambdaApi(Protocol):
    def invoke(self, **kwargs: object) -> object: ...


class Session(Protocol):
    def client(self, service_name: str, **kwargs: object) -> object: ...


def admit_retention(
    api: LambdaApi, *, function_name: str, idempotency_key: str
) -> dict[str, object]:
    if not idempotency_key.startswith("retention:") or len(idempotency_key) > 128:
        raise ValueError("invalid RETENTION idempotency key")
    response = api.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "schema_version": 1,
                "operation": "admit",
                "operation_type": "RETENTION",
                "idempotency_key": idempotency_key,
                "requested_by": "ADMIN",
            },
            separators=(",", ":"),
        ).encode(),
    )
    if not isinstance(response, dict) or response.get("FunctionError") is not None:
        raise RuntimeError("RETENTION admission failed")
    payload = response.get("Payload")
    reader = getattr(payload, "read", None)
    raw = reader() if callable(reader) else payload
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        result = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as error:
        raise RuntimeError("RETENTION admission returned malformed response") from error
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != 1
        or not isinstance(result.get("operation_id"), str)
        or not isinstance(result.get("created"), bool)
    ):
        raise RuntimeError("RETENTION admission returned malformed response")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    config = load_configuration(repository_root, args.stage)
    session = cast(Session, importlib.import_module("boto3").Session(profile_name=args.profile))
    result = admit_retention(
        cast(LambdaApi, session.client("lambda", region_name=config.stage.aws_region)),
        function_name=resource_name(config.project.resource_prefix, args.stage, "admission"),
        idempotency_key=args.idempotency_key,
    )
    print(f"operation_id={result['operation_id']} created={str(result['created']).lower()}")


if __name__ == "__main__":
    main()
