#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 fgo-wiki 的 **raw 抓取结果** 回填 gacha / events 的空字段。

为什么需要这一步：wiki 的 MD 是给人看的，不少字段留空——
卡池 UP 从者 79/91 是空的、活动名直接写成 ID、banner 图根本没进库。
`raw/gacha/gacha_raw.json`（Mooncell 卡池一览）和 `raw/events/<region>/*.json`（Atlas）
里有结构化字段，按 ID 回填即可，**不改 MD**，wiki 仍然是唯一数据源。

回填内容：
  gacha.banner     卡池横幅（jsdelivr 上的 fgo-images 仓库，国内访问快）
  gacha.up_ids     本期 UP 的内部 ID（从 collectionNo 反查）
  gacha.up_servants UP 从者名（MD 里已有就保留，raw 有就覆盖成完整列表）
  events.name      名字还是 ID 时，用 raw 里的正式名替换
  events.banner    活动横幅（Atlas）

用法：
    python tools/sync_gacha.py --wiki /home/mila/fgo-wiki
    python tools/sync_gacha.py --wiki /home/mila/fgo-wiki --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "fgo.db"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


# wiki MD 里偶尔会写「（从者列表待 Mooncell 模拟器补充）：共 0 骑」这类占位文案，
# 回填时清掉，别让卡片上出现这种句子。
_PLACEHOLDER = re.compile(r"[（(][^）)]*(待[^）)]*补充|模拟器补充|共\s*0\s*骑)[^）)]*[）)]|共\s*0\s*骑")


def _clean_up(text: str) -> str:
    text = _PLACEHOLDER.sub("", text or "")
    text = re.sub(r"\s*/\s*(?=/)|^\s*/\s*|\s*/\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip(" /")


def _ensure_columns(con: sqlite3.Connection) -> None:
    """老库也要能补（sync_from_wiki 重建成新 schema 后这里是空操作）。"""
    cols = {
        "gacha": {"banner": "TEXT", "up_ids": "TEXT"},
        "events": {"banner": "TEXT"},
    }
    for table, want in cols.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue
        for name, typ in want.items():
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def _servant_names(con: sqlite3.Connection, collection_ids) -> tuple[list[str], list[str]]:
    """collectionNo → (内部 ID, 名字)；查不到就跳过。"""
    ids: list[str] = []
    names: list[str] = []
    for cn in collection_ids or []:
        row = con.execute(
            """SELECT a.entity_id, s.name FROM aliases a
                 LEFT JOIN servants s ON s.id = a.entity_id
                WHERE a.entity_type = 'servant' AND a.alias = ?
                ORDER BY CASE a.region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1""",
            (str(cn),),
        ).fetchone()
        if row and row[0]:
            ids.append(str(row[0]))
            names.append(row[1] or str(cn))
    return ids, names


def enrich_gacha(wiki: Path, con: sqlite3.Connection, dry_run: bool) -> dict:
    path = wiki / "raw" / "gacha" / "gacha_raw.json"
    if not path.is_file():
        return {"skipped": f"没有 {path}"}
    raw = json.loads(path.read_text(encoding="utf-8")).get("gachas") or {}

    rows = con.execute("SELECT id, region, name, up_servants FROM gacha").fetchall()
    up_filled = banner_filled = 0
    for gid, region, name, up in rows:
        item = raw.get(gid)
        if not item:
            continue
        ids, names = _servant_names(con, item.get("servant_ids"))
        new_up = " / ".join(names) if names else _clean_up(up or "")
        if names:
            up_filled += 1
        banner = item.get("banner") or ""
        if banner:
            banner_filled += 1
        if dry_run:
            continue
        con.execute(
            "UPDATE gacha SET up_servants = ?, up_ids = ?, banner = ? WHERE id = ? AND region = ?",
            (new_up[:400], ",".join(ids), banner, gid, region),
        )
    return {"matched": len(rows), "up_filled": up_filled, "banner_filled": banner_filled}


def enrich_events(wiki: Path, con: sqlite3.Connection, dry_run: bool) -> dict:
    by_id: dict[str, dict] = {}
    for region in ("CN", "JP"):
        for f in sorted((wiki / "raw" / "events" / region).glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            by_id[f"{region}/{data.get('id')}"] = data

    rows = con.execute("SELECT id, region, name FROM events").fetchall()
    renamed = banner_filled = 0
    for eid, region, name in rows:
        item = by_id.get(f"{region}/{eid}")
        if not item:
            continue
        new_name = name
        raw_name = _clean(item.get("name") or "")
        if raw_name and (not name or name == eid or name.isdigit()):
            new_name = raw_name
            renamed += 1
        banner = item.get("banner") or item.get("noticeBanner") or ""
        if banner:
            banner_filled += 1
        if dry_run:
            continue
        con.execute(
            "UPDATE events SET name = ?, banner = ? WHERE id = ? AND region = ?",
            (new_name, banner, eid, region),
        )
    return {"renamed": renamed, "banner_filled": banner_filled}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="/home/mila/fgo-wiki")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    wiki = Path(a.wiki)
    if not wiki.is_dir():
        raise SystemExit(f"wiki 路径不存在：{wiki}")
    con = sqlite3.connect(a.db)
    try:
        _ensure_columns(con)
        g = enrich_gacha(wiki, con, a.dry_run)
        e = enrich_events(wiki, con, a.dry_run)
        if not a.dry_run:
            con.commit()
    finally:
        con.close()
    print("卡池：", json.dumps(g, ensure_ascii=False))
    print("活动：", json.dumps(e, ensure_ascii=False))
    if a.dry_run:
        print("（dry-run，未写库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
