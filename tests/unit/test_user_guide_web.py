"""Public artifact boundary and real parser/schema agreement; no external operations."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
import yaml

from web.build import (
    BEGIN,
    END,
    OUTPUTS,
    ROOT,
    ROUTES,
    build,
    examples,
    load_pages,
    md_text,
    public_markdown,
    render,
    sources,
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
    assert {str(p.relative_to(first)) for p in first.rglob("*") if p.is_file()} == OUTPUTS
    assert {str(p.relative_to(first)): p.read_bytes() for p in first.rglob("*") if p.is_file()} == {
        str(p.relative_to(second)): p.read_bytes() for p in second.rglob("*") if p.is_file()
    }
    with pytest.raises(FileExistsError):
        build(ROOT, first)
    for document in first.rglob("*.html"):
        parser = Links()
        parser.feed(document.read_text())
        assert len(parser.ids) == len(set(parser.ids))
        for url in parser.urls:
            if url.startswith("#"):
                assert url[1:] in parser.ids
            else:
                target = document.parent / url
                assert (target / "index.html").is_file() if url.endswith("/") else target.is_file()
    output = "\n".join(p.read_text() for p in first.rglob("*") if p.is_file())
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


def test_sources_are_explicit_and_complete() -> None:
    pages = load_pages(ROOT)
    assert tuple(pages) == ROUTES
    assert len(OUTPUTS) == 17
    assert all("{{" not in page.body for page in pages.values())
    index = (ROOT / "docs/discord_user_guide.md").read_text()
    assert "user-guide/commands/reset.md" in index


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
    pages = load_pages(ROOT)
    rows = [
        (example, pages[f"commands/{name}"].roles)
        for name, commands in examples(ROOT).items()
        for example in commands
    ]
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
    pages = load_pages(ROOT)
    body = "\n".join(page.body + page.conditions + page.warning for page in pages.values())
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


def test_metadata_setting_injection_and_unlisted_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from shutil import copytree

    import web.build as builder

    copytree(ROOT / "docs/user-guide", tmp_path / "docs/user-guide")
    copytree(ROOT / "web", tmp_path / "web")
    schema, games, facts = sources(ROOT)
    attack = '<img src=x onerror="alert(1)"> | [x](https://example.test)'
    games[0]["name"] = attack
    monkeypatch.setattr(builder, "sources", lambda root: (schema, games, facts))
    # Files outside the source allowlist must never be copied or rendered.
    (tmp_path / "docs/user-guide/private.md").write_text("private-synthetic-marker")
    build(tmp_path, tmp_path / "site")
    for document in (tmp_path / "site").rglob("*.html"):
        text = document.read_text()
        assert "<img" not in text and 'href="https:' not in text
        assert "private-synthetic-marker" not in text
    pages = builder.load_pages(tmp_path)
    reset = pages["commands/reset"]
    html = builder.page_html(reset, pages, tmp_path)
    assert html.index('class="warning"') < html.index("/mc reset game:")
    assert "遊ぶ前に、ここから" not in html
    # Metadata HTML is escaped too, not treated as a template or Markdown.
    html = builder.page_html(replace(reset, title=attack), pages, tmp_path)
    assert "<img" not in html
    games[0]["name"] = "arn:aws:synthetic"
    with pytest.raises(ValueError, match="excluded data"):
        builder.load_pages(tmp_path)
