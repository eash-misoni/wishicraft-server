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
    ROOT,
    build,
    examples,
    load_pages,
    md_text,
    outputs,
    public_markdown,
    render,
    routes,
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
    assert {str(p.relative_to(first)) for p in first.rglob("*") if p.is_file()} == outputs(ROOT)
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
    assert tuple(pages) == routes(ROOT)
    assert len(outputs(ROOT)) == len(routes(ROOT)) + 4
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


@pytest.fixture
def third_game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Web input only; never change the backend's two-Game catalog or real registration."""
    from shutil import copytree

    import web.build as builder

    copytree(ROOT / "web", tmp_path / "web")
    copytree(ROOT / "docs/user-guide", tmp_path / "docs/user-guide")
    schema, games, facts = sources(ROOT)
    games.append(
        {
            "id": "game-test-third",
            "name": "Test third <Game>",
            "edition": "Java Edition",
            "version": "99.7",
            "server": "TEST_LOADER",
        }
    )
    for command in schema[0]["options"]:
        if command["name"] in {"start", "switch"}:
            command["options"][0]["choices"].append(
                {"name": "Test third", "value": "game-test-third"}
            )
    monkeypatch.setattr(builder, "sources", lambda root: (schema, games, facts))
    path = tmp_path / "web/games.yaml"
    entries = yaml.safe_load(path.read_text())
    entries.append(
        {
            "id": "game-test-third",
            "slug": "third-game",
            "client": {
                "status": "required",
                "loader": "Test Loader 7.1",
                "pack": "Test Pack 8.2",
                "preparation": "管理者からtest配布物を受け取り、専用profileを作成します。",
            },
        }
    )
    path.write_text(yaml.safe_dump(entries, allow_unicode=True))
    (tmp_path / "docs/user-guide/games/third-game.md").write_text(
        "---\nsummary: test-only-third-summary\nwarning: test専用\n---\n試験用の説明です。\n"
    )
    return tmp_path


def test_third_game_is_independent_and_order_safe(third_game: Path) -> None:
    import web.build as builder

    pages = load_pages(third_game)
    page = pages["games/third-game"]
    assert "99\\.7" in page.body and "Test Loader 7\\.1" in page.body
    assert "Test Pack 8\\.2" in page.body and "test配布物" in page.body
    assert "Reset：非対応" in page.body
    assert "seed 0" not in page.body and "26.2" not in page.body
    assert "/mc start game:game-test-third" in page.body
    assert "third-game.md" in pages["commands/start"].body
    assert "third-game.md" not in pages["commands/reset"].body
    site = third_game / "site"
    build(third_game, site)
    assert (site / "games/third-game/index.html").is_file()
    assert 'href="third-game/"' in (site / "games/index.html").read_text()
    for document in site.rglob("*.html"):
        parser = Links()
        parser.feed(document.read_text())
        for url in parser.urls:
            if url.startswith("#"):
                assert url[1:] in parser.ids
            else:
                target = document.parent / url
                assert (target / "index.html").is_file() if url.endswith("/") else target.is_file()
    # Both canonical record ordering and publication ordering can change independently.
    schema, records, facts = builder.sources(third_game)
    records.reverse()
    registration = third_game / "web/games.yaml"
    registration.write_text(
        yaml.safe_dump(list(reversed(yaml.safe_load(registration.read_text()))))
    )
    reordered = load_pages(third_game)
    for route in pages:
        if route.startswith("games/"):
            assert reordered[route] == pages[route]
    # Schema can contain a Game that has not been selected for publication.
    entries = yaml.safe_load(registration.read_text())
    registration.write_text(yaml.safe_dump([e for e in entries if e["id"] != "game-test-third"]))
    build(third_game, third_game / "unlisted-site")
    assert "game-test-third" not in "".join(
        p.read_text() for p in (third_game / "unlisted-site").rglob("*.html")
    )


@pytest.mark.parametrize("field", ["edition", "version", "server", "name"])
def test_missing_resolved_participation_field(third_game: Path, field: str) -> None:
    import web.build as builder

    _, records, _ = builder.sources(third_game)
    records[-1][field] = ""
    with pytest.raises(ValueError, match=f"game-test-third: missing {field}"):
        load_pages(third_game)


@pytest.mark.parametrize("field", ["status", "loader", "pack", "preparation"])
def test_missing_client_information(third_game: Path, field: str) -> None:
    path = third_game / "web/games.yaml"
    entries = yaml.safe_load(path.read_text())
    del entries[-1]["client"][field]
    path.write_text(yaml.safe_dump(entries))
    with pytest.raises(ValueError, match=f"game-test-third: missing.*client.{field}"):
        load_pages(third_game)


@pytest.mark.parametrize("slug", ["a", "../private", "A", "x/y", "<script>", "", "x?y", "x%2fy"])
def test_unsafe_or_duplicate_game_slug(third_game: Path, slug: str) -> None:
    path = third_game / "web/games.yaml"
    entries = yaml.safe_load(path.read_text())
    entries[-1]["slug"] = slug
    path.write_text(yaml.safe_dump(entries))
    with pytest.raises(ValueError, match="slug"):
        load_pages(third_game)


def test_explicit_unknown_and_client_insertion(third_game: Path) -> None:
    path = third_game / "web/games.yaml"
    entries = yaml.safe_load(path.read_text())
    entries[-1]["client"] = {
        "status": "unknown",
        "loader": "未確認",
        "pack": "未確認",
        "preparation": '<img src=x onerror="alert(1)"> | [x](https://test.invalid)',
    }
    path.write_text(yaml.safe_dump(entries))
    build(third_game, third_game / "unknown-site")
    html = (third_game / "unknown-site/games/third-game/index.html").read_text()
    assert "未確認：参加前に管理者へ確認" in html
    assert "<img" not in html and 'href="https:' not in html
    assert "追加MOD不要と確認済み" not in html


def test_real_output_excludes_fixture_values(tmp_path: Path) -> None:
    build(ROOT, tmp_path / "site")
    html = "".join(p.read_text() for p in (tmp_path / "site").rglob("*.html"))
    for marker in (
        "game-test-third",
        "99.7",
        "Test Loader",
        "Test Pack",
        "test配布物",
        "test.invalid",
    ):
        assert marker not in html
