# -*- coding: utf-8 -*-
"""活动日历卡：events 行 → 模型 → HTML → pytakumi 渲染 → 磁盘缓存。

和卡池卡共用 ``templates/list_card.html`` 的列表版式（横幅 + 标题 + 标签 + 时间）。

横幅走 ``events.banner``（``tools/sync_gacha.py`` 从 wiki ``raw/events`` 回填，
图在 Atlas 的 ``Banner/event_war_*.png``）。没有横幅的活动用同尺寸占位块，
版式不会跳。
"""
from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
from datetime import date
from pathlib import Path

from . import render, store

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "list_card.html"

TITLE = "活动日历"
EYEBROW_LEFT = "F G O U I D"
EYEBROW_RIGHT = "E V E N T"
FOOTER = {
    "l1": "数据来源　fgo-wiki 快照　·　Atlas Academy API",
    "l2": "版权所有　TYPE-MOON / FGO PROJECT　·　非官方插件",
    "r1": "DESIGN BY MILA",
    "r2": "DARK-CHALDEA FRAME ／ EVENT v1",
}

TYPE_LABEL = {
    "eventQuest": "活动关卡",
    "warBoard": "棋盘战",
    "mainQuest": "主线",
    "campaign": "纪念活动",
}


def _banner_name(url: str) -> str:
    return "event_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] + ".png"


def _status_of(start: str, end: str, raw: str = "") -> str:
    today = date.today().isoformat()
    if start and end:
        if start <= today <= end:
            return "进行中"
        if start > today:
            return "未来"
        return "已结束"
    return (raw or "").strip()


def _span_text(start: str, end: str) -> str:
    if not start and not end:
        return "时间未知"
    try:
        s = date.fromisoformat(start) if start else None
        e = date.fromisoformat(end) if end else None
    except ValueError:
        return f"{start} ~ {end}".strip(" ~")
    days = f"（{(e - s).days + 1} 天）" if s and e else ""
    return f"{start} ~ {end}{days}"


def _model_row(r) -> dict:
    keys = r.keys() if hasattr(r, "keys") else ()
    banner = (r["banner"] if "banner" in keys else "") or ""
    etype = (r["event_type"] or "").strip()
    start = (r["start_time"] or "").strip()
    end = (r["end_time"] or "").strip()
    return {
        "name": (r["name"] or "").strip(),
        "region": (r["region"] or "").strip(),
        "type": TYPE_LABEL.get(etype, etype),
        "status": _status_of(start, end, (r["status"] or "")),
        "span": _span_text(start, end),
        "banner": _banner_name(banner) if banner else "",
        "banner_url": banner,
    }


def event_model(rows, keyword: str = "") -> dict:
    items = [_model_row(r) for r in rows]
    regions = sorted({i["region"] for i in items if i["region"]})
    sub = f"{len(items)} 个活动　·　数据来自 fgo-wiki 快照"
    if keyword:
        sub = f"搜索「{keyword}」　·　{sub}"
    return {
        "header": {
            "eyebrow_left": EYEBROW_LEFT,
            "eyebrow_right": EYEBROW_RIGHT,
            "title": TITLE,
            "sub": sub,
            "pill": "／".join(regions) if regions else "FGO",
        },
        "stats": [
            ("活　动", str(len(items))),
            ("进行中", str(sum(1 for i in items if i["status"] == "进行中"))),
            ("未　来", str(sum(1 for i in items if i["status"] == "未来"))),
            ("已结束", str(sum(1 for i in items if i["status"] == "已结束"))),
        ],
        "items": items,
        "footer": FOOTER,
    }


def _row_html(it: dict) -> str:
    esc = _html.escape
    tags = []
    if it["region"]:
        tags.append(f'<span class="tag{" jp" if it["region"] == "JP" else ""}">{esc(it["region"])}</span>')
    if it["type"]:
        tags.append(f'<span class="tag">{esc(it["type"])}</span>')
    if it["status"] == "进行中":
        tags.append('<span class="tag">进行中</span>')
    elif it["status"] == "未来":
        tags.append('<span class="tag est">未开始</span>')
    box = (
        f'<div class="gb"><img src="../assets/{it["banner"]}"></div>'
        if it["banner"] else '<div class="gb empty">暂无横幅</div>'
    )
    return (
        f'<div class="g">{box}<div class="gi">'
        f'<div class="gn">{esc(it["name"])}</div>'
        f'<div class="gm">{"".join(tags)}</div>'
        f'<div class="gd">{esc(it["span"])}</div>'
        f"</div></div>"
    )


def event_html(model: dict) -> str:
    stats = "".join(f'<div class="st"><i>{lb}</i><b>{v}</b></div>' for lb, v in model["stats"])
    rows = "".join(_row_html(it) for it in model["items"])
    hd, ft = model["header"], model["footer"]
    out = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "EYEBROW_LEFT": hd["eyebrow_left"],
        "EYEBROW_RIGHT": hd["eyebrow_right"],
        "TITLE": hd["title"],
        "SUB": hd["sub"],
        "PILL": hd["pill"],
        "STATS": stats,
        "ROWS": rows,
        "FOOT_L1": ft["l1"],
        "FOOT_L2": ft["l2"],
        "FOOT_R1": ft["r1"],
        "FOOT_R2": ft["r2"],
    }.items():
        out = out.replace("{{%s}}" % key, val)
    left = [m for m in out.split("{{") if "}}" in m and m.split("}}")[0].isupper()]
    if left:
        raise ValueError(f"模板还有未填充占位符：{left[:3]}")
    return out


def _cache_key(model: dict, quality: str = "hd") -> str:
    blob = (json.dumps(model, ensure_ascii=False, sort_keys=True) + quality
            + TEMPLATE.read_text(encoding="utf-8"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def prewarm_banners(limit: int = 6) -> int:
    """启动时把默认列表里那几个活动的横幅先下下来（首图慢主要慢在 Atlas 的图上）。"""
    from ..card import fetch as card_fetch
    from .db import search_events

    rows = search_events("", limit)
    mapping = {}
    for r in rows:
        keys = r.keys()
        banner = (r["banner"] if "banner" in keys else "") or ""
        if banner:
            mapping[_banner_name(banner)] = banner
    if not mapping:
        return 0
    got = await asyncio.to_thread(card_fetch.remote_images, mapping)
    return len(got)


async def get_event_png(rows, keyword: str = "", quality: str = "hd") -> bytes | None:
    model = event_model(rows, keyword)
    if not model["items"]:
        return None
    key = _cache_key(model, quality)
    path = store.data_dir() / f"events_{key}.png"
    if path.is_file():
        return path.read_bytes()
    if not render.available():
        return None

    from ..card import fetch as card_fetch

    mapping = {it["banner"]: it["banner_url"] for it in model["items"] if it["banner"]}
    images = await asyncio.to_thread(card_fetch.remote_images, mapping) if mapping else None
    # 有些横幅在 CDN 上已经 404（raw 里还有 URL），下不回来的就别留空洞，
    # 改成「暂无横幅」占位，免得版式上出现空白框
    got = {k[len("../assets/"):] for k in (images or {}) if k.startswith("../assets/")}
    missing = {it["banner"] for it in model["items"] if it["banner"] and it["banner"] not in got}
    if missing:
        for it in model["items"]:
            if it["banner"] in missing:
                it["banner"] = ""
        key2 = _cache_key(model, quality)
        path2 = path.parent / path.name.replace(key, key2)
        if path2.is_file():
            return path2.read_bytes()
        key, path = key2, path2
    png = await render.render_png(event_html(model), TEMPLATE.parent, extra_images=images,
                                  quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("events_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
