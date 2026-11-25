#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 fgo-wiki 的「从者-羁绊加成礼装」反查表固化成 card/bondce.json。

开发期脚本：直接复用 fgo-wiki/card-render/cardkit/bondce.py 的解析结果，
避免插件运行时读 wiki。最终插件里只有这份 JSON（约几十 KB）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CR = Path("/home/mila/fgo-wiki/card-render")
OUT = ROOT / "card" / "bondce.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card-render", type=Path, default=DEFAULT_CR)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "fgo.db")
    ap.add_argument("--wiki", type=Path, default=Path("/home/mila/fgo-wiki"))
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    a = ap.parse_args()

    spec = importlib.util.spec_from_file_location("wiki_bondce", a.card_render / "cardkit" / "bondce.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # 把 wiki 路径指到实际目录（模块默认按 Path.home() 推）
    mod.WIKI = a.wiki
    mod.REVERSE = a.wiki / "entities" / "bond-ce" / "从者适配反查.md"
    mod.INDEX = a.wiki / "entities" / "bond-ce" / "index.md"

    import zlib

    con = sqlite3.connect(a.db)
    nos = []
    if _has_no(con):
        for (blob,) in con.execute("SELECT data FROM servant_cards"):
            try:
                nos.append(int(json.loads(zlib.decompress(blob))["no"]))
            except Exception:
                pass
    con.close()

    mapping = {str(n): mod.lookup(n) for n in nos if n}
    mapping = {k: v for k, v in mapping.items() if v}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(mapping, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{a.out}  {len(mapping)} 个从者有羁绊礼装适性  {a.out.stat().st_size / 1024:.0f} KB")
    return 0


def _has_no(con: sqlite3.Connection) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='servant_cards'").fetchone())


if __name__ == "__main__":
    sys.exit(main())
