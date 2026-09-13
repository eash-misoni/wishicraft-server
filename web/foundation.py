"""Build the integrated Web bundle separately from the frozen public guide allowlist."""

from __future__ import annotations

import json
from pathlib import Path

from web.build import build, outputs


def build_foundation(root: Path, output: Path) -> None:
    build(root, output)
    for name in outputs(root):
        if not name.endswith("index.html"):
            continue
        path = output / name
        content = path.read_text().replace(
            "</nav></header>", '<a href="/manage/">管理</a></nav></header>'
        )
        path.write_text(content)
    (output / "manage").mkdir()
    (output / "manage/index.html").write_text((root / "web/manage.html").read_text())
    (output / "manage.js").write_text((root / "web/manage.js").read_text())
    public = outputs(root) - {"_headers"}
    (output / "routes.json").write_text(
        json.dumps(sorted(public | {"manage/index.html", "manage.js"}))
    )
