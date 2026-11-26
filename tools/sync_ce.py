#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""礼装（概念礼装）补充数据：卡面图、未破/满破效果、ATK/HP、图鉴编号。

为什么单独一张表：`craft_essences` 是「人读的 MD」派生（只有一行 effect 文本），
卡面图、满破效果这些只在 raw JSON 里有。单独存 `ce_details` 不动主表，
`fgo礼装` 的卡片渲染按 id 关联；raw 里没有的礼装（日服独有/活动纪念）就保持文字降级。

用法：
    python tools/sync_ce.py --wiki /home/mila/fgo-wiki
    python tools/sync_ce.py --wiki /home/mila/fgo-wiki --region CN
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "fgo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ce_details(
    id TEXT NOT NULL,
    region TEXT NOT NULL,
    collection_no INTEGER,
    name_jp TEXT,
    art_url TEXT,
    icon_url TEXT,
    atk_base INTEGER, atk_max INTEGER,
    hp_base INTEGER, hp_max INTEGER,
    lv_max INTEGER,
    effects TEXT,
    PRIMARY KEY (id, region)
);
"""


def _art_url(assets: dict) -> str:
    chara = (assets or {}).get("charaGraph") or {}
    flat: dict[str, str] = {}
    for _kind, group in chara.items():
        if isinstance(group, dict):
            for _k, url in group.items():
                if isinstance(url, str) and url:
                    flat[url] = url
        elif isinstance(group, str) and group:
            flat[group] = group
    if not flat:
        return ""
    # 优先 a（满破前）→ 任意
    for url in sorted(flat):
        if re.search(r"\da\.png$", url):
            return url
    return sorted(flat)[0]


def _effects(raw: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for sk in raw.get("skills") or []:
        detail = (sk.get("detail") or "").strip()
        if not detail:
            continue
        # 满破那版是 priority 2，其余（未破）当 priority 1
        prio = 2 if int(sk.get("priority") or 0) >= 2 else 1
        key = re.sub(r"\s+", "", detail)
        if key in seen:
            continue
        seen.add(key)
        out.append({"detail": detail, "priority": prio})
    out.sort(key=lambda e: e["priority"])
    return out


def sync(wiki: Path, con: sqlite3.Connection, regions: list[str]) -> dict:
    con.executescript(SCHEMA)
    total = kept = 0
    for region in regions:
        files = sorted((wiki / "raw" / "craft-essences" / region).glob("*.json"))
        for f in files:
            total += 1
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            effects = _effects(raw)
            art = _art_url(raw.get("extraAssets") or {})
            skills = raw.get("skills") or []
            icon = (skills[0].get("icon") or "") if skills else ""
            if not art and not effects:
                continue
            con.execute(
                "INSERT OR REPLACE INTO ce_details (id, region, collection_no, name_jp,"
                " art_url, icon_url, atk_base, atk_max, hp_base, hp_max, lv_max, effects)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(raw.get("id") or f.stem), region,
                    raw.get("collectionNo"), raw.get("originalName") or "",
                    art, icon,
                    int(raw.get("atkBase") or 0), int(raw.get("atkMax") or 0),
                    int(raw.get("hpBase") or 0), int(raw.get("hpMax") or 0),
                    int(raw.get("lvMax") or 0),
                    json.dumps(effects, ensure_ascii=False),
                ),
            )
            kept += 1
    return {"raw_files": total, "stored": kept}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="/home/mila/fgo-wiki")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--region", default=None, help="只处理某个区服（CN/JP），默认两个都做")
    a = ap.parse_args()

    wiki = Path(a.wiki)
    if not wiki.is_dir():
        raise SystemExit(f"wiki 路径不存在：{wiki}")
    regions = [a.region] if a.region else ["CN", "JP"]
    con = sqlite3.connect(a.db)
    try:
        stats = sync(wiki, con, regions)
        con.commit()
        size = a.db.stat().st_size
    finally:
        con.close()
    print(f"礼装补充：raw {stats['raw_files']} → 入库 {stats['stored']}；DB {size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
