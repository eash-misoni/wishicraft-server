"""Build only allowlisted guide pages and assets from reviewed Markdown and schema."""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from markdown_it import MarkdownIt

from wishicraft.reset_commands import extend
from wishicraft.reset_policy import policies
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.two_game_admin import declaration

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (
    "",
    "join",
    "games",
    "games/a",
    "games/b",
    "commands",
    "commands/status",
    "commands/start",
    "commands/stop",
    "commands/switch",
    "commands/backup",
    "commands/reset",
    "help",
)
CONTENT = Path("docs/user-guide")
ASSETS = ("guide.css", "guide.js")
OUTPUTS = {
    *(f"{route}/index.html" if route else "index.html" for route in ROUTES),
    "404.html",
    "guide.css",
    "guide.js",
    "_headers",
}
BEGIN = "<!-- public-guide:begin -->"
END = "<!-- public-guide:end -->"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'"
)


def sources(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    """Explicit projection; never serialize configuration or the full declaration."""
    document = declaration(root, now=datetime(2000, 1, 1, tzinfo=UTC))
    project = yaml.safe_load((root / "config/project.yaml").read_text())
    stage = yaml.safe_load((root / "config/stages/dev.yaml").read_text())
    catalog = RuntimeCatalog.parse((root / "config/two-game-dev.json").read_text())
    reset = policies((root / "config/reset-dev.json").read_text(), catalog)
    runtime = stage["host_runtime"]["minecraft"]
    if runtime["type"] != "VANILLA" or not re.fullmatch(r"\d+(?:\.\d+)+", runtime["version"]):
        raise ValueError("runtime changed: review edition/client guidance before building")
    games = [
        {"id": catalog.game_ids[0], "name": project["initial_game"]["display_name"]},
        {"id": catalog.game_ids[1], "name": document["game"]["display_name"]},
    ]
    commands = extend(document["discord_commands"], tuple(reset))
    for command in commands[0]["options"]:
        identifiers = [command["name"]]
        for option in command.get("options", []):
            identifiers.append(option["name"])
            identifiers.extend(choice["value"] for choice in option.get("choices", []))
        if any(not re.fullmatch(r"[a-z0-9-]+", value) for value in identifiers):
            raise ValueError("unsafe command schema text")
    return (
        commands,
        games,
        {
            "version": runtime["version"],
            "reset": reset,
        },
    )


def md_text(value: str) -> str:
    """Escape all Markdown punctuation as well as HTML, including table separators."""
    value = " ".join(value.splitlines())
    return re.sub(r"([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\\\1", value)


@dataclass(frozen=True)
class GuidePage:
    route: str
    title: str
    summary: str
    roles: str
    conditions: str
    warning: str
    body: str


def source_path(route: str) -> Path:
    if route not in ROUTES:
        raise ValueError("page outside public allowlist")
    return CONTENT / (f"{route}.md" if route else "index.md")


def relative_url(current: str, target: str) -> str:
    """Directory URLs work at domain root and under a hosting subpath."""
    path = posixpath.relpath(target or ".", current or ".")
    return path + "/" if path != "." else "./"


def examples(root: Path) -> dict[str, list[str]]:
    schema, games, _ = sources(root)
    result = {c["name"]: [f"/mc {c['name']}"] for c in schema[0]["options"]}
    result["start"] += [f"/mc start game:{g['id']}" for g in games]
    result["switch"] = [f"/mc switch game:{g['id']} confirm:true" for g in games]
    reset = next(c for c in schema[0]["options"] if c["name"] == "reset")
    choices = {o["name"]: o.get("choices", []) for o in reset["options"]}
    result["reset"] = [
        f"/mc reset game:{g['value']} confirm:true seed:{seed['value']}"
        for g in choices["game"]
        for seed in choices["seed"]
    ]
    return result


def argument_table(command: dict[str, Any]) -> str:
    meanings = {
        "game": "対象Game。STARTでは省略すると選択中Game。SWITCH/RESETでは省略不可。",
        "confirm": "操作の明示確認。省略不可。falseは拒否されます。",
        "seed": "worldのseed方針。省略不可。fixed/newの違いは下記を参照。",
    }
    rows = ["| 引数 | 意味・省略時 | 必須性 | 許容値 |", "|---|---|---|---|"]
    for option in command.get("options", []):
        choices = " / ".join(f"`{c['value']}`" for c in option.get("choices", []))
        if option["type"] == 5:
            choices = "`true`（`false`は拒否）"
        rows.append(
            f"| `{option['name']}` | {meanings[option['name']]} | "
            f"{'必須' if option.get('required', False) else '任意'} | {choices} |"
        )
    return "\n".join(rows) if command.get("options") else "引数はありません。"


def public_markdown(text: str) -> str:
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) >= text.index(END):
        raise ValueError("expected one ordered public region")
    body = text.split(BEGIN)[1].split(END)[0]
    forbidden = (
        r"arn:|\b\d{12,20}\b|\b(?:snap|vol|i|op)-[0-9a-f]{8}|"
        r"/srv/|/var/|/Users/|\.wishicraft\.net|discord\.(?:gg|com/invite)|"
        r"AKIA[A-Z0-9]+|-----BEGIN|(?:token|secret|credential)\s*[:=]"
    )
    if re.search(forbidden, body, re.IGNORECASE):
        raise ValueError("excluded data in public guide")
    return body.strip()


