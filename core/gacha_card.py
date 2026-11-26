# -*- coding: utf-8 -*-
"""卡池日历卡：gacha 行 → 模型 → HTML 投影 → pytakumi 渲染 → 磁盘缓存。

和帮助卡/从者卡同一套路子（模型层不碰渲染），共用 ``core/render.py`` 的并发送流。
卡池横幅来自 wiki 的 ``raw/gacha/gacha_raw.json``（由 ``tools/sync_gacha.py`` 回填到
``gacha.banner``），托管在 jsdelivr 的 ``karl2829/fgo-images`` 仓库，国内可直连。
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

TITLE = "卡池日历"
EYEBROW_LEFT = "F G O U I D"
EYEBROW_RIGHT = "G A C H A"
FOOTER = {
    "l1": "数据来源　fgo-wiki 快照　·　Mooncell 卡池一览",
    "l2": "版权所有　TYPE-MOON / FGO PROJECT　·　非官方插件",
    "r1": "DESIGN BY MILA",
    "r2": "DARK-CHALDEA FRAME ／ GACHA v1",
}


def _banner_name(url: str) -> str:
    return "gacha_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] + ".png"


def _span_text(start: str, end: str) -> str:
    if not start and not end:
        return "时间未知"
    today = date.today()
    try:
        s = date.fromisoformat(start) if start else None
        e = date.fromisoformat(end) if end else None
    except ValueError:
        return f"{start} ~ {end}".strip(" ~")
    days = f"（{(e - s).days + 1} 天）" if s and e else ""
    if s and today < s:
        return f"{start} ~ {end}{days} · 还有 {(s - today).days} 天"
    if e and today <= e:
        return f"{start} ~ {end}{days} · 开放中，剩 {(e - today).days} 天"
    return f"{start} ~ {end}{days} · 已结束"


def _model_row(r) -> dict:
    keys = r.keys() if hasattr(r, "keys") else ()
    banner = (r["banner"] if "banner" in keys else "") or ""
    up = (r["up_servants"] or "").strip()
    return {
        "name": (r["name"] or "").strip(),
        "region": (r["region"] or "").strip(),
        "type": (r["gacha_type"] or "").strip(),
        "status": (r["status"] or "").strip(),
        "span": _span_text(r["start_time"] or "", r["end_time"] or ""),
        "up": up,
        "banner": _banner_name(banner) if banner else "",
        "banner_url": banner,
    }


def gacha_model(rows, keyword: str = "") -> dict:
    items = [_model_row(r) for r in rows]
    regions = sorted({i["region"] for i in items if i["region"]})
    starts = [i["span"][:10] for i in items if len(i["span"]) >= 10]
    sub = f"{len(items)} 期·数据来自 fgo-wiki 快照"
    if keyword:
        sub = f"搜索「{keyword}」·{sub}"
    return {
        "header": {
            "eyebrow_left": EYEBROW_LEFT,
            "eyebrow_right": EYEBROW_RIGHT,
            "title": TITLE,
            "sub": sub,
            "pill": "／".join(regions) if regions else "FGO",
        },
        "stats": [
            ("卡　池", str(len(items))),
            ("最　早", starts[0][5:] if starts else "—"),
            ("最　晚", max(i["span"][:10] for i in items)[5:] if items else "—"),
            ("带横幅", str(sum(1 for i in items if i["banner"]))),
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
    if "预估" in it["status"]:
        tags.append('<span class="tag est">预估</span>')
    box = (
        f'<div class="gb"><img src="../assets/{it["banner"]}"></div>'
        if it["banner"] else '<div class="gb empty">无横幅</div>'
    )
    up = f'<div class="gu"><b>UP</b>　{esc(it["up"])}</div>' if it["up"] else ""
    return (
        f'<div class="g">{box}<div class="gi">'
        f'<div class="gn">{esc(it["name"])}</div>'
        f'<div class="gm">{"".join(tags)}</div>'
        f'<div class="gd">{esc(it["span"])}</div>'
        f"{up}</div></div>"
    )


def gacha_html(model: dict) -> str:
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


def _cache_key(model: dict) -> str:
    blob = json.dumps(model, ensure_ascii=False, sort_keys=True) + TEMPLATE.read_text(encoding="utf-8")
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def prewarm_banners(limit: int = 12) -> int:
    """后台把接下来几期卡池的横幅下到缓存（首图慢主要慢在这 ~150KB/张的下图）。

    只下横幅、不渲染：启动时跑一次，之后 ``fgo卡池`` 基本 4s 内出图。
    """
    from ..card import fetch as card_fetch
    from .db import list_gacha

    rows = list_gacha("", limit)
    mapping = {}
    for r in rows:
        keys = r.keys()
        banner = (r["banner"] if "banner" in keys else "") or ""
        if banner:
            mapping[_banner_name(banner)] = banner
    if not mapping:
        return 0
    got = await asyncio.to_thread(card_fetch.remote_images, mapping)
    missing = [n for n in mapping if n not in got]
    from gsuid_core.logger import logger

    if missing:
        logger.info(f"[FGOUID] 卡池横幅预热 {len(got)}/{len(mapping)}，缺 {len(missing)} 张（下次再试）")
    else:
        logger.info(f"[FGOUID] 卡池横幅预热完成：{len(got)} 张")
    return len(got)


async def get_gacha_png(rows, keyword: str = "") -> bytes | None:
    """渲染卡池卡；pytakumi 不可用/渲染失败时返回 None（调用方降级文字）。"""
    model = gacha_model(rows, keyword)
    if not model["items"]:
        return None
    key = _cache_key(model)
    path = store.data_dir() / f"gacha_{key}.png"
    if path.is_file():
        return path.read_bytes()
    if not render.available():
        return None

    from ..card import fetch as card_fetch

    mapping = {it["banner"]: it["banner_url"] for it in model["items"] if it["banner"]}
    images = await asyncio.to_thread(card_fetch.remote_images, mapping) if mapping else None
    png = await render.render_png(gacha_html(model), TEMPLATE.parent, extra_images=images)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("gacha_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
