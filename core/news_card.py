# -*- coding: utf-8 -*-
"""官网公告卡（白底黑字）：维护公告推送用。

输入是 news 表的一行；输出 1080 宽的浅色卡片。渲染失败时调用方回落纯文字。
"""
from __future__ import annotations

import hashlib
import html as _html
import json
from datetime import date
import re
from pathlib import Path

from . import render, store

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "news_card.html"

KIND_CN = {"维护": "维　护", "活动": "活　动", "召唤": "召　唤", "公告": "公　告"}
SOURCE = "数据来源　FGO 官网公告（B 站）"


def cache_dir() -> Path:
    d = store.file("cards")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def news_html(item: dict) -> str:
    esc = _html.escape
    title = _clean(item.get("title", ""))
    summary = _clean(item.get("summary", ""))
    if len(summary) > 260:
        summary = summary[:260].rstrip() + "……"
    meta = [f"发布　{esc((item.get('ctime') or '')[:16])}"]
    when = item.get("start_at") or ""
    if when:
        meta.append(f"维护日　{esc(when)}")
    WEEK = "一二三四五六日"

    def _weekday(d: str) -> str:
        try:
            y, m, dd = int(d[0:4]), int(d[5:7]), int(d[8:10])
            return "周" + WEEK[date(y, m, dd).weekday()]
        except Exception:
            return ""

    ms, me = (item.get("maint_start") or ""), (item.get("maint_end") or "")
    time_band = ""
    if ms:
        day, hm = ms[:10], ms[11:]
        end_txt = me[11:] if (me and me[:10] == day) else (me or "")
        pretty = f"{int(day[5:7])}月{int(day[8:10])}日"
        time_band = (f'<div class="band"><span class="k">维 护 时 间</span>'
                     f'<span class="v">{hm}'
                     f'<small>～ {end_txt}　·　{pretty} {_weekday(day)}</small></span></div>')

    items_block = ""
    try:
        items = json.loads(item.get("contents") or "[]")
    except Exception:
        items = []
    if items:
        rows = "".join(
            f'<div class="it"><i>{i}</i><span>{esc(x)}</span></div>'
            for i, x in enumerate(items[:12], start=1)
        )
        items_block = (f'<div class="block"><div class="bh"><i></i><b>维护内容</b>'
                       f'<s>{len(items)} 项</s></div><div class="items">{rows}</div></div>')

    comp = (item.get("comp") or "").strip()
    comp_time = (item.get("comp_time") or "").strip()
    comp_to = (item.get("comp_to") or "").strip()
    comp_block = ""
    if comp or comp_time or comp_to:
        rows = []
        if comp:
            rows.append(f'<div class="row"><i>补偿内容</i><b class="hl">{esc(comp)}</b></div>')
        if comp_time:
            rows.append(f'<div class="row"><i>发放时间</i><b>{esc(comp_time)}</b></div>')
        if comp_to:
            rows.append(f'<div class="row"><i>补偿对象</i><b>{esc(comp_to)}</b></div>')
        comp_block = ('<div class="block"><div class="bh"><i></i><b>维护补偿</b></div>'
                      f'<div class="comp">{"".join(rows)}</div></div>')

    note = esc(summary[:120]) if summary else ""

    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "TITLE": esc(title),
        "KIND": KIND_CN.get(item.get("kind", ""), esc(item.get("kind", "公告"))),
        "META": "<span>　·　</span>".join(meta),
        "SUMMARY": esc(summary) or "（该公告没有正文摘要，点下面链接看原文）",
        "SOURCE": SOURCE,
        "TIME_BAND": time_band,
        "ITEMS_BLOCK": items_block,
        "COMP_BLOCK": comp_block,
        "NOTE": note,
    }.items():
        html = html.replace("{{%s}}" % key, val)
    left = [m for m in html.split("{{") if "}}" in m and m.split("}}")[0].isupper()]
    if left:
        raise ValueError(f"模板还有未填充占位符：{left[:3]}")
    return html


async def get_news_png(item: dict, quality: str = "std") -> bytes | None:
    if not render.available():
        return None
    key = hashlib.sha1(
        (news_html(item) + quality).encode("utf-8")
    ).hexdigest()[:12]
    path = cache_dir() / f"news_{item.get('id', '0')}_{key}.img"
    if path.is_file():
        return path.read_bytes()
    png = await render.render_png(
        news_html(item), TEMPLATE.parent, quality=quality, bleed=28, margin=8
    )
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"news_{item.get('id', '0')}_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
