"""Public artifact boundary and real parser/schema agreement; no external operations."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
import yaml

from web.build import (
    BEGIN,
    END,
    GUIDE,
    OUTPUTS,
    ROOT,
    build,
    md_text,
    public_markdown,
    render,
    sources,
    update_generated,
)
from wishicraft.discord_interactions import (
    DiscordIngressConfig,
    UnauthorizedInteraction,
    parse_and_authorize,
)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if value is not None and key == "id":
                self.ids.append(value)
            if value is not None and key in {"href", "src"}:
                self.urls.append(value)


def test_reproducible_closed_artifact_and_links(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    build(ROOT, first)
    build(ROOT, second)
    assert {p.name for p in first.iterdir()} == OUTPUTS
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    with pytest.raises(FileExistsError):
        build(ROOT, first)
    parser = Links()
    parser.feed((first / "index.html").read_text())
    assert len(parser.ids) == len(set(parser.ids))
    for url in parser.urls:
        assert url[1:] in parser.ids if url.startswith("#") else (first / url).is_file()
    output = "\n".join(p.read_text() for p in first.iterdir())
    stage = yaml.safe_load((ROOT / "config/stages/dev.yaml").read_text())
    project = yaml.safe_load((ROOT / "config/project.yaml").read_text())
    excluded = [
        stage["aws"]["account_id"],
        stage["route53"]["record_name"],
        stage["route53"]["hosted_zone_id"],
        *[v for k, v in stage["discord"].items() if k.endswith("_id") or k == "public_key"],
        *project["initial_game"]["minecraft_profile_names"],
        *project["initial_game"]["minecraft_profile_uuids"],
        "production evidence",
        "/srv/minecraft",
        "receipt.json",
    ]
    assert all(value not in output for value in excluded)
    assert "fetch(" not in output and "XMLHttpRequest" not in output


def test_generated_markdown_is_current() -> None:
    text = (ROOT / GUIDE).read_text()
    assert update_generated(text, ROOT) == text


def payload(example: str, roles: list[str], schema: list[dict[str, Any]]) -> bytes:
    _, name, *arguments = example.split()
    command = next(c for c in schema[0]["options"] if c["name"] == name)
    options = []
    for argument in arguments:
        key, value = argument.split(":", 1)
        definition = next(o for o in command["options"] if o["name"] == key)
        options.append(
            {"name": key, "type": definition["type"], "value": True if value == "true" else value}
        )
    return json.dumps(
        {
            "id": "10",
            "application_id": "1",
            "guild_id": "2",
            "channel_id": "3",
            "version": 1,
            "type": 2,
            "token": "synthetic-test-only",
            "member": {"roles": roles},
            "data": {
                "id": "11",
                "name": "mc",
                "type": 1,
                "options": [{"name": name, "type": 1, "options": options}],
            },
        }
    ).encode()


def test_all_documented_examples_and_roles_match_actual_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_GAMES", (ROOT / "config/two-game-dev.json").read_text())
    monkeypatch.setenv("RESET_POLICIES", (ROOT / "config/reset-dev.json").read_text())
    schema, _, _ = sources(ROOT)
    config = DiscordIngressConfig("1", "2", "3", "4", "5", "a" * 64)
    rows = re.findall(r"^\| `(/mc [^`]+)` \| ([^|]+) \|", (ROOT / GUIDE).read_text(), re.M)
    assert {example.split()[1] for example, _ in rows} == {c["name"] for c in schema[0]["options"]}
    for example, allowed in rows:
        for label, roles in (("Player", ["4"]), ("Admin", ["5"]), ("Nobody", [])):
            raw = payload(example, roles, schema)
            if label in allowed:
                assert (
                    parse_and_authorize(raw, config=config).kind.value == example.split()[1].upper()
                )
            else:
                with pytest.raises(UnauthorizedInteraction):
                    parse_and_authorize(raw, config=config)
        raw = payload(example, ["5"], schema)
        for field in ("application_id", "guild_id", "channel_id"):
            wrong = json.loads(raw)
            wrong[field] = "999"
            with pytest.raises(UnauthorizedInteraction):
                parse_and_authorize(json.dumps(wrong).encode(), config=config)
    assert parse_and_authorize(payload("/mc start", ["4"], schema), config=config)
    assert (
        parse_and_authorize(
            payload("/mc reset game:game-vanilla-secondary confirm:true seed:new", ["4"], schema),
            config=config,
        ).seed_mode
        == "new"
    )


@pytest.mark.parametrize(
    "text",
    ["arn:aws:example", "123456789012", "mc-dev.wishicraft.net", "/srv/data", "token=example"],
)
def test_excluded_values_fail_closed(text: str) -> None:
    with pytest.raises(ValueError, match="excluded data"):
        public_markdown(BEGIN + text + END)


def test_only_explicit_public_region_is_selected() -> None:
    assert (
        public_markdown("internal before" + BEGIN + "approved" + END + "internal after")
        == "approved"
    )
    for text in ("missing", END + BEGIN, BEGIN + BEGIN + END):
        with pytest.raises(ValueError):
            public_markdown(text)


def test_insertion_safety_and_local_links() -> None:
    html, _ = render("## 参加の準備\n<script>alert(1)</script>\n\n[x](javascript:alert(1))")
    assert "<script>" not in html and 'href="javascript:' not in html
    attack = '<img src=x onerror="alert(1)">\n## injected | [x](https://example.test) `code`'
    html, _ = render("## 参加の準備\n\n" + md_text(attack))
    assert "<img" not in html and "<a " not in html and "<code>" not in html
    for body in ("[private](../config/stages/dev.yaml)", "![x](remote.png)", "[bad](#missing)"):
        with pytest.raises(ValueError):
            render(body)


def test_current_safety_contract_remains_in_public_text() -> None:
    body = public_markdown((ROOT / GUIDE).read_text())
    for requirement in (
        "STOPPED/HEALTHY",
        "共有Data EBS全体",
        "選択中・稼働中・観測0人",
        "seed 0",
        "その操作に固定",
        "server.properties",
        "所持品/位置/進捗",
        "gamerule/scoreboard",
        "直近3個",
        "別枠",
        "anchor",
        "EBS喪失",
        "race",
        "新しい操作で補わず",
    ):
        assert requirement in body
