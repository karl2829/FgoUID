# -*- coding: utf-8 -*-
"""御主衣服（魔术礼装）卡：衣服图 + 技能（效果/冷却曲线/5 格断点）+ 解说。

与其它卡片同一套外框与配色；缓存按 模型 + 画质 + 模板指纹 分目录，
卡片 cache key 里带模板内容，改模板即失效。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from ..card import build, fetch
from . import render
from .store import file

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "mystic_card.html"
BREAK_LEVELS = (1, 6, 10)

SRC = "fgo-wiki 快照 · Atlas Academy API"


def cache_dir() -> Path:
    d = file("cards")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _template_sig() -> str:
    try:
        return hashlib.sha1(TEMPLATE.read_bytes()).hexdigest()[:12]
    except Exception:
        return "0"


def _cache_key(model: dict, quality: str = "hd") -> str:
    blob = (json.dumps(model, ensure_ascii=False, sort_keys=True) + quality
            + _template_sig())
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _cd_values(cd: str) -> list[str]:
    return [p.strip() for p in (cd or "").split("→") if p.strip()]


def _grid(vals: list[str]) -> str:
    """Lv.1 / … / Lv.6 / … / Lv.10 五格，和从者卡技能区同一套语言。"""
    if not vals:
        return ""
    cells = []
    for idx, lv in enumerate(BREAK_LEVELS):
        if idx:
            cells.append('<div class="vc dots">…</div>')
        i = min(lv - 1, len(vals) - 1)
        edge = " edge" if lv == BREAK_LEVELS[-1] else ""
        cells.append(f'<div class="vc{edge}">{vals[i]}</div>')
    return '<div class="v5">' + "".join(cells) + "</div>"


def _skill_html(sk: dict, idx: int) -> str:
    """一个技能 = 标题 + 若干词条（每条：说明一行 + 数值五格）。"""
    parts = []
    for eff in sk.get("effects") or []:
        text = eff.get("text", "")
        grid = _grid(eff.get("vals") or [])
        parts.append(f'<div class="eff">{text}</div>' + grid)
    if not parts:                     # 老数据兜底：没有词条就整段文字
        parts.append(f'<div class="eff">{sk.get("effect", "")}</div>')
    return f'''  <div class="sk">
    <div class="sk-h">
      <div class="no">{idx}</div>
      <span class="nm">{sk.get("name", "")}</span>
    </div>
    {"".join(parts)}
  </div>'''


def mystic_model(row) -> dict:
    def g(k, d=""):
        try:
            return row[k] if row[k] is not None else d
        except Exception:
            return d

    try:
        skills = json.loads(g("skills", "[]") or "[]")
    except Exception:
        skills = []
    return {
        "id": str(g("id")),
        "name": g("name"),
        "name_jp": g("name_jp"),
        "lv_max": int(g("lv_max", 0) or 0),
        "detail": g("detail"),
        "icon_url": g("icon_url"),
        "figure_url": g("figure_url"),
        "skills": skills,
    }


def build_html(model: dict) -> str:
    skills = model.get("skills") or []
    cds = []
    for sk in skills:
        vals = _cd_values(sk.get("cd", ""))
        if vals:
            cds.append(int(vals[-1]))
    min_cd = min(cds) if cds else 0
    name_jp = model.get("name_jp") or ""
    sub = name_jp if name_jp and name_jp != model.get("name") else "御主装备 · 魔术礼装"
    detail = " ".join((model.get("detail") or "").split())      # 说明不换行，压成一段
    html = TEMPLATE.read_text(encoding="utf-8")
    pairs = {
        "{{ART}}": f"mc_icon_{model['id']}.png",
        "{{NAME}}": model.get("name", ""),
        "{{SUB}}": sub,
        "{{BADGE}}": f'御主衣服 · No.{model["id"]}',
        "{{SKILLS}}": "".join(_skill_html(sk, i + 1) for i, sk in enumerate(skills)),
        "{{DETAIL}}": detail or "—",
        "{{SRC}}": SRC,
    }
    for k, v in pairs.items():
        html = html.replace(k, v)
    return html


async def get_mystic_png(row, quality: str = "hd") -> bytes | None:
    model = mystic_model(row)
    key = _cache_key(model, quality)
    path = cache_dir() / f"mc_{model['id']}_{key}.img"
    if path.is_file():
        return path.read_bytes()

    html = build_html(model)
    names = build.assets_used(html)
    extra = await asyncio.to_thread(fetch.extra_images, model, names)
    png = await render.render_png(html, TEMPLATE.parent, extra_images=extra, quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"mc_{model['id']}_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
