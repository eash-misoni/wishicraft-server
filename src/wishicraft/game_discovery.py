"""Read-only discovery from the existing registry and immutable package authority."""

from __future__ import annotations

import json
import time
from collections import Counter
from html import escape
from typing import Any

from wishicraft.artifacts import game_package
from wishicraft.game_creation import registry_ids
from wishicraft.reset_policy import policies
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.web_status import decode, display_name

GUIDE_SLOT = "<!-- registered-games -->"
GUIDE_UNAVAILABLE = (
    '<p role="status">Game一覧を取得できません。<a href="./">再読み込み</a>してください。</p>'
)


class Discovery:
    def __init__(
        self, api: Any, table: str, legacy: tuple[str, ...], reset: dict[str, Any]
    ) -> None:
        self.api, self.table, self.legacy, self.reset = api, table, legacy, reset

    def read(self, *, deadline: float | None = None) -> list[dict[str, Any]]:
        ids = registry_ids(self.api, self.table, self.legacy)
        result = []
        packages = game_package.load()
        for game_id in ids:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("discovery budget exceeded")
            raw = self.api.get_item(
                TableName=self.table, Key={"game_id": {"S": game_id}}, ConsistentRead=True
            ).get("Item", {})
            item = {k: decode(v) for k, v in raw.items()}
            if not item or item.get("lifecycle_state") != "ACTIVE":
                continue
            name = display_name(item.get("display_name"))
            if item.get("game_id") != game_id or not name:
                continue
            if item.get("materialization_state") not in {
                "UNMATERIALIZED",
                "MATERIALIZED",
                "MATERIALIZATION_FAILED",
            }:
                continue
            # Match the pinned catalog; do not publish an unvalidated stored definition.
            package = game_package.select(packages, item.get("package", {}))
            if "creation" in item:
                if item.get("package", {}).get("definition") != package or item["creation"].get(
                    "package_digest"
                ) != game_package.digest(package):
                    continue
                reset = item["creation"].get("reset_policy")
            else:
                if game_id not in self.legacy or package["loader"]["type"] != "vanilla":
                    continue
                reset = self.reset.get(game_id)
            if reset is not None:
                policies(json.dumps({game_id: reset}), RuntimeCatalog(ids))
            result.append(
                {
                    "id": game_id,
                    "name": name,
                    "status": "ACTIVE",
                    "kind": package["loader"]["type"],
                    "minecraft_version": package["minecraft_version"],
                    "reset": reset is not None
                    and item.get("materialization_state") == "MATERIALIZED"
                    and "import" not in item.get("creation", {}),
                }
            )
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("discovery budget exceeded")
        counts = Counter(g["name"].casefold() for g in result)
        for game in result:
            label = game["name"]
            if counts[label.casefold()] > 1:
                # Smallest unique prefix, comparing the complete registry snapshot.
                size = 8
                suffix = game["id"].removeprefix("game-")
                while any(
                    other["id"] != game["id"]
                    and other["id"].removeprefix("game-")[:size] == suffix[:size]
                    for other in result
                ):
                    size += 1
                tail = " · " + suffix[:size]
                label = label[: 100 - len(tail)] + tail
            game["label"] = label[:100]
        return sorted(result, key=lambda g: (g["name"].casefold(), g["id"]))


def choices(games: list[dict[str, Any]], command: str, query: str) -> list[dict[str, str]]:
    if command not in {"start", "switch", "reset"}:
        raise ValueError("unsupported discovery command")
    text = query.casefold().strip()
    eligible = [
        g
        for g in games
        if (command != "reset" or g["reset"])
        and (text in g["name"].casefold() or text in g["id"].casefold())
    ]

    def rank(g: dict[str, Any]) -> tuple[int, str, str]:
        values = (g["name"].casefold(), g["id"].casefold())
        return (
            0 if text in values else 1 if any(v.startswith(text) for v in values) else 2,
            g["name"].casefold(),
            g["id"],
        )

    return [{"name": g["label"], "value": g["id"]} for g in sorted(eligible, key=rank)[:25]]


def guide_html(games: list[dict[str, Any]]) -> str:
    # Explicit public allowlist: no IDs, paths, seeds, provenance, AWS or connection details.
    cards = []
    for game in games:
        cards.append(
            '<section class="card"><h2>'
            + escape(game["label"])
            + "</h2><p>"
            + escape(game["kind"])
            + " · Minecraft "
            + escape(game["minecraft_version"])
            + "</p><p>RESET："
            + ("対応" if game["reset"] else "非対応")
            + "</p></section>"
        )
    return (
        '<div class="listing">' + "".join(cards) + "</div>"
        if cards
        else "<p>現在公開中のGameはありません。</p>"
    )
