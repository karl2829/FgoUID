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
import time
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
    fetched_at TEXT NOT NULL DEFAULT '',
    detail_at TEXT NOT NULL DEFAULT '',    -- 详情页抓取时间（空 = 没抓过）
    maint_start TEXT NOT NULL DEFAULT '',  -- 维护开始 YYYY-MM-DD HH:MM
    maint_end   TEXT NOT NULL DEFAULT '',  -- 维护结束
    comp       TEXT NOT NULL DEFAULT '',   -- 补偿内容
    comp_time  TEXT NOT NULL DEFAULT '',   -- 发放时间
    contents   TEXT NOT NULL DEFAULT '',   -- 维护内容（JSON 数组）
    comp_to    TEXT NOT NULL DEFAULT ''    -- 补偿对象
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
    cols = {r[1] for r in con.execute("PRAGMA table_info(news)")}
    for col in ("detail_at", "maint_start", "maint_end", "comp", "comp_time",
                "contents", "comp_to"):
        if col not in cols:
            con.execute(f"ALTER TABLE news ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    con.commit()
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


DETAIL_API = "https://api.biligame.com/news/{id}"
_SECTION = re.compile(r"【([^】]{1,12})】")
_TIME_PAIR = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})"
    r"\s*[～~\-—至]\s*(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})")


def fetch_detail(nid: str, timeout: int = 20) -> str:
    """公告详情（完整正文 HTML）。列表接口的 content 是截断的摘要。"""
    req = urllib.request.Request(DETAIL_API.format(id=nid), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        data = d.get("data") or {}
        return data.get("content") or ""
    except Exception:
        return ""


def split_sections(html: str) -> tuple[str, dict]:
    """按 【小标题】 切段：返回 (正文前缀, {标题: 内容})。"""
    text = re.sub(r"<br\s*/?>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ")
    text = re.sub(r"[ \t]+", " ", text)
    marks = list(_SECTION.finditer(text))
    if not marks:
        return text.strip(), {}
    head = text[:marks[0].start()].strip()
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end]
        body = re.sub(r"\n{2,}", "\n", body).strip()
        out[m.group(1).strip()] = body
    return head, out


def _first_line(value: str, cut_words: tuple[str, ...] = ()) -> str:
    """取第一行；遇到注意事项之类的尾巴就截断。"""
    text = (value or "").replace("\r", "\n")
    for w in cut_words:
        idx = text.find(w)
        if idx > 0:
            text = text[:idx]
    for line in text.split("\n"):
        line = line.strip(" ·-　")
        if line:
            return line[:80]
    return ""


def _parse_items(value: str) -> list[str]:
    """把「1. 开启xxx 2. 关闭xxx」拆成列表。"""
    text = (value or "").replace("\r", "\n")
    parts = re.split(r"\n\s*(?=\d+\s*[.、．])", text)
    items = []
    for part in parts:
        part = re.sub(r"^\s*\d+\s*[.、．]\s*", "", part).strip(" 　\n")
        part = re.sub(r"\s*\n\s*", " ", part)
        if part:
            items.append(part[:120])
    return items


def _parse_maint_time(value: str) -> tuple[str, str]:
    plain = value.replace("（预计）", "").replace("(预计)", "")
    m = _TIME_PAIR.search(plain)
    if not m:
        return "", ""
    y, mo, d, h, mi, y2, mo2, d2, h2, mi2 = m.groups()
    start = f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}"
    end = f"{int(y2 or y):04d}-{int(mo2):02d}-{int(d2):02d} {int(h2):02d}:{mi2}"
    return start, end


def _row(item: dict) -> dict:
    title = (item.get("title") or "").strip()
    ctime = (item.get("ctime") or "").strip()
    body = item.get("content") or ""
    start, end = parse_span(body, ctime)
    if not start:                       # 维护公告的日期写在标题里：活动维护公告（2026年11月24日 14时）
        m = _DATE.search(title)
        if m:
            start = _mk_date(m.group(1), m.group(2), m.group(3))
    return {
        "id": str(item.get("id")),
        "title": title,
        "kind": classify(title),
        "ctime": ctime,
        "start_at": start,
        "end_at": end,
        "summary": _strip_html(body)[:400],
    }


def _needs_detail(row: dict) -> bool:
    return (not row.get("start_at")) or row["kind"] in ("维护", "召唤")


