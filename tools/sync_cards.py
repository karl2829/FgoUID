#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 fgo-wiki 的从者卡数据模型批量同步进 FGOUID 的 SQLite（开发期脚本）。

数据从哪里来：直接复用 fgo-wiki/card-render 的 ``parse_servant()``——也就是
「出图脚本先写在 wiki 里」的那一份解析器，不在这里重复实现。等插件定型后，
把这个解析器连同 cardkit/templates 一起拷进插件，本脚本改成 import 插件内副本即可。

存什么：每张卡的完整模型 JSON，zlib 压缩后进 ``servant_cards`` 表
（实测平均 4.3KB / 压缩后 1.4KB，458 个国服从者约 0.7MB）。

用法：
    python tools/sync_cards.py                       # 全量（CN）
    python tools/sync_cards.py --limit 5 --verbose   # 先跑 5 个看看
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "fgo.db"
DEFAULT_WIKI = Path("/home/mila/fgo-wiki")
DEFAULT_CR = Path("/home/mila/fgo-wiki/card-render")

SCHEMA = """
CREATE TABLE IF NOT EXISTS servant_cards (
    id      TEXT NOT NULL,
    region  TEXT NOT NULL DEFAULT 'CN',
    data    BLOB NOT NULL,          -- zlib 压缩的卡片模型 JSON
    built_at TEXT,
    PRIMARY KEY (id, region)
);
"""


def load_card_render(cr_dir: Path, wiki: Path):
    """把 card-render/build_data.py 作为模块加载（并把它指向给定 wiki）。"""
    path = cr_dir / "build_data.py"
    if not path.is_file():
        raise SystemExit(f"找不到解析器：{path}")
    spec = importlib.util.spec_from_file_location("fgo_card_build_data", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.WIKI = wiki
    # 资产目录指到临时位置：同步阶段不下载立绘/图标（插件运行时按需拉）
    mod.ASSETS = cr_dir / "assets"
    return mod


def servant_ids(con: sqlite3.Connection, region: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT id FROM servants WHERE region = ? ORDER BY CAST(id AS INTEGER)", (region,))]


def main() -> int:
    ap = argparse.ArgumentParser(description="同步从者卡数据模型进 FGOUID 数据库")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    ap.add_argument("--card-render", type=Path, default=DEFAULT_CR)
    ap.add_argument("--region", default="CN", choices=["CN", "JP"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    if not a.wiki.is_dir():
        raise SystemExit(f"wiki 不存在：{a.wiki}")
    mod = load_card_render(a.card_render, a.wiki)

    con = sqlite3.connect(a.db)
    con.executescript(SCHEMA)
    ids = servant_ids(con, a.region)
    if a.limit:
        ids = ids[: a.limit]
    print(f"待处理 {len(ids)} 个{con.execute('SELECT COUNT(*) FROM servants WHERE region=?', (a.region,)).fetchone()[0]}个中")

    before = a.db.stat().st_size
    ok, fail, raw_bytes, comp_bytes = 0, 0, 0, 0
    errors: list[tuple[str, str]] = []
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    t0 = time.perf_counter()

    for i, sid in enumerate(ids, 1):
        try:
            data = mod.parse_servant(sid)
            blob = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"), 9)
            con.execute(
                "INSERT OR REPLACE INTO servant_cards (id, region, data, built_at) VALUES (?,?,?,?)",
                (sid, a.region, blob, now),
            )
            ok += 1
            raw_bytes += len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            comp_bytes += len(blob)
            if a.verbose:
                print(f"  {sid} No.{data.get('no')} {data.get('name')} "
                      f"{data.get('class')} ★{data.get('rarity')} 技能{len(data.get('skills', []))}"
                      f" 宝具{len(data.get('np', {}).get('effects', []))}条")
        except Exception as e:  # 单个从者解析失败不该拖垮整批
            fail += 1
            errors.append((sid, f"{type(e).__name__}: {e}"))
        if i % 50 == 0:
            con.commit()
            print(f"  … {i}/{len(ids)}  ok={ok} fail={fail}")
    con.commit()
    con.close()

    el = time.perf_counter() - t0
    after = a.db.stat().st_size
    print(f"\n完成：ok={ok} fail={fail}  耗时 {el:.0f}s")
    print(f"卡片 JSON 原始 {raw_bytes / 1024 / 1024:.1f} MB → 压缩 {comp_bytes / 1024 / 1024:.2f} MB")
    print(f"数据库 {before / 1024 / 1024:.2f} MB → {after / 1024 / 1024:.2f} MB")
    if errors:
        print(f"失败样例（前 10）：")
        for sid, err in errors[:10]:
            print(f"  {sid}: {err}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
