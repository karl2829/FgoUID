"""FGOUID 本地索引查询（SQLite，只读，运行时零 wiki 依赖）。"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fgo.db"
OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "overrides" / "aliases.json"
_OVERRIDES: dict[str, str] | None = None


def _overrides() -> dict[str, str]:
    global _OVERRIDES
    if _OVERRIDES is None:
        try:
            import json
            _OVERRIDES = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        except Exception:
            _OVERRIDES = {}
    return _OVERRIDES


def _resolve(query: str) -> str:
    q = (query or "").strip()
    return _overrides().get(q, q)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con



# 职阶别名：中文 / 英文 / 日文都认，长的优先匹配（「アルターエゴ」不能被「エゴ」抢）
CLASS_TOKENS: list[tuple[str, str]] = sorted({
    ("saber", "saber"), ("剑", "saber"), ("剑士", "saber"), ("剑阶", "saber"),
    ("セイバー", "saber"), ("剣", "saber"), ("剣士", "saber"),
    ("archer", "archer"), ("弓", "archer"), ("弓兵", "archer"), ("弓阶", "archer"),
    ("アーチャー", "archer"),
    ("lancer", "lancer"), ("枪", "lancer"), ("枪兵", "lancer"), ("枪阶", "lancer"),
    ("ランサー", "lancer"), ("槍", "lancer"),
    ("rider", "rider"), ("骑", "rider"), ("骑兵", "rider"), ("骑阶", "rider"),
    ("ライダー", "rider"), ("騎", "rider"),
    ("caster", "caster"), ("术", "caster"), ("术阶", "caster"), ("魔术师", "caster"),
    ("キャスター", "caster"), ("術", "caster"),
    ("assassin", "assassin"), ("杀", "assassin"), ("杀阶", "assassin"),
    ("アサシン", "assassin"), ("殺", "assassin"),
    ("berserker", "berserker"), ("狂", "berserker"), ("狂阶", "berserker"),
    ("バーサーカー", "berserker"), ("狂战士", "berserker"),
    ("ruler", "ruler"), ("裁", "ruler"), ("尺", "ruler"), ("ルーラー", "ruler"),
    ("avenger", "avenger"), ("仇", "avenger"), ("复仇者", "avenger"),
    ("アヴェンジャー", "avenger"),
    ("alterego", "alterego"), ("丑", "alterego"), ("他我", "alterego"),
    ("アルターエゴ", "alterego"),
    ("mooncancer", "mooncancer"), ("mc", "mooncancer"), ("月", "mooncancer"),
    ("ムーンキャンサー", "mooncancer"),
    ("foreigner", "foreigner"), ("外", "foreigner"), ("降", "foreigner"),
    ("フォーリナー", "foreigner"), ("フォーリナ", "foreigner"),
    ("pretender", "pretender"), ("伪", "pretender"), ("詐", "pretender"),
    ("プリテンダー", "pretender"),
    ("shielder", "shielder"), ("盾", "shielder"), ("シールダー", "shielder"),
    ("beast", "beast"), ("兽", "beast"), ("ビースト", "beast"),
}, key=lambda kv: -len(kv[0]))

STAR_RE = re.compile(r"\s*(?:★\s*(\d)|([1-5一二三四五])\s*星)\s*")


def _parse_servant_query(query: str) -> tuple[str, str | None, int | None]:
    """把「剑 伊吹童子」「伊吹童子 5星」「berserker5★伊吹童子」拆成 (名字, 职阶, 星级)。"""
    q = (query or "").strip()
    cls = None
    star = None
    m = STAR_RE.search(q)
    if m:
        raw = m.group(1) or m.group(2)
        star = int(raw) if str(raw).isdigit() else "一二三四五".index(raw) + 1
        q = (q[: m.start()] + " " + q[m.end():]).strip()
    for token, cid in CLASS_TOKENS:
        if q.lower().startswith(token) and len(q) > len(token):
            rest = q[len(token):].strip(" ·・-／/")
            if rest:
                cls = cid
                q = rest
                break
    return q, cls, star


def parse_servant_query(query: str) -> tuple[str, str | None, int | None]:
    """对外暴露的查询解析（名字 / 职阶 / 星级）。"""
    return _parse_servant_query(_resolve(query))


def _search_rows(con, query: str, limit: int = 12):
    """先精确别名，再前缀/包含匹配；同一名字的多条都返回（不要 LIMIT 1）。"""
    q = (query or "").strip()
    if not q:
        return []
    rows = con.execute(
        """SELECT DISTINCT t.* FROM servants t
            WHERE t.id IN (SELECT entity_id FROM aliases
                            WHERE alias = ? AND entity_type = 'servant')
         ORDER BY CASE t.region WHEN 'CN' THEN 0 ELSE 1 END""",
        (q,),
    ).fetchall()
    if rows:
        return rows
    for pattern in (q, f"{q}%", f"%{q}%"):
        rows = con.execute(
            """SELECT * FROM servants WHERE name LIKE ?
             ORDER BY CASE region WHEN 'CN' THEN 0 ELSE 1 END LIMIT ?""",
            (pattern, limit),
        ).fetchall()
        if rows:
            return rows
    return []


def _dedupe(rows) -> list:
    """同一个 id 的国服/日服两条记录只留国服那条。"""
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    return out


def find_servants(query: str) -> list:
    """从者查询：支持「职阶 + 名称」「名称 + 星级」，返回全部候选（重名不吃掉）。"""
    q = _resolve(query)
    con = _conn()
    try:
        rows = _dedupe(_search_rows(con, q))
        if rows:
            return rows
        name, cls, star = _parse_servant_query(q)
        if not name or (cls is None and star is None):
            return []
        rows = _dedupe(_search_rows(con, name))
        if cls:
            rows = [r for r in rows if (r["servant_class"] or "").lower() == cls]
        if star:
            rows = [r for r in rows if int(r["rarity"] or 0) == star]
        return rows
    finally:
        con.close()

def _lookup(con, table: str, entity_type: str, query: str, name_col: str = "name"):
    q = (query or "").strip()
    if not q:
        return None
    row = con.execute(
        f"""SELECT t.* FROM {table} t
            WHERE t.id IN (SELECT entity_id FROM aliases WHERE alias = ? AND entity_type = ?)
            ORDER BY CASE t.region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1""",
        (q, entity_type),
    ).fetchone()
    if row:
        return row
    for pattern in (q, f"{q}%", f"%{q}%"):
        row = con.execute(
            f"""SELECT * FROM {table} WHERE {name_col} LIKE ?
                ORDER BY CASE region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1""",
            (pattern,),
        ).fetchone()
        if row:
            return row
    return None


def find_servant(query: str):
    rows = find_servants(query)
    return rows[0] if rows else None


def find_servant_id(query: str) -> str | None:
    row = find_servant(query)
    return row["id"] if row else None


def load_card_model(servant_id: str) -> dict | None:
    """从 servant_cards 表取卡片模型（zlib 压缩的 JSON）。没有就返回 None。"""
    import json
    import zlib

    con = _conn()
    try:
        row = con.execute(
            "SELECT data FROM servant_cards WHERE id = ? ORDER BY CASE region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1",
            (servant_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(zlib.decompress(row[0]))
    except Exception:
        return None
    finally:
        con.close()


def find_servant(query: str):
    con = _conn()
    try:
        return _lookup(con, "servants", "servant", query)
    finally:
        con.close()


def find_ce(query: str):
    con = _conn()
    try:
        return _lookup(con, "craft_essences", "ce", _resolve(query))
    finally:
        con.close()


def format_servant(row: sqlite3.Row) -> str:
    lines = [f"【{row['name']}】{'★' * (row['rarity'] or 0)} {row['servant_class']}"]
    if row["name_jp"] and row["name_jp"] != row["name"]:
        lines.append(f"日文名：{row['name_jp']}")
    meta = [f"{label} {row[key]}" for label, key in (("属性", "alignment"), ("阵营", "camp"), ("性别", "gender")) if row[key]]
    if meta:
        lines.append("｜".join(meta))
    if row["atk_base"] and row["atk_max"]:
        lines.append(f"攻击 {row['atk_base']} → {row['atk_max']}（Lv.{row['max_level'] or 90}）")
    if row["hp_base"] and row["hp_max"]:
        lines.append(f"HP {row['hp_base']} → {row['hp_max']}（Lv.{row['max_level'] or 90}）")
    if row["traits"]:
        lines.append(f"特性：{row['traits'][:120]}")
    if row["gacha"]:
        lines.append(f"卡池：{row['gacha']}")
    lines.append(f"（{row['region']} 数据｜ID {row['id']}）")
    return "\n".join(lines)


def format_ce(row: sqlite3.Row) -> str:
    lines = [f"【{row['name']}】{'★' * (row['rarity'] or 0)} COST {row['cost']}｜{row['ce_type']}"]
    if row["effect"]:
        lines.append(f"效果：{row['effect'][:200]}")
    lines.append(f"（{row['region']} 数据｜ID {row['id']}）")
    return "\n".join(lines)


def search_events(query: str = "", limit: int = 5):
    con = _conn()
    today = date.today().isoformat()
    try:
        if query.strip():
            return con.execute(
                "SELECT * FROM events WHERE name LIKE ? ORDER BY start_time DESC LIMIT ?",
                (f"%{query.strip()}%", limit),
            ).fetchall()
        end_window = (date.today() + timedelta(days=730)).isoformat()
        rows = con.execute(
            "SELECT * FROM events WHERE start_time >= ? AND start_time <= ? ORDER BY start_time ASC LIMIT ?",
            (today, end_window, limit),
        ).fetchall()
        if rows:
            return rows
        return con.execute(
            "SELECT * FROM events WHERE start_time < ? ORDER BY start_time DESC LIMIT ?",
            (today, limit),
        ).fetchall()
    finally:
        con.close()


def format_events(rows) -> str:
    if not rows:
        return "没有找到活动"
    out = []
    for r in rows:
        span = f"{r['start_time']} ~ {r['end_time']}" if r["start_time"] else ""
        status = f"｜{r['status']}" if r["status"] else ""
        out.append(f"· {r['name']}（{r['region']}）\n  {span}{status}")
    return "\n".join(out)


def list_gacha(query: str = "", limit: int = 5):
    con = _conn()
    today = date.today().isoformat()
    try:
        if query.strip():
            return con.execute(
                "SELECT * FROM gacha WHERE name LIKE ? ORDER BY start_time ASC LIMIT ?",
                (f"%{query.strip()}%", limit),
            ).fetchall()
        return con.execute(
            "SELECT * FROM gacha WHERE start_time >= ? ORDER BY start_time ASC LIMIT ?",
            (today, limit),
        ).fetchall()
    finally:
        con.close()


def format_gacha(rows) -> str:
    if not rows:
        return "没有找到卡池"
    out = []
    for r in rows:
        span = f"{r['start_time']} ~ {r['end_time']}" if r["start_time"] else "时间未知"
        out.append(f"· {r['name']}（{r['region']}）\n  {span}｜{r['status']}")
        if r["up_servants"]:
            out.append(f"  UP：{r['up_servants'][:120]}")
    return "\n".join(out)
