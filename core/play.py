# -*- coding: utf-8 -*-
"""趣味互动：每日一抽 + 从者图鉴（本地记账，不需要账号数据）。

规则刻意做成**确定性**的：同一用户同一天永远是同一张卡，
重发命令不会「刷新运气」，换天自动换一抽。

概率按稀有度先抽档、再在档内均匀取人（FGO 圣晶石召唤的粗略近似）：
5★ 1% / 4★ 3% / 3★ 40% / 2★ 25% / 1★ 30% / 0★ 1%。
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import date

from .db import DB_PATH
from .store import file

SALT = "fgouid-draw-v1"
DB_FILE = "play.db"
# (星级, 权重)，权重是百分比的整数倍：1 → 1%
RATES: tuple[tuple[int, int], ...] = ((5, 1), (4, 3), (3, 40), (2, 25), (1, 30), (0, 1))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pulls (
    user_id    TEXT NOT NULL,
    day        TEXT NOT NULL,
    servant_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    rarity     INTEGER NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS owned (
    user_id    TEXT NOT NULL,
    servant_id TEXT NOT NULL,
    first_day  TEXT NOT NULL,
    PRIMARY KEY (user_id, servant_id)
);
"""


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(file(DB_FILE), timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _pool() -> list[dict]:
    """候选池：有卡片数据的国服从者，去掉 NPC/敌方形态（id 99 开头那批）。"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """SELECT s.id, s.name, s.servant_class, s.rarity
                 FROM servants s JOIN servant_cards c ON c.id = s.id AND c.region = s.region
                WHERE s.region = 'CN' AND s.id NOT LIKE '99%'
             ORDER BY CAST(s.id AS INTEGER)"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _hash_int(*parts: str) -> int:
    return int(hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest(), 16)


def _pick(pool: list[dict], user_id: str, day: str) -> dict:
    by_star: dict[int, list[dict]] = {}
    for row in pool:
        by_star.setdefault(int(row["rarity"] or 0), []).append(row)

    roll = _hash_int(user_id, day, SALT, "band") % 100
    upto = 0
    band = 0
    for star, weight in RATES:
        upto += weight
        if roll < upto:
            band = star
            break
    # 该档位没人（数据缺）时退到最近的有人的档
    if not by_star.get(band):
        band = min(by_star, key=lambda s: abs(s - band))
    group = by_star[band]
    return group[_hash_int(user_id, day, SALT, "idx") % len(group)]


def draw(user_id: str, day: str | None = None) -> dict | None:
    """抽今天的卡；同一天重复调用返回同一条记录（已抽过则 is_new=False）。"""
    day = day or date.today().isoformat()
    uid = str(user_id or "0")
    con = _conn()
    try:
        row = con.execute(
            "SELECT * FROM pulls WHERE user_id = ? AND day = ?", (uid, day)
        ).fetchone()
        if row is not None:
            res = dict(row)
            res["is_new"] = False
            res["already"] = True
        else:
            pool = _pool()
            if not pool:
                return None
            pick = _pick(pool, uid, day)
            own = con.execute(
                "SELECT 1 FROM owned WHERE user_id = ? AND servant_id = ?",
                (uid, str(pick["id"])),
            ).fetchone()
            con.execute(
                "INSERT OR REPLACE INTO pulls (user_id, day, servant_id, name, rarity, at)"
                " VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                (uid, day, str(pick["id"]), pick["name"], int(pick["rarity"] or 0)),
            )
            con.execute(
                "INSERT OR IGNORE INTO owned (user_id, servant_id, first_day) VALUES (?, ?, ?)",
                (uid, str(pick["id"]), day),
            )
            con.commit()
            res = {
                "user_id": uid,
                "day": day,
                "servant_id": str(pick["id"]),
                "name": pick["name"],
                "rarity": int(pick["rarity"] or 0),
                "servant_class": pick.get("servant_class"),
                "is_new": own is None,
                "already": False,
            }
        res["pool"] = _pool_size()
        res["owned"] = con.execute(
            "SELECT COUNT(*) FROM owned WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        res["pulls"] = con.execute(
            "SELECT COUNT(*) FROM pulls WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        return res
    finally:
        con.close()


_POOL_SIZE: int | None = None


def _pool_size() -> int:
    global _POOL_SIZE
    if _POOL_SIZE is None:
        _POOL_SIZE = len(_pool())
    return _POOL_SIZE


def stats(user_id: str, recent: int = 5) -> dict:
    uid = str(user_id or "0")
    con = _conn()
    try:
        by_star = {
            int(r["rarity"]): int(r["n"])
            for r in con.execute(
                """SELECT p.rarity AS rarity, COUNT(*) AS n
                     FROM owned o JOIN pulls p ON p.user_id = o.user_id AND p.servant_id = o.servant_id
                    WHERE o.user_id = ?
                 GROUP BY p.rarity""",
                (uid,),
            )
        }
        rows = con.execute(
            "SELECT day, name, rarity FROM pulls WHERE user_id = ? ORDER BY day DESC LIMIT ?",
            (uid, recent),
        ).fetchall()
        return {
            "owned": con.execute(
                "SELECT COUNT(*) FROM owned WHERE user_id = ?", (uid,)
            ).fetchone()[0],
            "pulls": con.execute(
                "SELECT COUNT(*) FROM pulls WHERE user_id = ?", (uid,)
            ).fetchone()[0],
            "by_star": by_star,
            "recent": [dict(r) for r in rows],
            "pool": _pool_size(),
        }
    finally:
        con.close()


def _stars(rarity: int) -> str:
    return "★" * int(rarity or 0)


def format_draw(res: dict) -> str:
    head = f"【每日一抽】{res['day']}"
    body = f"{_stars(res['rarity'])}　{res['name']}"
    if res.get("servant_class"):
        body += f"　·　{res['servant_class']}"
    lines = [head, body]
    tag = "图鉴 NEW" if res["is_new"] else "重复"
    if res.get("already"):
        tag = "今天抽过了"
    lines.append(f"{tag}　·　已收集 {res['owned']}/{res['pool']}")
    lines.append(f"累计 {res['pulls']} 抽　·　明天再来")
    return "\n".join(lines)


def format_stats(st: dict) -> str:
    total = st["pool"]
    pct = (st["owned"] / total * 100) if total else 0
    lines = [f"【从者图鉴】{st['owned']}/{total}（{pct:.1f}%）"]
    star_line = "　".join(
        f"★{s} {st['by_star'].get(s, 0)}" for s in (5, 4, 3, 2, 1, 0)
    )
    lines.append(star_line)
    if st["recent"]:
        lines.append("最近：" + "　/　".join(
            f"{r['day'][5:]} {r['name']}" for r in st["recent"]
        ))
    else:
        lines.append("还没抽过，发「fgo每日一抽」开张")
    lines.append(f"累计 {st['pulls']} 抽")
    return "\n".join(lines)