def refresh_details(budget: int = 25, window_days: int = 45) -> int:
    """给「没日期 / 维护 / 召唤」的公告补抓详情页（列表接口正文是截断的）。"""
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    con = _conn()
    done = 0
    try:
        rows = con.execute(
            "SELECT * FROM news WHERE (detail_at = '' OR (kind = '维护' AND contents = ''))"
            " AND substr(ctime,1,10) >= ? ORDER BY ctime DESC LIMIT ?",
            (cutoff, max(1, budget)),
        ).fetchall()
        for r in rows:
            html = fetch_detail(r["id"])
            if not html:
                continue
            head, sec = split_sections(html)
            start, end = r["start_at"], r["end_at"]
            mstart = mend = comp = ctime_s = comp_to = ""
            items_json = ""
            if r["kind"] == "维护":
                mt = sec.get("维护时间") or sec.get("维护期间") or ""
                mstart, mend = _parse_maint_time(mt)
                comp = _first_line(sec.get("维护补偿内容") or sec.get("补偿内容") or "")
                ctime_s = _first_line(sec.get("发放时间") or "", cut_words=("注意事项",))
                comp_to = _first_line(sec.get("维护补偿对象") or sec.get("补偿对象") or "")
                items = _parse_items(sec.get("维护内容") or sec.get("更新内容") or "")
                if items:
                    items_json = json.dumps(items, ensure_ascii=False)
                if mstart:
                    start = mstart[:10]
                if not end and mend:
                    end = mend[:10]
            elif not start:
                start, end = parse_span(head + "\n" + html, r["ctime"])
            con.execute(
                "UPDATE news SET detail_at=?, start_at=?, end_at=?, maint_start=?,"
                " maint_end=?, comp=?, comp_time=?, contents=?, comp_to=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), start or "", end or "",
                 mstart, mend, comp.replace("\n", " ")[:120], ctime_s, items_json, comp_to,
                 r["id"]),
            )
            done += 1
            time.sleep(1.2)                      # 别把人家接口打疼
        con.commit()
    finally:
        con.close()
    return done


def sync(pages: int = 3, details: int = 25) -> dict:
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
            # 注意：不能用 INSERT OR REPLACE —— 那会把 detail_*/comp/contents 一起重置
            con.execute(
                "INSERT INTO news (id, title, kind, ctime, start_at, end_at, summary,"
                " pushed, fetched_at) VALUES (?,?,?,?,?,?,?,0,?)"
                " ON CONFLICT(id) DO UPDATE SET title=excluded.title, kind=excluded.kind,"
                " ctime=excluded.ctime, summary=excluded.summary, fetched_at=excluded.fetched_at,"
                " start_at=CASE WHEN excluded.start_at != '' THEN excluded.start_at"
                "               ELSE news.start_at END,"
                " end_at=CASE WHEN excluded.end_at != '' THEN excluded.end_at ELSE news.end_at END",
                (row["id"], row["title"], row["kind"], row["ctime"], row["start_at"],
                 row["end_at"], row["summary"], now),
            )
            if not exists:
                new_rows.append(row)
        con.commit()
        cleanup(con)
    finally:
        con.close()
    if details:
        refresh_details(budget=details)
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


def pending_maintenance(within_days: int = 3) -> list[dict]:
    """还没推送过的维护公告（只取最近几天，避免刚订阅时把历史全推一遍）。"""
    cutoff = (date.today() - timedelta(days=within_days)).isoformat()
    con = _conn()
    try:
        rows = con.execute(
            "SELECT * FROM news WHERE kind = '维护' AND pushed = 0"
            " AND substr(ctime,1,10) >= ? ORDER BY ctime DESC LIMIT 5",
            (cutoff,),
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


def timeline(limit: int = 60) -> list[dict]:
    """日历卡用：当前 + 未来的活动/召唤/维护（都要求有开始日期）。"""
    today = date.today().isoformat()
    con = _conn()
    try:
        rows = con.execute(
            "SELECT * FROM news WHERE kind IN ('活动','召唤','维护') AND start_at != ''"
            " AND (end_at = '' OR end_at >= ?) ORDER BY start_at, ctime LIMIT ?",
            (today, limit * 2),
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        d = dict(r)
        if d["kind"] == "维护":
            when = (d.get("maint_start") or d.get("start_at") or "")[:10]
            if when < today:            # 已经过去的维护没意义
                continue
        out.append(d)
    return out[:limit]


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
