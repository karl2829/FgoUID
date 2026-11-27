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
from datetime import date, timedelta
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
    sub = f"{len(items)} 期　·　数据来自 fgo-wiki 快照"
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


def _cache_key(model: dict, quality: str = "hd") -> str:
    blob = (json.dumps(model, ensure_ascii=False, sort_keys=True) + quality
            + TEMPLATE.read_text(encoding="utf-8"))
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
    have = {k[len("../assets/"):] for k in got if k.startswith("../assets/")}
    missing = [n for n in mapping if n not in have]
    from gsuid_core.logger import logger

    if missing:
        logger.info(f"[FGOUID] 卡池横幅预热 {len(got)}/{len(mapping)}，缺 {len(missing)} 张（下次再试）")
    else:
        logger.info(f"[FGOUID] 卡池横幅预热完成：{len(got)} 张")
    return len(got)


async def get_gacha_png(rows, keyword: str = "", quality: str = "hd") -> bytes | None:
    """渲染卡池卡；pytakumi 不可用/渲染失败时返回 None（调用方降级文字）。"""
    model = gacha_model(rows, keyword)
    if not model["items"]:
        return None
    key = _cache_key(model, quality)
    path = store.data_dir() / f"gacha_{key}.png"
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
    png = await render.render_png(gacha_html(model), TEMPLATE.parent, extra_images=images,
                                  quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("gacha_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png


# ---------------------------------------------------------------- 时间轴版（卡片 v2）
TIMELINE_TEMPLATE = PKG / "templates" / "gacha_card.html"
PAD_X = 44
NAME_W = 572          # 缩略图(142) + 名称列(430)
BARS_W = 376
GACHA_CLS = "c-sum"


def _d(value: str):
    try:
        return date.fromisoformat((value or "")[:10])
    except Exception:
        return None


def _clean_name(name: str) -> str:
    t = (name or "").replace("推荐召唤", "").strip("「」『』！· ")
    return t or (name or "")


def gacha_sections(rows, today=None) -> dict:
    today = today or date.today()
    items = []
    for r in rows:
        s, e = _d(r["start_time"]), _d(r["end_time"])
        if not s or not e or e < today:
            continue
        items.append({
            "name": _clean_name(r["name"]),
            "up": (r["up_servants"] or "").strip(),
            "start": s, "end": e,
            "banner": _banner_name(r["banner"]) if r["banner"] else "",
            "banner_url": r["banner"] or "",
        })
    ongoing = sorted([i for i in items if i["start"] <= today], key=lambda i: i["end"])
    upcoming = sorted([i for i in items if i["start"] > today], key=lambda i: i["start"])
    if not items:
        return {}
    lo = today
    hi = max(i["end"] for i in items)
    hi = max(min(hi, today + timedelta(days=45)), today + timedelta(days=10))
    # 超出窗口的（45 天以后才开始）先不放进图里，免得条块顶到卡片外
    items = [i for i in items if i["start"] <= hi]
    if not items:
        return {}
    ongoing = [i for i in ongoing if i["start"] <= hi]
    upcoming = [i for i in upcoming if i["start"] <= hi]
    for i in items:                                  # 结束日也不超过窗口
        i["end"] = min(i["end"], hi)
    return {"ongoing": ongoing, "upcoming": upcoming, "lo": lo, "hi": hi,
            "span": max((hi - lo).days, 1), "today": today}


def _pct(d, m) -> float:
    return (d - m["lo"]).days / m["span"] * 100


def _row(it, m, kind_cls) -> str:
    today = m["today"]
    left = min(max(_pct(max(it["start"], m["lo"]), m), 0.0), 99.4)
    width = min(max(_pct(it["end"], m) - left, 0.6), 100.0 - left)
    if it["start"] > today:
        status = f'{it["start"].month:02d}-{it["start"].day:02d} 开始'
        hot = ""
    else:
        left_days = (it["end"] - today).days
        status = f'剩 {left_days} 天 · 截止 {it["end"].month:02d}-{it["end"].day:02d}'
        hot = " hot" if left_days <= 2 else ""
    thumb = (f'<div class="th"><img src="../assets/{it["banner"]}"></div>'
             if it["banner"] else '<div class="th"></div>')
    up = (f'<div class="up"><b>UP</b>{_html.escape(_short(it["up"], 46))}</div>'
          if it["up"] else '<div class="up">&nbsp;</div>')
    end_pct = left + width
    if width >= 34 and end_pct <= 88:            # 够宽且不出界：写在块内
        bar = (f'<div class="bar {kind_cls}" style="left:{left:.3f}%;width:{width:.3f}%">'
               f'<span class="st in{hot}">{status}</span></div>')
        st = ""
    elif end_pct <= 58:                          # 靠左：跟在块尾
        bar = f'<div class="bar {kind_cls}" style="left:{left:.3f}%;width:{width:.3f}%"></div>'
        st = f'<div class="st{hot}" style="left:{end_pct + 2.0:.3f}%">{status}</div>'
    else:                                        # 靠右：放块左侧
        bar = f'<div class="bar {kind_cls}" style="left:{left:.3f}%;width:{width:.3f}%"></div>'
        st = (f'<div class="st left{hot}" style="right:{max(100 - left + 2.0, 2.0):.3f}%">'
              f'{status}</div>')
    return (f'<div class="row">{thumb}<div class="name">'
            f'<div class="nm">{_html.escape(it["name"])}</div>{up}</div>'
            f'<div class="area">{bar}{st}</div></div>')


def _short(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def gacha_timeline_html(sections: dict, keyword: str = "") -> str:
    m = sections
    rows = m["ongoing"] + m["upcoming"]
    parts = []
    for title, en, items in (("进行中", "O N G O I N G", m["ongoing"]),
                             ("即将开始", "U P C O M I N G", m["upcoming"])):
        if not items:
            continue
        body = "".join(_row(it, m, GACHA_CLS) for it in items)
        parts.append(f'<div class="sec"><div class="lane-hd"><b>{title}</b><s>{en}</s>'
                     f'<span class="cnt">{len(items)}</span></div>{body}</div>')

    marks = [(m["today"], "today", f'{m["today"].month}-{m["today"].day:02d} 今天')]
    if m["upcoming"]:
        d = m["upcoming"][0]["start"]
        marks.append((d, "start", f'{d.month}-{d.day:02d} 新卡池'))
    axis = "".join(
        f'<div class="tk {cls}" style="left:{max(_pct(d, m), 0.2):.3f}%">'
        f'<span style="top:{2 if cls == "today" else 24}px;left:5px">{label}</span></div>'
        for d, cls, label in marks)

    sub = (f'{m["lo"].year}.{m["lo"].month:02d}.{m["lo"].day:02d} — '
           f'{m["hi"].year}.{m["hi"].month:02d}.{m["hi"].day:02d}　·　'
           + (f'搜索「{keyword}」　·　' if keyword else "") + "官网公告同步（当前 + 未来）")
    stats = (f'<div class="s"><i>进行中</i><b>{len(m["ongoing"])}</b></div>'
             f'<div class="s"><i>即将开始</i><b>{len(m["upcoming"])}</b></div>')

    html = TIMELINE_TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "SUB": sub,
        "STATS": stats,
        "AXIS": axis,
        "LANES": "".join(parts),
        "FOOT_L": f'共 {len(rows)} 期　·　数据来源 fgo-wiki 快照',
    }.items():
        html = html.replace("{{%s}}" % key, val)
    left = [x for x in html.split("{{") if "}}" in x and x.split("}}")[0].isupper()]
    if left:
        raise ValueError(f"模板还有未填充占位符：{left[:3]}")
    return html


async def get_gacha_timeline_png(rows, keyword: str = "", quality: str = "std") -> bytes | None:
    sections = gacha_sections(rows)
    if not sections or not (sections["ongoing"] or sections["upcoming"]):
        return None
    if not render.available():
        return None
    html = gacha_timeline_html(sections, keyword)
    key = hashlib.sha1((html + quality).encode("utf-8")).hexdigest()[:12]
    d = store.data_dir() / "cards"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"gcal_{key}.img"
    if path.is_file():
        return path.read_bytes()

    from ..card import fetch as card_fetch

    mapping = {it["banner"]: it["banner_url"] for it in sections["ongoing"] + sections["upcoming"]
               if it["banner"]}
    images = await asyncio.to_thread(card_fetch.remote_images, mapping) if mapping else None
    got = {k[len("../assets/"):] for k in (images or {}) if k.startswith("../assets/")}
    for it in sections["ongoing"] + sections["upcoming"]:
        if it["banner"] and it["banner"] not in got:
            it["banner"] = ""
    html = gacha_timeline_html(sections, keyword) if mapping else html
    png = await render.render_png(html, TIMELINE_TEMPLATE.parent, quality=quality,
                                  extra_images=images, bleed=28, margin=8)
    try:
        path.write_bytes(png)
        for stale in d.glob("gcal_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
