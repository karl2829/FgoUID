#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""御主衣服（魔术礼装）入库：wiki 的 MD（中文技能表）+ raw（图标/立绘/解说）。

数据是「第三维度」——从者、概念礼装之外的御主装备。
表结构与其它实体一样是只读快照，由本脚本生成，`sync_from_wiki.py` 重建时会先 DROP。

用法：
    python tools/sync_mystic.py --wiki /home/mila/fgo-wiki
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "fgo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mystic_codes(
    id TEXT PRIMARY KEY,
    name TEXT,
    name_jp TEXT,
    lv_max INTEGER,
    detail TEXT,
    icon_url TEXT,
    figure_url TEXT,
    skills TEXT,
    file TEXT
);
"""


def _table_rows(lines: list[str]) -> list[list[str]]:
    """把 markdown 表格行拆成单元格。"""
    rows = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def _section(text: str, title: str) -> list[str]:
    m = re.search(rf"^##+\s*{re.escape(title)}\s*$", text, re.M)
    if not m:
        return []
    rest = text[m.end():]
    end = re.search(r"^##+\s", rest, re.M)
    return (rest[: end.start()] if end else rest).splitlines()


def parse_md(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    name = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            name = line[2:].strip()
            break
    mid = ""
    m = re.search(r"\*\*ID\*\*[：:]\s*(\d+)", text)
    if m:
        mid = m.group(1)
    info = {}
    for row in _table_rows(_section(text, "基本信息")):
        if len(row) >= 2:
            info[row[0]] = row[1]
    mid = mid or info.get("ID", "")
    if not mid:
        return None
    skills = []
    for row in _table_rows(_section(text, "技能列表")):
        if len(row) < 3 or row[0] in ("技能名",):
            continue
        skills.append({"name": row[0], "effect": row[1], "cd": row[2]})
    return {
        "id": str(mid),
        "name": info.get("名称") or name,
        "name_jp": info.get("日文名", ""),
        "skills": skills,
        "file": str(path),
    }


RAW_TYPES = {"gainHp", "gainStar", "gainNp", "gainCp", "addNp", "subHp", "addMaxHp"}


def _fmt_value(func_type: str, raw: list) -> list[str]:
    """svals → 展示用的 10 个值。百分比类 Value/10，HP/暴击星等保持原值。"""
    vals = [v for v in raw if v is not None]
    if not vals:
        return []
    if func_type in RAW_TYPES:
        return [f"{int(v)}" for v in vals]
    if func_type == "addState" and max(vals) >= 1000:     # 毅力这类是 HP 数值，不是百分比
        return [f"{int(v)}" for v in vals]
    return [f"{v / 10:g}%" for v in vals]


def parse_effects(raw_skill: dict) -> list[dict]:
    """unmodifiedDetail 按 ＆ 拆词条，每个词条配自己的 svals（没有数值的只留文字）。"""
    detail = raw_skill.get("unmodifiedDetail") or raw_skill.get("detail") or ""
    parts = [p.strip() for p in re.split(r"[＆&]", detail) if p.strip()]
    fns = [f for f in (raw_skill.get("functions") or [])
           if any(x.get("Value") is not None for x in (f.get("svals") or []))]
    need = sum(p.count("[{0}]") for p in parts)
    nonzero = [f for f in fns if any((x.get("Value") or 0) != 0 for x in (f.get("svals") or []))]
    if len(nonzero) >= need:          # 优先用真正带数值的 function（避开 0 值占位）
        fns = nonzero
    fi = 0
    out = []
    for part in parts:
        text = re.sub(r"\[\{0\}\]", "", part).strip()
        vals: list[str] = []
        if "[{0}]" in part and fi < len(fns):
            vals = _fmt_value(fns[fi].get("funcType", ""), [x.get("Value") for x in fns[fi]["svals"]])
            fi += 1
        out.append({"text": text, "vals": vals})
    return out


def load_raw(wiki: Path) -> dict[str, dict]:
    p = wiki / "raw" / "mystic-codes" / "all.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for item in data if isinstance(data, list) else []:
        out[str(item.get("id"))] = item
    return out


def sync(wiki: Path, con: sqlite3.Connection) -> dict:
    con.executescript(SCHEMA)
    con.execute("DELETE FROM aliases WHERE entity_type = 'mystic'")   # 重建别名，避免旧数据残留
    raw = load_raw(wiki)
    total = 0
    for md in sorted((wiki / "entities" / "mystic-codes").glob("*.md")):
        if md.stem == "index":
            continue
        info = parse_md(md)
        if not info:
            continue
        r = raw.get(info["id"], {})
        raw_skills = {sk.get("name"): sk for sk in (r.get("skills") or [])}
        for sk in info["skills"]:
            src = raw_skills.get(sk["name"])
            sk["effects"] = parse_effects(src) if src else []
            if src and src.get("coolDown"):
                sk["cd"] = "→".join(str(x) for x in src["coolDown"])
        assets = r.get("extraAssets") or {}
        icon = (assets.get("item") or {}).get("female") or (assets.get("item") or {}).get("male") or ""
        figure = (assets.get("masterFigure") or {}).get("female") or (assets.get("masterFigure") or {}).get("male") or ""
        con.execute(
            "INSERT OR REPLACE INTO mystic_codes VALUES (?,?,?,?,?,?,?,?,?)",
            (
                info["id"], info["name"], r.get("originalName") or info["name_jp"] or "",
                int(r.get("maxLv") or 0), (r.get("detail") or "").strip(),
                icon, figure,
                json.dumps(info["skills"], ensure_ascii=False), info["file"],
            ),
        )
        # 别名表：中文名 / 日文名 / 短名（如「探险者」）
        def _clean(x: str) -> str:
            return re.sub(r"\s+", "", x or "")

        names = {_clean(x) for x in (info["name"], info["name_jp"], r.get("shortName", ""))} - {""}
        for nm in names:
            con.execute(
                "INSERT INTO aliases (alias, entity_type, entity_id, region) VALUES (?,?,?,?)",
                (nm, "mystic", info["id"], "CN"),
            )
        total += 1
    return {"stored": total, "raw": len(raw)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="/home/mila/fgo-wiki")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    a = ap.parse_args()
    wiki = Path(a.wiki)
    if not wiki.is_dir():
        raise SystemExit(f"wiki 路径不存在：{wiki}")
    con = sqlite3.connect(a.db)
    try:
        stats = sync(wiki, con)
        con.commit()
        size = a.db.stat().st_size
    finally:
        con.close()
    print(f"御主衣服：入库 {stats['stored']} 件（raw {stats['raw']}）；DB {size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
