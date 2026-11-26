# -*- coding: utf-8 -*-
"""趣味互动：今日老婆等不需要账号数据的小玩法。

选人规则刻意做成**确定性**的：同一用户同一天永远同一个人（方便复读、截图、对账），
换天自动换人。种子 = sha1(user_id + 日期 + 固定盐)，对候选池取模。
"""
from __future__ import annotations

import hashlib
from datetime import date

from .db import _conn  # 复用只读连接

SALT = "fgouid-waifu-v1"


def _pool() -> list[dict]:
    """候选池：有卡片数据的国服从者（能出图的那批）。"""
    con = _conn()
    try:
        rows = con.execute(
            """SELECT s.id, s.name, s.servant_class, s.rarity
                 FROM servants s JOIN servant_cards c ON c.id = s.id AND c.region = s.region
                WHERE s.region = 'CN'
             ORDER BY CAST(s.id AS INTEGER)"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def today_waifu(user_id: str, day: str | None = None) -> dict | None:
    day = day or date.today().isoformat()
    pool = _pool()
    if not pool:
        return None
    seed = f"{user_id}:{day}:{SALT}".encode("utf-8")
    idx = int(hashlib.sha1(seed).hexdigest(), 16) % len(pool)
    pick = pool[idx]
    pick["date"] = day
    pick["pool"] = len(pool)
    return pick


def format_waifu(pick: dict) -> str:
    stars = "★" * int(pick.get("rarity") or 0)
    return (
        f"【今日老婆】{pick['date']}\n"
        f"{pick['name']} {stars} {pick['servant_class']}\n"
        f"（从 {pick['pool']} 位从者里抽的，明天换人）"
    )
