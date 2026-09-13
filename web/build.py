"""Build only allowlisted guide pages and assets from reviewed Markdown and schema."""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from markdown_it import MarkdownIt

from web.canonical import sources as sources

ROOT = Path(__file__).resolve().parents[1]
BASE_ROUTES = (
    "",
    "join",
    "games",
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
BEGIN = "<!-- public-guide:begin -->"
END = "<!-- public-guide:end -->"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'"
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
    if route not in BASE_ROUTES and not re.fullmatch(r"games/[a-z0-9]+(?:-[a-z0-9]+)*", route):
        raise ValueError("page outside public allowlist")
    return CONTENT / (f"{route}.md" if route else "index.md")


def relative_url(current: str, target: str) -> str:
    """Directory URLs work at domain root and under a hosting subpath."""
    path = posixpath.relpath(target or ".", current or ".")
    return path + "/" if path != "." else "./"


def public_games(root: Path) -> list[dict[str, Any]]:
    schema, records, facts = sources(root)
    by_id = {g["id"]: g for g in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate canonical Game ID")
    registrations = yaml.safe_load((root / "web/games.yaml").read_text())
    if not isinstance(registrations, list) or not registrations:
        raise ValueError("public Game registration must be a nonempty list")
    commands = {c["name"]: c for c in schema[0]["options"]}
    result = []
    slugs: set[str] = set()
    ids: set[str] = set()
    for entry in registrations:
        if not isinstance(entry, dict) or set(entry) != {"id", "slug", "client"}:
            raise ValueError("invalid public Game registration fields")
        game_id = entry.get("id")
        if not isinstance(game_id, str) or not re.fullmatch(r"game-[a-z0-9-]+", game_id):
            raise ValueError("invalid public Game ID")
        slug = entry.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError(f"{game_id}: invalid public slug")
        if slug in slugs or game_id in ids:
            raise ValueError(f"{game_id}: duplicate public slug or ID")
        slugs.add(slug)
        ids.add(game_id)
        if game_id not in by_id:
            raise ValueError(f"{game_id}: missing canonical Game")
        game = dict(by_id[game_id])
        for key in ("name", "edition", "version", "server"):
            if not isinstance(game.get(key), str) or not game[key].strip():
                raise ValueError(f"{game_id}: missing {key}")
        client = entry.get("client", {})
        if not isinstance(client, dict):
            raise ValueError(f"{game_id}: missing client metadata")
        if client.get("status") not in {"confirmed_none", "required", "unknown"}:
            raise ValueError(f"{game_id}: missing or invalid client.status")
        for key in ("loader", "pack", "preparation"):
            if not isinstance(client.get(key), str) or not client[key].strip():
                raise ValueError(f"{game_id}: missing client.{key}")
        available = []
        for name, command in commands.items():
            option = next((o for o in command.get("options", []) if o["name"] == "game"), None)
            if option is None or game_id in {c["value"] for c in option.get("choices", [])}:
                available.append(name)
        reset = facts["reset"].get(game_id)
        if (reset is not None) != ("reset" in available):
            raise ValueError(f"{game_id}: Reset policy/schema mismatch")
        game.update(slug=slug, client=client, reset=reset, commands=available)
        public_markdown(BEGIN + str(game) + END)
        result.append(game)
    return result


def routes(root: Path) -> tuple[str, ...]:
    return (*BASE_ROUTES, *(f"games/{g['slug']}" for g in public_games(root)))


def outputs(root: Path) -> set[str]:
    return {
        *(f"{r}/index.html" if r else "index.html" for r in routes(root)),
        "404.html",
        "guide.css",
        "guide.js",
        "_headers",
    }


def examples(root: Path) -> dict[str, list[str]]:
    schema, _, _ = sources(root)
    games = public_games(root)
    result: dict[str, list[str]] = {}
    for command in schema[0]["options"]:
        name = command["name"]
        options = {o["name"]: o for o in command.get("options", [])}
        result[name] = [] if options.get("game", {}).get("required") else [f"/mc {name}"]
        if "game" not in options:
            continue
        for game in games:
            if name not in game["commands"]:
                continue
            base = f"/mc {name} game:{game['id']}"
            if "confirm" in options:
                base += " confirm:true"
            if "seed" in options:
                result[name] += [f"{base} seed:{c['value']}" for c in options["seed"]["choices"]]
            else:
                result[name].append(base)
    return result


def supported_games(root: Path, name: str) -> str:
    blocks = []
    for g in public_games(root):
        if name not in g["commands"]:
            continue
        line = f"- [{md_text(g['name'])}](../games/{g['slug']}.md)"
        if name == "reset":
            p = g["reset"]
            line += (
                f"：fixed = seed {p['fixed_seed']}。"
                f"current＋直近{p['retain_previous']}個のmanaged旧world。"
                f"容量は{p['minimum_free_bytes'] / 2**30:g} GiBと"
                "現在領域のファイル総量×2の大きい方以上。"
            )
        blocks.append(line)
    return "\n".join(blocks) or "現在の公開対象Gameに対応するものはありません。"


def requirements(game: dict[str, Any]) -> str:
    c = game["client"]
    status = {
        "confirmed_none": "追加MOD不要と確認済み",
        "required": "必要なclient構成を明示",
        "unknown": "未確認：参加前に管理者へ確認してください",
    }[c["status"]]
    return "\n".join(
        f"- {label}：{md_text(value)}"
        for label, value in (
            ("edition", game["edition"]),
            ("Minecraft version", game["version"]),
            ("server種類", game["server"]),
            ("client確認状況", status),
            ("loader・版", c["loader"]),
            ("MODパック・版", c["pack"]),
            ("追加準備", c["preparation"]),
        )
    )


def argument_table(command: dict[str, Any], public_ids: set[str]) -> str:
    meanings = {
        "game": "対象Game。STARTでは省略すると選択中Game。SWITCH/RESETでは省略不可。",
        "confirm": "操作の明示確認。省略不可。falseは拒否されます。",
        "seed": "worldのseed方針。省略不可。fixed/newの違いは下記を参照。",
    }
    rows = ["| 引数 | 意味・省略時 | 必須性 | 許容値 |", "|---|---|---|---|"]
    for option in command.get("options", []):
        choices = " / ".join(
            f"`{c['value']}`"
            for c in option.get("choices", [])
            if option["name"] != "game" or c["value"] in public_ids
        )
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
    schema, _, _ = sources(root)
    games = {f"games/{g['slug']}": g for g in public_games(root)}
    commands = {c["name"]: c for c in schema[0]["options"]}
    if set(commands) != {r.split("/")[1] for r in BASE_ROUTES if r.startswith("commands/")}:
        raise ValueError("command pages differ from schema")
    samples = examples(root)
    result = {}
    for route in routes(root):
        game = games.get(route)
        path = CONTENT / "games/_page.md" if game else source_path(route)
        raw = (root / path).read_text()
        _, header, body = raw.split("---", 2)
        meta = yaml.safe_load(header)
        if set(meta) != {"title", "summary", "roles", "conditions", "warning"}:
            raise ValueError("unknown or missing public page field")
        if not all(isinstance(v, str) for v in meta.values()):
            raise ValueError("page metadata must be text")
        values = {}
        for shared in ("access", "connection"):
            if "{{" + shared + "}}" in body:
                body = body.replace(
                    "{{" + shared + "}}",
                    (root / CONTENT / "shared" / f"{shared}.md").read_text().strip(),
                )
        name = route.rsplit("/", 1)[-1]
        if route.startswith("commands/"):
            body = body.replace(
                "{{arguments}}", argument_table(commands[name], {g["id"] for g in games.values()})
            )
            body = body.replace(
                "{{examples}}", "\n\n".join(f"```text\n{c}\n```" for c in samples[name])
            )
            body = body.replace("{{supported-games}}", supported_games(root, name))
        if game:
            body = body.replace("{{game-id}}", game["id"])
            _, intro_meta, notes = (root / source_path(route)).read_text().split("---", 2)
            intro = yaml.safe_load(intro_meta)
            if set(intro) != {"summary", "warning"} or not all(
                isinstance(v, str) for v in intro.values()
            ):
                raise ValueError(f"{game['id']}: missing Game summary/warning")
            values = {
                "game-name": game["name"],
                "game-summary": intro["summary"],
                "game-warning": intro["warning"],
            }
            body = body.replace("{{requirements}}", requirements(game)).replace(
                "{{game-notes}}", notes.strip()
            )
            body = body.replace(
                "{{game-examples}}",
                "\n\n".join(
                    f"```text\n{c}\n```"
                    for n in ("start", "switch")
                    for c in samples[n]
                    if f"game:{game['id']}" in c.split()
                ),
            )
            operations = " / ".join(f"[{n}](../commands/{n}.md)" for n in game["commands"])
            operations += "\n\nReset：" + (
                "対応。選択中・稼働中・観測0人・明示確認が必要です。worldとプレイヤー状態を新しくします。"
                if game["reset"]
                else "非対応。"
            )
            operations += (
                " BACKUPは正常停止中（STOPPED/HEALTHY）専用で、共有Data EBS全体を保護します。"
            )
            body = body.replace("{{operations}}", operations)
        for key, value in values.items():
            body = body.replace("{{" + key + "}}", md_text(value))
            meta = {k: v.replace("{{" + key + "}}", value) for k, v in meta.items()}
        if "{{" in body or any("{{" in v for v in meta.values()):
            raise ValueError(f"{route}: unknown guide substitution")
        public_markdown(BEGIN + "\n".join(meta.values()) + body + END)
        result[route] = GuidePage(route=route, body=body, **meta)
    return result


def heading_id(title: str) -> str:
    return "section-" + hashlib.sha256(title.encode()).hexdigest()[:12]


def render(body: str, route: str = "", allowed: tuple[str, ...] = BASE_ROUTES) -> tuple[str, str]:
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
                if url.scheme or url.netloc or url.query or url.fragment or target not in allowed:
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
        "": ("games", "commands", "join", "help"),
        "games": tuple(r for r in pages if r.startswith("games/")),
        "commands": tuple(r for r in pages if r.startswith("commands/")),
    }
    if page.route not in groups:
        return ""
    games = {f"games/{g['slug']}": g for g in public_games(root)}
    cards = []
    for target in groups[page.route]:
        item = pages[target]
        extra = ""
        if page.route == "games":
            g = games[target]
            extra = (
                f"<p>{escape(g['edition'])} {escape(g['version'])} · {escape(g['server'])}<br>"
                f"{escape(g['client']['loader'])}<br>{escape(g['client']['pack'])}</p>"
            )
            extra += f"<p>Reset：{'対応' if g['reset'] else '非対応'}</p>"
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
    content, toc = render(page.body, page.route, tuple(pages))
    nav = []
    for target in ("", "games", "commands", "join", "help"):
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
    if set(files) != outputs(root):
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
