# -*- coding: utf-8 -*-
"""B 站 FGO 官网公告：抓取 / 分类 / 入库 / 日历 / 维护推送。

数据源（只有一个，稳定且轻量）：
    https://api.biligame.com/news/list.action?gameExtensionId=45&positionId=2&pageNum=N&pageSize=50
返回 ``data`` 列表，字段 id / title / content / ctime / mtime。

存放：``<data>/FGOUID/news.db``（news 表）。只保留「还有效」的数据：
- 活动：end_at 早于今天 → 删
- 维护 / 其它：ctime 早于 30 天 → 删
这样日历永远是「当前 + 未来」，库也不会长胖。
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from .store import file

API = ("https://api.biligame.com/news/list.action?gameExtensionId=45"
       "&positionId=2&pageNum={page}&pageSize=50&typeId=")
UA = {"User-Agent": "Mozilla/5.0 (compatible; FGOUID/0.1)"}
DB = "news.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS news(
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT '',   -- 维护 / 活动 / 召唤 / 公告
    ctime     TEXT NOT NULL DEFAULT '',
    start_at  TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD
    end_at    TEXT NOT NULL DEFAULT '',
    summary   TEXT NOT NULL DEFAULT '',
    pushed    INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_news_start ON news(start_at);
CREATE INDEX IF NOT EXISTS idx_news_kind ON news(kind);
"""

KIND_RULES = (
    ("维护", ("维护", "停机")),
    ("召唤", ("推荐召唤", "召唤")),
    ("活动", ("【限时】", "活动", "纪念")),
)


def _conn() -> sqlite3.Connection:
    p = file(DB)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def classify(title: str) -> str:
    for kind, keys in KIND_RULES:
        if any(k in title for k in keys):
            return kind
    return "公告"


_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:（[^）]*）)?")
_MD = re.compile(r"(\d{1,2})月(\d{1,2})日(?:（[^）]*）)?")
_SPAN = re.compile(r"(?:时间|举办期间|活动期间)[：:]\s*([^\n。；;]{0,120})")


def _mk_date(y: int, m: int, d: int) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


def parse_span(text: str, ctime: str) -> tuple[str, str]:
    """从正文里抠出活动起止日期（只到天，够日历用）。"""
    flat = _strip_html(text)
    m = _SPAN.search(flat)
    seg = m.group(1) if m else flat[:200]
    years = {x.group(1) for x in _DATE.finditer(flat)}
    base_year = int(min(years)) if years else int((ctime or "2026")[:4])
    full = [x for x in _DATE.finditer(seg)]
    if len(full) >= 2:
        a, b = full[0], full[1]
        return _mk_date(a.group(1), a.group(2), a.group(3)), _mk_date(b.group(1), b.group(2), b.group(3))
    if len(full) == 1:
        a = full[0]
        start = _mk_date(a.group(1), a.group(2), a.group(3))
        md = [x for x in _MD.finditer(seg[a.end():])]
        if md:
            return start, _mk_date(a.group(1), md[0].group(1), md[0].group(2))
        return start, ""
    md = list(_MD.finditer(seg))
    if len(md) >= 2:
        return (_mk_date(base_year, md[0].group(1), md[0].group(2)),
                _mk_date(base_year, md[1].group(1), md[1].group(2)))
    # 兜底：正文里第一个完整日期当开始（「预定于X月X日开幕」这类）
    any_full = list(_DATE.finditer(flat))
    if any_full:
        a = any_full[0]
        return _mk_date(a.group(1), a.group(2), a.group(3)), ""
    return "", ""