def load_pages(root: Path) -> dict[str, GuidePage]:
    schema, games, facts = sources(root)
    policy = facts["reset"][games[1]["id"]]
    if games[0]["id"] in facts["reset"]:
        raise ValueError("review A capability before publishing")
    values = {
        "version": facts["version"],
        "a-name": games[0]["name"],
        "b-name": games[1]["name"],
        "fixed-seed": str(policy["fixed_seed"]),
        "retain-previous": str(policy["retain_previous"]),
        "minimum-free-gib": f"{policy['minimum_free_bytes'] / 2**30:g}",
    }
    commands = {c["name"]: c for c in schema[0]["options"]}
    if set(commands) != {route.split("/")[1] for route in ROUTES if route.startswith("commands/")}:
        raise ValueError("command pages differ from schema")
    samples = examples(root)
    result = {}
    for route in ROUTES:
        raw = (root / source_path(route)).read_text()
        if not raw.startswith("---\n"):
            raise ValueError("missing page metadata")
        _, header, body = raw.split("---", 2)
        meta = yaml.safe_load(header)
        if set(meta) != {"title", "summary", "roles", "conditions", "warning"}:
            raise ValueError("unknown or missing public page field")
        if not all(isinstance(v, str) for v in meta.values()):
            raise ValueError("page metadata must be text")
        for key, value in values.items():
            body = body.replace("{{" + key + "}}", md_text(value))
            meta = {k: v.replace("{{" + key + "}}", value) for k, v in meta.items()}
        name = route.rsplit("/", 1)[-1]
        if route.startswith("commands/"):
            body = body.replace("{{arguments}}", argument_table(commands[name]))
            body = body.replace(
                "{{examples}}", "\n\n".join(f"```text\n{c}\n```" for c in samples[name])
            )
        if route in {"games/a", "games/b"}:
            game = games[0 if name == "a" else 1]
            body = body.replace("{{game-id}}", game["id"])
            body = body.replace(
                "{{game-examples}}",
                "\n\n".join(
                    f"```text\n{c}\n```"
                    for c in samples["start"] + samples["switch"]
                    if f"game:{game['id']}" in c
                ),
            )
        if "{{" in body or any("{{" in v for v in meta.values()):
            raise ValueError("unknown guide substitution")
        public_markdown(BEGIN + "\n".join(meta.values()) + body + END)
        result[route] = GuidePage(route=route, body=body, **meta)
    return result


def heading_id(title: str) -> str:
    return "section-" + hashlib.sha256(title.encode()).hexdigest()[:12]


def render(body: str, route: str = "") -> tuple[str, str]:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(body)
    headings: set[str] = set()
    nav = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            title = tokens[index + 1].content
            anchor = heading_id(title)
            if anchor in headings or token.tag not in {"h2", "h3"}:
                raise ValueError("duplicate or unsupported heading")
            headings.add(anchor)
            token.attrSet("id", anchor)
            if token.tag == "h2":
                nav.append(f'<a href="#{anchor}">{escape(title)}</a>')
        if token.type == "table_open":
            token.attrSet("class", "arguments")
        for child in token.children or []:
            if child.type == "image":
                raise ValueError("images require an explicit asset review")
            if child.type == "link_open":
                href = child.attrGet("href")
                if not isinstance(href, str):
                    raise ValueError("invalid guide link")
                if href.startswith("#"):
                    continue
                url = urlsplit(href)
                # Authored links name only allowlisted Markdown pages, relative to this source.
                target = posixpath.normpath(posixpath.join(posixpath.dirname(route), url.path))
                target = "" if target == "index.md" else target.removesuffix(".md")
                if url.scheme or url.netloc or url.query or url.fragment or target not in ROUTES:
                    raise ValueError("only allowlisted guide pages are allowed")
                child.attrSet("href", relative_url(route, target))
    for token in tokens:
        for child in token.children or []:
            if child.type == "link_open":
                href = str(child.attrGet("href"))
                if href.startswith("#") and href[1:] not in headings:
                    raise ValueError("broken public anchor")
    return parser.renderer.render(tokens, parser.options, {}), "".join(nav)


