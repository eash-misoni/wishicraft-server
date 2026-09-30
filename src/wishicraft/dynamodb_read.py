"""Consistent low-level DynamoDB reads; no operator/configuration dependencies."""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeDeserializer  # type: ignore[import-untyped]


def item(api: Any, table: str, key: str, value: str) -> dict[str, Any]:
    raw = api.get_item(TableName=table, Key={key: {"S": value}}, ConsistentRead=True).get(
        "Item", {}
    )
    decoder = TypeDeserializer()
    return {k: decoder.deserialize(v) for k, v in raw.items()}
