#!/usr/bin/env python3
"""把 fgo-wiki 的 Markdown 实体解析成 SQLite 索引（构建期脚本，部署时可不用）。"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

WIKI = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/mila/fgo-wiki")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parent.parent / "data" / "fgo.db"))

IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
BOLD_RE = re.compile(r"\*\*([^*]*)\*\*")
STAR_RE = re.compile(r"[★☆]")


def clean(v: str) -> str:
    v = IMG_RE.sub("", v)
    v = BOLD_RE.sub(r"\1", v)
    return v.strip()


def parse_sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out.setdefault(cur, [])
        elif line.startswith("### "):
            cur = line[4:].strip()
            out.setdefault(cur, [])
        elif cur:
            out[cur].append(line)
    return out


def parse_table(lines: list[str]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for line in lines:
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m:
            continue
        k, v = clean(m.group(1)), clean(m.group(2))
        if not k or not v or v == "值" or set(k) <= set("-: "):
            continue
        kv[k] = v
    return kv


def stars(v: str) -> int:
    return len(STAR_RE.findall(v))


def load_aliases() -> dict[str, list[str]]:
    p = WIKI / "data" / "alias_map.json"
    mapping: dict[str, list[str]] = {}
    if not p.exists():
        return mapping
    data = json.loads(p.read_text(encoding="utf-8"))
    for alias, v in data.items():
        items = v if isinstance(v, list) else [v]
        for it in items:
            if isinstance(it, dict) and it.get("id"):
                mapping.setdefault(str(it["id"]), []).append(alias)
    return mapping


def iter_md(base: Path):
    return sorted(base.rglob("*.md"))


def build() -> None:
    aliases = load_aliases()
    db = sqlite3.connect(OUT)
    db.executescript("""
    DROP TABLE IF EXISTS servants;
    DROP TABLE IF EXISTS craft_essences;
    DROP TABLE IF EXISTS events;
    DROP TABLE IF EXISTS aliases;
    CREATE TABLE servants(
        id TEXT, region TEXT, name TEXT, name_jp TEXT, aliases TEXT,
        servant_class TEXT, rarity INT, cost INT, alignment TEXT, camp TEXT,
        gender TEXT, gacha TEXT, traits TEXT, atk_base INT, atk_max INT,
        hp_base INT, hp_max INT, max_level INT, star_rate TEXT, death_rate TEXT, file TEXT,
        PRIMARY KEY (id, region));
    CREATE TABLE craft_essences(
        id TEXT, region TEXT, name TEXT, rarity INT, cost INT,
        ce_type TEXT, effect TEXT, file TEXT, PRIMARY KEY (id, region));
    CREATE TABLE events(
        id TEXT, region TEXT, name TEXT, event_type TEXT,
        start_time TEXT, end_time TEXT, status TEXT, file TEXT,
        PRIMARY KEY (id, region));
    CREATE TABLE aliases(alias TEXT, entity_type TEXT, entity_id TEXT, region TEXT);
    """)

    n_s = n_c = n_e = 0
    for region in ("CN", "JP"):
        for f in iter_md(WIKI / "entities" / "servants" / region):
            text = f.read_text(encoding="utf-8", errors="ignore")
            sec = parse_sections(text)
            info = parse_table(sec.get("基础信息", []))
            num = parse_table(sec.get("数值", []))
            sid = info.get("内部 ID") or f.stem
            name = info.get("名称") or f.stem
            name_jp = info.get("原始名称（日文）", "")
            own = [a.strip() for a in re.split(r"[、,，/]", info.get("别名", "")) if a.strip() and a.strip() != "-"]
            al = sorted(set(own + aliases.get(sid, [])))
            def _pick(prefix: str):
                for k, v in num.items():
                    if k.startswith(prefix):
                        try:
                            return int(v or 0) or None, k
                        except ValueError:
                            return None, k
                return None, ""

            atk_max, atk_key = _pick("满级攻击力")
            hp_max, hp_key = _pick("满级 HP")
            m = re.search(r"Lv\.(\d+)", atk_key or "")
            max_level = int(m.group(1)) if m else 90

            db.execute(
                "INSERT OR REPLACE INTO servants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid, region, name, name_jp, "、".join(al),
                    info.get("职阶", ""), stars(info.get("星级", "")), int(info.get("编队消耗") or 0) or None,
                    info.get("属性", ""), info.get("阵营", ""), info.get("性别", ""),
                    info.get("卡池", ""), info.get("特性", ""),
                    int(num.get("基础攻击力") or 0) or None, atk_max,
                    int(num.get("基础 HP") or 0) or None, hp_max, max_level,
                    num.get("出星率", ""), num.get("被即死率", ""), str(f),
                ),
            )
            for a in set([name, name_jp] + al):
                if a:
                    db.execute("INSERT INTO aliases VALUES (?,?,?,?)", (a, "servant", sid, region))
            n_s += 1

        for f in iter_md(WIKI / "entities" / "craft-essences" / region):
            text = f.read_text(encoding="utf-8", errors="ignore")
            sec = parse_sections(text)
            info = parse_table(sec.get("基础信息", []))
            cid = info.get("ID") or f.stem
            name = info.get("名称") or f.stem
            effect = " ".join(
                clean(x).lstrip("- ").strip()
                for k in ("未破效果", "满破效果")
                for x in sec.get(k, [])
                if x.strip().startswith("-") and "效果" in x
            )[:300]
            db.execute(
                "INSERT OR REPLACE INTO craft_essences VALUES (?,?,?,?,?,?,?,?)",
                (cid, region, name, stars(info.get("星级", "")), int(info.get("COST") or 0) or None,
                 info.get("类型", ""), effect, str(f)),
            )
            db.execute("INSERT INTO aliases VALUES (?,?,?,?)", (name, "ce", cid, region))
            n_c += 1

        for f in iter_md(WIKI / "entities" / "events" / region):
            text = f.read_text(encoding="utf-8", errors="ignore")
            sec = parse_sections(text)
            info = parse_table(sec.get("基础信息", []))
            eid = info.get("ID") or f.stem
            db.execute(
                "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)",
                (eid, region, info.get("名称", f.stem), info.get("类型", ""),
                 info.get("开始时间", ""), info.get("结束时间", ""), info.get("状态", ""), str(f)),
            )
            db.execute("INSERT INTO aliases VALUES (?,?,?,?)", (info.get("名称", f.stem), "event", eid, region))
            n_e += 1

    db.executescript("""
    CREATE INDEX idx_aliases ON aliases(alias);
    CREATE INDEX idx_servant_name ON servants(name);
    CREATE INDEX idx_ce_name ON craft_essences(name);
    CREATE INDEX idx_event_name ON events(name);
    """)
    db.commit()
    db.close()
    print(f"servants={n_s} ce={n_c} events={n_e} db={OUT} size={OUT.stat().st_size/1024/1024:.1f}MB")


if __name__ == "__main__":
    build()