def listings(page: GuidePage, pages: dict[str, GuidePage], root: Path) -> str:
    groups = {
        "": ("join", "games", "commands", "help"),
        "games": ("games/a", "games/b"),
        "commands": tuple(r for r in ROUTES if r.startswith("commands/")),
    }
    if page.route not in groups:
        return ""
    _, _, facts = sources(root)
    cards = []
    for target in groups[page.route]:
        item = pages[target]
        extra = ""
        if page.route == "games":
            extra = (
                f"<p>Java Edition {escape(facts['version'])} · Vanilla<br>"
                "同じ版の標準Java client</p>"
            )
            extra += f"<p>Reset：{'対応（Bのみ）' if target == 'games/b' else '非対応'}</p>"
        if page.route == "commands":
            extra = (
                f"<p><b>権限：</b>{escape(item.roles)}<br>"
                f"<b>条件：</b>{escape(item.conditions)}</p>"
            )
            if item.warning:
                extra += f'<p class="short-warning">{escape(item.warning)}</p>'
        cards.append(
            f'<section class="card"><h2><a href="{relative_url(page.route, target)}">'
            f"{escape(item.title)}</a></h2><p>{escape(item.summary)}</p>{extra}"
            f'<a class="detail-link" href="{relative_url(page.route, target)}">'
            f'{escape(item.title)}の詳細へ <span aria-hidden="true">→</span></a></section>'
        )
    return '<div class="listing">' + "".join(cards) + "</div>"


def page_html(page: GuidePage, pages: dict[str, GuidePage], root: Path) -> str:
    content, toc = render(page.body, page.route)
    nav = []
    for target in ("", "join", "games", "commands", "help"):
        current = page.route == target or (target and page.route.startswith(target + "/"))
        attr = (
            ' aria-current="page"'
            if page.route == target
            else (' class="active"' if current else "")
        )
        nav.append(
            f'<a href="{relative_url(page.route, target)}"{attr}>'
            f"{escape('ホーム' if not target else pages[target].title)}</a>"
        )
    parent = page.route.split("/")[0] if "/" in page.route else ""
    crumbs = f'<a href="{relative_url(page.route, "")}">ホーム</a>' if page.route else ""
    if parent:
        crumbs += (
            f' / <a href="{relative_url(page.route, parent)}">{escape(pages[parent].title)}</a>'
        )
    crumbs += (" / " if crumbs else "") + f'<span aria-current="page">{escape(page.title)}</span>'
    conditions = ""
    if page.roles:
        conditions = '<section class="conditions"><h2>利用条件</h2>' + (
            f"<p><b>権限：</b>{escape(page.roles)}。指定の操作チャンネルで実行します。</p>"
            f"<p><b>実行条件：</b>{escape(page.conditions)}</p></section>"
        )
    warning = (
        f'<aside class="warning" aria-label="重要な注意">{escape(page.warning)}</aside>'
        if page.warning
        else ""
    )
    toc_html = f'<nav class="toc" aria-label="ページ内目次">{toc}</nav>' if toc else ""
    back = (
        f'<p class="back"><a href="{relative_url(page.route, parent)}">← '
        f"{escape(pages[parent].title if parent else 'ホーム')}へ戻る</a></p>"
        if page.route
        else ""
    )
    body_html = listings(page, pages, root) + f"<article>{content}</article>"
    asset = posixpath.relpath("guide.css", page.route or ".")
    script = posixpath.relpath("guide.js", page.route or ".")
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">
<meta name="referrer" content="no-referrer">
<title>{escape(page.title)} | Wishicraft 利用ガイド</title>
<link rel="stylesheet" href="{asset}"><script src="{script}" defer></script></head>
<body><a class="skip" href="#content">本文へ移動</a>
<header><a class="brand" href="{relative_url(page.route, "")}">Wishicraft 利用ガイド</a>
<nav aria-label="共通ナビゲーション">{"".join(nav)}</nav></header>
<main id="content" tabindex="-1"><nav class="breadcrumbs" aria-label="現在位置">{crumbs}</nav>
<h1>{escape(page.title)}</h1><p class="summary">{escape(page.summary)}</p>
{conditions}{warning}{toc_html}{body_html}{back}
</main><footer>dev環境の静的利用案内です。現在の状態はDiscordの
<a href="{relative_url(page.route, "commands/status")}">/mc status</a> で確認してください。</footer>
<p id="copy-feedback" class="copy-feedback" role="status" aria-live="polite"></p></body></html>
'''


def build(root: Path, output: Path) -> None:
    pages = load_pages(root)
    files = {
        f"{r}/index.html" if r else "index.html": page_html(p, pages, root)
        for r, p in pages.items()
    }
    files["404.html"] = """<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ページが見つかりません</title><h1>ページが見つかりません</h1>
<p>URLを確認し、利用ガイドのホームから開き直してください。</p></html>"""
    files["_headers"] = (
        "/*\n  Content-Security-Policy: " + CSP + "; frame-ancestors 'none'\n"
        "  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
        "  X-Frame-Options: DENY\n  Cache-Control: public, max-age=0, must-revalidate\n"
    )
    for name in ASSETS:
        files[name] = (root / "web" / name).read_text()
    if set(files) != OUTPUTS:
        raise ValueError("public output allowlist mismatch")
    output.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True, help="new, dedicated site directory")
    args = cli.parse_args()
    build(ROOT, args.output)


if __name__ == "__main__":
    main()
