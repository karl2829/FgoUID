#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 FGOUID 数据库渲染一张从者卡（开发期自测用，不需要 GsCore）。

用法：
    .render-venv/bin/python tools/render_card.py 704000 -o out/card.png
    .render-venv/bin/python tools/render_card.py 摩根 -o out/card.png        # 也可以给名字
    .render-venv/bin/python tools/render_card.py 704000 --assets-report
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fgo.db"


def load_plugin_card():
    """按包路径导入插件里的 card 包（避免依赖 sys.path 布局）。"""
    spec = importlib.util.spec_from_file_location(
        "fgouid_card", ROOT / "card" / "__init__.py", submodule_search_locations=[str(ROOT / "card")]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fgouid_card"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    import fgouid_card.build as build  # noqa: E402
    import fgouid_card.fetch as fetch  # noqa: E402

    return build, fetch


def model_for(con: sqlite3.Connection, key: str) -> dict:
    row = con.execute("SELECT data FROM servant_cards WHERE id = ?", (key,)).fetchone()
    if row is None:  # 按名字/index 找
        r = con.execute(
            "SELECT id FROM servants WHERE name = ? OR name LIKE ? ORDER BY CASE region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1",
            (key, f"%{key}%"),
        ).fetchone()
        if r is None:
            raise SystemExit(f"找不到从者：{key}")
        row = con.execute("SELECT data FROM servant_cards WHERE id = ?", (r[0],)).fetchone()
        if row is None:
            raise SystemExit(f"{key} 有从者记录但没有卡片数据，先跑 tools/sync_cards.py")
    return json.loads(zlib.decompress(row[0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key", help="内部ID 或 从者名")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--dpr", type=int, default=2)
    ap.add_argument("--assets-report", action="store_true")
    ap.add_argument("--db", type=Path, default=DB)
    a = ap.parse_args()

    build, fetch = load_plugin_card()
    con = sqlite3.connect(a.db)
    data = model_for(con, a.key)
    con.close()

    html = build.build_html(data)
    names = build.assets_used(html)
    extra = fetch.extra_images(data, names)
    out = Path(a.out) if a.out else ROOT / "out" / f"card_{data.get('servant_id')}.png"
    r = build.render_card(data, out, extra_images=extra, dpr=a.dpr)
    print(r["log"])
    print(f"素材 {len(names)} 个（其中 {len(extra)} 个从缓存/网络取）")
    if a.assets_report:
        print("assets:", json.dumps(names, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
