# -*- coding: utf-8 -*-
"""素材预热：提前把立绘/羁绊礼装/技能图标拉到 ``data/FGOUID/art``。

为什么要预热：服务器到 static.atlasacademy.io 只有 ~130KB/s，一张从者卡要下
3~5 个文件（约 1.1MB），冷查询要等 10s 以上；预热把这段等待挪到后台。

分批而不是一次全下：素材缓存默认 300MB（``FGOUID_ART_CACHE_MB`` 可调），
448 个从者全量约 500MB，一次全下会把刚下好的图又 LRU 淘汰掉。所以
``fgo下载资源`` 一次只推一批（默认 60 张），优先级 5★ → 4★ → 其余。
进度记在 ``data/FGOUID/prewarm.json``，重启不丢。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime

from .db import DB_PATH, load_card_model
from .store import file

STATE = "prewarm.json"
DEFAULT_BATCH = 60
MAX_BATCH = 200


def _load() -> dict:
    p = file(STATE)
    if not p.is_file():
        return {"done": {}, "updated": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"done": {}, "updated": None}


def _save(state: dict) -> None:
    state["updated"] = datetime.now().isoformat(timespec="seconds")
    p = file(STATE)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def plan() -> list[str]:
    """预热顺序：星级高的先来，同星级按图鉴编号。"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """SELECT s.id FROM servants s
                 JOIN servant_cards c ON c.id = s.id AND c.region = s.region
                WHERE s.region = 'CN'
             ORDER BY s.rarity DESC, CAST(s.id AS INTEGER)"""
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def status() -> dict:
    state = _load()
    ids = plan()
    done = sum(1 for i in ids if i in state["done"])
    return {"total": len(ids), "done": done, "pending": len(ids) - done,
            "updated": state.get("updated")}


def next_batch(limit: int = DEFAULT_BATCH) -> list[str]:
    state = _load()
    out: list[str] = []
    for sid in plan():
        if sid in state["done"]:
            continue
        out.append(sid)
        if len(out) >= limit:
            break
    return out


def _warm_one(servant_id: str) -> bool:
    """同步预热一张卡的全部素材（在线程里跑）。"""
    from ..card import build, fetch

    model = load_card_model(servant_id)
    if not model:
        return False
    names = build.assets_used(build.build_html(model))
    missing = [
        n for n in names
        if not (fetch.BUNDLED / n).is_file() and not (fetch.cache_dir() / n).is_file()
    ]
    if missing:
        fetch.warm(missing, model)
    return all(
        (fetch.BUNDLED / n).is_file() or (fetch.cache_dir() / n).is_file() for n in names
    )


async def run(limit: int = DEFAULT_BATCH) -> dict:
    """预热一批，返回 {asked, ok, failed, status}。"""
    batch = next_batch(max(1, min(limit, MAX_BATCH)))
    if not batch:
        return {"asked": 0, "ok": 0, "failed": 0, "status": status()}
    state = _load()
    ok = failed = 0
    for sid in batch:
        try:
            good = await asyncio.to_thread(_warm_one, sid)
        except Exception:
            good = False
        if good:
            state["done"][sid] = datetime.now().isoformat(timespec="seconds")
            ok += 1
        else:
            failed += 1
        await asyncio.sleep(0)          # 让出事件循环，别卡住消息收发
    _save(state)
    return {"asked": len(batch), "ok": ok, "failed": failed, "status": status()}


def format_status(st: dict) -> str:
    total, done = st["total"], st["done"]
    pct = (done / total * 100) if total else 0
    return f"素材预热：{done}/{total}（{pct:.0f}%）"
