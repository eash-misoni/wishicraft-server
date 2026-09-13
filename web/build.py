"""Build only the reviewed public Markdown region and three explicit local assets."""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt

from wishicraft.reset_commands import extend
from wishicraft.reset_policy import policies
from wishicraft.runtime_catalog import RuntimeCatalog
from wishicraft.two_game_admin import declaration

ROOT = Path(__file__).resolve().parents[1]
GUIDE = Path("docs/discord_user_guide.md")
BEGIN = "<!-- public-guide:begin -->"
END = "<!-- public-guide:end -->"
ASSETS = ("guide.css", "guide.js")
OUTPUTS = {"index.html", "404.html", "guide.css", "guide.js", "_headers"}
SECTIONS = {
    "参加の準備": "join",
    "Game一覧と詳細": "games",
    "使えるコマンド": "commands",
    "引数の一覧": "arguments",
    "Resetで変わるもの・残るもの": "reset",
    "受付・経過・失敗の見方": "help",
}
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


def generated(root: Path) -> dict[str, str]:
    commands, games, facts = sources(root)
    lines = ["## Game一覧と詳細", "", "同時に遊べるGameは一つです。", ""]
    for label, game in zip(("A", "B"), games, strict=True):
        title = f"{label} · {md_text(game['name'])}"
        lines.append(f"[{label}の詳細](#{heading_id(title)})")
    lines += [""]
    for label, game in zip(("A", "B"), games, strict=True):
        lines += [
            f"### {label} · {md_text(game['name'])}",
            "",
            f"- コマンドで選ぶ名前：`{game['id']}`",
            f"- Minecraft Java Edition **{facts['version']}** / Vanilla（A・B共通）",
        ]
        policy = facts["reset"].get(game["id"])
        if policy:
            lines += [
                "- B専用の保存領域。対応条件を満たす場合にResetできます。",
                f"- Reset：`fixed`はseed **{policy['fixed_seed']}**。"
                f"current＋直近 **{policy['retain_previous']}** managed旧worldを保持。",
                "- 元Bのanchorは別枠で自動削除対象外です。",
            ]
        else:
            lines += ["- A専用の保存領域。現在Resetには対応していません。"]
        lines += [""]
    args = ["## 引数の一覧", "", "Discordの候補から選択してください。", ""]
    for command in commands[0]["options"]:
        args += [f"### /mc {command['name']}", ""]
        options = command.get("options", [])
        if not options:
            args += ["引数なし。", ""]
        for option in options:
            required = "必須" if option.get("required", False) else "省略可"
            choices = " / ".join(f"`{c['value']}`" for c in option.get("choices", []))
            if option["type"] == 5:
                choices = "`true`（明示確認。`false`は拒否）"
            args += [f"- `{option['name']}`：{required}。{choices}"]
        args += [""]
    return {"games": "\n".join(lines).strip(), "arguments": "\n".join(args).strip()}


def update_generated(text: str, root: Path) -> str:
    for name, content in generated(root).items():
        start, end = f"<!-- generated:{name}:begin -->", f"<!-- generated:{name}:end -->"
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError(f"expected one generated region: {name}")
        before, rest = text.split(start)
        _, after = rest.split(end)
        text = before + start + "\n\n" + content + "\n\n" + end + after
    return text


def public_markdown(text: str) -> str:
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) >= text.index(END):
        raise ValueError("expected one ordered public region")
    body = text.split(BEGIN)[1].split(END)[0]
    body = re.sub(r"<!-- generated:(games|arguments):(begin|end) -->", "", body)
    # New public content is reviewed in Git; reject obvious internal/endpoint additions as well.
    forbidden = (
        r"arn:|\b\d{12,20}\b|\b(?:snap|vol|i|op)-[0-9a-f]{8}|"
        r"/srv/|/var/|/Users/|\.wishicraft\.net|discord\.(?:gg|com/invite)|"
        r"AKIA[A-Z0-9]+|-----BEGIN|(?:token|secret|credential)\s*[:=]"
    )
    if re.search(forbidden, body, re.IGNORECASE):
        raise ValueError("excluded data in public guide")
    return body.strip()


def heading_id(title: str) -> str:
    return SECTIONS.get(title, "section-" + hashlib.sha256(title.encode()).hexdigest()[:12])


def render(body: str) -> tuple[str, str]:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(body)
    nav: list[str] = []
    headings: set[str] = set()
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
        for child in token.children or []:
            if child.type == "image":
                raise ValueError("images require an explicit asset review")
            if child.type == "link_open":
                href = child.attrGet("href") or ""
                if not isinstance(href, str) or not re.fullmatch(r"#[a-z0-9-]+", href):
                    raise ValueError("only internal anchors are allowed in public Markdown")
    for token in tokens:
        for child in token.children or []:
            if child.type == "link_open" and str(child.attrGet("href"))[1:] not in headings:
                raise ValueError("broken public anchor")
    return parser.renderer.render(tokens, parser.options, {}), "".join(nav)


def page(content: str, nav: str) -> str:
    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">
<meta name="referrer" content="no-referrer">
<meta name="description" content="Wishicraftの参加準備、Game、Discordコマンドと安全な操作の案内。">
<title>遊び方ガイド | Wishicraft</title>
<link rel="stylesheet" href="guide.css">
<script src="guide.js" defer></script>
</head>
<body>
<a class="skip" href="#content">本文へ移動</a>
<header><a class="brand" href="index.html">WISHICRAFT<span>PLAYER GUIDE</span></a>
<span class="edition">遊ぶ前に、ここから。</span></header>
<div class="layout"><aside><nav aria-label="このページの目次">{nav}</nav></aside>
<main id="content" tabindex="-1">
<div class="hero"><p class="eyebrow">WISHICRAFT / 遊び方ガイド</p>
<h1>集まる。選ぶ。<br>世界をつづける。</h1>
<p>参加の準備から、いつもの操作、困ったときまで。</p>
<a class="primary" href="#join">参加の準備を見る <span aria-hidden="true">↗</span></a></div>
<div class="status-note">このページは静的な案内です。
現在の状態はDiscordの <code>/mc status</code> で確認してください。</div>
<article>{content}</article>
<footer>Wishicraft · 利用案内<br>操作はDiscordの指定チャンネルで行ってください。</footer>
</main></div><p id="copy-feedback" class="copy-feedback" role="status" aria-live="polite"></p>
</body></html>
'''


def build(root: Path, output: Path) -> None:
    text = (root / GUIDE).read_text()
    if update_generated(text, root) != text:
        raise ValueError("generated guide is stale: run uv run python -m web.build --update-guide")
    content, nav = render(public_markdown(text))
    files = {"index.html": page(content, nav)}
    files["404.html"] = """<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ページが見つかりません | Wishicraft</title>
<h1>ページが見つかりません</h1><p><a href="./">利用案内へ戻る</a></p></html>"""
    files["_headers"] = (
        "/*\n  Content-Security-Policy: " + CSP + "; frame-ancestors 'none'\n"
        "  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
        "  X-Frame-Options: DENY\n  Cache-Control: public, max-age=0, must-revalidate\n"
    )
    for name in ASSETS:
        files[name] = (root / "web" / name).read_text()
    # No merge/copytree: stale files, symlinks, and accidental repository serving are excluded.
    output.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        (output / name).write_text(value, encoding="utf-8")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="new, dedicated site directory")
    mode.add_argument("--update-guide", action="store_true")
    args = cli.parse_args()
    if args.update_guide:
        path = ROOT / GUIDE
        path.write_text(update_generated(path.read_text(), ROOT))
    else:
        build(ROOT, args.output)


if __name__ == "__main__":
    main()