def fetch(pages: int = 3, timeout: int = 20) -> list[dict]:
    """抓最近几页公告（每页 50 条）。"""
    out: list[dict] = []
    for page in range(1, pages + 1):
        req = urllib.request.Request(API.format(page=page), headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
        except Exception:
            break
        items = data.get("data") or []
        if not items:
            break
        out.extend(items)
    return out


def _row(item: dict) -> dict:
    title = (item.get("title") or "").strip()
    ctime = (item.get("ctime") or "").strip()
    body = item.get("content") or ""
    start, end = parse_span(body, ctime)
    return {
        "id": str(item.get("id")),
        "title": title,
        "kind": classify(title),
        "ctime": ctime,
        "start_at": start,
        "end_at": end,
        "summary": _strip_html(body)[:400],
    }


def sync(pages: int = 3) -> dict:
    """抓取并写库，返回新增条数与新增的维护公告列表。"""
    items = fetch(pages)
    if not items:
        return {"fetched": 0, "new": [], "new_count": 0}
    now = datetime.now().isoformat(timespec="seconds")
    new_rows = []
    con = _conn()
    try:
        for item in items:
            row = _row(item)
            if not row["id"] or not row["title"]:
                continue
            exists = con.execute("SELECT 1 FROM news WHERE id = ?", (row["id"],)).fetchone()
            con.execute(
                "INSERT OR REPLACE INTO news (id, title, kind, ctime, start_at, end_at,"
                " summary, pushed, fetched_at) VALUES (?,?,?,?,?,?,?,"
                " COALESCE((SELECT pushed FROM news WHERE id=?),0), ?)",
                (row["id"], row["title"], row["kind"], row["ctime"], row["start_at"],
                 row["end_at"], row["summary"], row["id"], now),
            )
            if not exists:
                new_rows.append(row)
        con.commit()
        cleanup(con)
    finally:
        con.close()
    maint = [r for r in new_rows if r["kind"] == "维护"]
    return {"fetched": len(items), "new": maint, "new_count": len(new_rows)}


def cleanup(con: sqlite3.Connection | None = None) -> int:
    """删掉过期数据：活动看 end_at，其它看 ctime（30 天）。"""
    own = con is None
    con = con or _conn()
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    try:
        n1 = con.execute(
            "DELETE FROM news WHERE kind = '活动' AND end_at != '' AND end_at < ?", (today,)
        ).rowcount
        n2 = con.execute(
            "DELETE FROM news WHERE kind != '活动' AND ctime != '' AND substr(ctime,1,10) < ?",
            (cutoff,),
        ).rowcount
        n3 = con.execute(
            "DELETE FROM news WHERE kind = '活动' AND end_at = '' AND substr(ctime,1,10) < ?",
            (cutoff,),
        ).rowcount
        con.commit()
        return (n1 or 0) + (n2 or 0) + (n3 or 0)
    finally:
        if own:
            con.close()


def pending_maintenance() -> list[dict]:
    """还没推送过的维护公告。"""
    con = _conn()
    try:
        rows = con.execute(
            "SELECT * FROM news WHERE kind = '维护' AND pushed = 0 ORDER BY ctime DESC LIMIT 5"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def mark_pushed(ids: list[str]) -> None:
    if not ids:
        return
    con = _conn()
    try:
        con.executemany("UPDATE news SET pushed = 1 WHERE id = ?", [(i,) for i in ids])
        con.commit()
    finally:
        con.close()


def calendar(limit: int = 15) -> list[dict]:
    """当前 + 未来的活动，按开始时间正序。"""
    today = date.today().isoformat()
    con = _conn()
    try:
        rows = con.execute(
            "SELECT * FROM news WHERE kind = '活动' AND start_at != ''"
            " AND (end_at = '' OR end_at >= ?) ORDER BY start_at, ctime LIMIT ?",
            (today, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dateless_count() -> int:
    """有活动公告但正文没标注时间的条数（日历里单独提示）。"""
    con = _conn()
    try:
        r = con.execute(
            "SELECT COUNT(*) FROM news WHERE kind = '活动' AND start_at = ''"
        ).fetchone()
        return int(r[0] or 0)
    finally:
        con.close()


def stats() -> dict:
    con = _conn()
    try:
        rows = con.execute("SELECT kind, COUNT(*) c FROM news GROUP BY kind").fetchall()
        return {r["kind"]: r["c"] for r in rows}
    finally:
        con.close()
