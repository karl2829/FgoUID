#!/usr/bin/env python3
"""把 Atlas 的 CN 道具/卡池 ID→名称 表写进 fgo.db（给抽卡记录卡用）。

用法：python tools/sync_master_names.py [--wiki /home/mila/fgo-wiki]
只读 Atlas 公开导出，不碰游戏接口。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "fgo.db"
ATLAS = "https://api.atlasacademy.io/export/CN/{name}.json"
SCHEMA = """
CREATE TABLE IF NOT EXISTS item_names(id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT);
CREATE TABLE IF NOT EXISTS gacha_names(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  gacha_type TEXT, started_at INTEGER, ended_at INTEGER);
"""


def fetch(name: str) -> list:
    req = urllib.request.Request(ATLAS.format(name=name), headers={"User-Agent": "FGOUID/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> int:
    print("拉 Atlas 道具表…")
    items = fetch("nice_item")
    print("拉 Atlas 卡池表…")
    gachas = fetch("nice_gacha")
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT OR REPLACE INTO item_names(id, name, type) VALUES (?,?,?)",
        [(int(i["id"]), (i.get("name") or "").strip(), i.get("type") or "") for i in items],
    )
    con.executemany(
        "INSERT OR REPLACE INTO gacha_names(id, name, gacha_type, started_at, ended_at) VALUES (?,?,?,?,?)",
        [(int(g["id"]), (g.get("name") or "").strip(), g.get("type") or "",
          int(g.get("startedAt") or 0), int(g.get("endedAt") or 0)) for g in gachas],
    )
    con.commit()
    n_i = con.execute("SELECT COUNT(*) FROM item_names").fetchone()[0]
    n_g = con.execute("SELECT COUNT(*) FROM gacha_names").fetchone()[0]
    con.close()
    print(f"道具 {n_i} 条 / 卡池 {n_g} 条 → {DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
