"""FGOUID 本地索引查询（SQLite，只读）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fgo.db"


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def find_servant(query: str) -> sqlite3.Row | None:
    q = (query or "").strip()
    if not q:
        return None
    con = _conn()
    try:
        sql = """
        SELECT s.* FROM servants s
        WHERE s.id IN (
            SELECT entity_id FROM aliases WHERE alias = ? AND entity_type = 'servant'
        )
        ORDER BY CASE s.region WHEN 'CN' THEN 0 ELSE 1 END
        LIMIT 1
        """
        row = con.execute(sql, (q,)).fetchone()
        if row:
            return row
        for pattern in (q, f"{q}%", f"%{q}%"):
            row = con.execute(
                """SELECT * FROM servants WHERE name LIKE ?
                   ORDER BY CASE region WHEN 'CN' THEN 0 ELSE 1 END LIMIT 1""",
                (pattern,),
            ).fetchone()
            if row:
                return row
        return None
    finally:
        con.close()


def format_servant(row: sqlite3.Row) -> str:
    lines = [f"【{row['name']}】{'★' * (row['rarity'] or 0)} {row['servant_class']}"]
    if row["name_jp"] and row["name_jp"] != row["name"]:
        lines.append(f"日文名：{row['name_jp']}")
    meta = []
    for label, key in (("属性", "alignment"), ("阵营", "camp"), ("性别", "gender")):
        if row[key]:
            meta.append(f"{label} {row[key]}")
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
