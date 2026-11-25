"""FGOUID 本地索引查询（SQLite，只读，运行时零 wiki 依赖）。"""
from __future__ import annotations

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
