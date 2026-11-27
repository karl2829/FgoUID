# -*- coding: utf-8 -*-
"""活动日历卡：时间轴 + 分类泳道（活动 / 召唤 / 维护）。

数据来自 news 表（当前 + 未来）。每类内部按开始时间排，重叠的自动分到下一行，
条块按日期比例定位；右边放不下的短块改成「条块 + 右侧文字」。
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import render, store

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "calendar_card.html"

KINDS = (
    ("活动", "活　动", "E V E N T S", "c-act"),
    ("召唤", "召　唤", "S U M M O N S", "c-sum"),
    ("维护", "维　护", "M A I N T.", "c-mnt"),
)
PAD_X = 44             # 模板 .inner 的左右 padding
LABEL_W = 150          # 与模板 --label-w 一致
CARD_W = 1080
BARS_X = LABEL_W
BARS_W = CARD_W - PAD_X * 2 - LABEL_W
BAR_H = 38
LANE_GAP = 10


def _d(s: str) -> date | None:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _short(title: str, n: int = 15) -> str:
    t = _clean(title)
    return t if len(t) <= n else t[:n].rstrip() + "…"


def _clean(title: str) -> str:
    t = re.sub(r"[「」『』【】]", "", title or "")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(限时|预告|公告)", "", t).strip()
    return t


def build_model(items: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    rows = []
    for it in items:
        start = _d(it.get("start_at") or "")
        if not start:
            continue
        end = _d(it.get("end_at") or "") or start
        if end < today and it.get("kind") != "维护":
            continue
        rows.append({**it, "_s": start, "_e": max(end, start)})
    if not rows:
        return {}
    lo = min(min(r["_s"] for r in rows), today) - timedelta(days=3)
    hi = max(max(r["_e"] for r in rows), today) + timedelta(days=7)
    span = max((hi - lo).days, 1)
    return {"rows": rows, "lo": lo, "hi": hi, "span": span, "today": today}


def _pct(d: date, m: dict) -> float:
    return (d - m["lo"]).days / m["span"] * 100


def _axis(m: dict) -> str:
    lo, hi = m["lo"], m["hi"]
    out = []
    cur = lo
    step = 7 if (hi - lo).days <= 70 else 14
    while cur <= hi:
        left = _pct(cur, m)
        if 0 <= left <= 100:
            out.append(f'<div class="tk" style="left:{left:.3f}%">'
                       f'<span>{cur.month}-{cur.day:02d}</span></div>')
        cur += timedelta(days=step)
    left = _pct(m["today"], m)
    out.append(f'<div class="today" style="left:{left:.3f}%"><span>今天 {m["today"].month}-{m["today"].day:02d}</span></div>')
    return "".join(out)


def _maint_items(rows: list[dict]) -> list[dict]:
    """维护按天去重（同一天多条公告合成一个标记），并带上标题里的小时。"""
    seen = {}
    for r in rows:
        if r.get("kind") != "维护":
            continue
        key = r["_s"].isoformat()
        hour = ""
        mm = re.search(r"（[^）]*?(\d{1,2})时", r.get("title", ""))
        if mm:
            hour = f"{int(mm.group(1)):02d}:00"
        if key not in seen:
            seen[key] = {**r, "_hour": hour}
    return sorted(seen.values(), key=lambda r: r["_s"])


def _lane(kind: str, label: str, en: str, cls: str, rows: list[dict], m: dict) -> str:
    if kind == "维护":
        items = _maint_items(rows)
        lanes = [[it] for it in items]          # 每个维护日一行，避免标签打架
    else:
        items = sorted([r for r in rows if r.get("kind") == kind], key=lambda r: (r["_s"], r["_e"]))
        lanes = []
        for it in items:
            for lane in lanes:
                if lane[-1]["_e"] < it["_s"]:
                    lane.append(it)
                    break
            else:
                lanes.append([it])
    if not items:
        return ""
    body = []
    for lane in lanes:
        bars = []
        for it in lane:
            left = _pct(it["_s"], m)
            width = max(_pct(it["_e"], m) - left, 0.7)
            title = _clean(it.get("title", ""))
            chars = 26 if width >= 40 else (18 if width >= 25 else 12)
            short = _short(title, chars)
            span_txt = (f'{it["_s"].month}-{it["_s"].day:02d}'
                        + (f'~{it["_e"].month}-{it["_e"].day:02d}' if it["_e"] != it["_s"] else ""))
            if kind == "维护":                       # 维护是单日事件：画标记，标签放右侧
                bars.append(
                    f'<div class="bar {cls}" style="left:{left:.3f}%;width:{width:.3f}%"></div>'
                    f'<div class="lab" style="left:{min(left + width + 0.6, 78):.3f}%">'
                    f'<b>{it["_s"].month}-{it["_s"].day:02d}'
                    f'{" " + it["_hour"] if it.get("_hour") else ""} 维护</b></div>')
                continue
            if width >= 18:                          # 够宽就把标题写进条块
                bars.append(
                    f'<div class="bar {cls}" style="left:{left:.3f}%;width:{width:.3f}%">'
                    f'<span class="t">{_html.escape(short)}</span>'
                    f'<span class="d">{span_txt}</span></div>')
            elif left < 60:                          # 条块在左侧：标签放右
                bars.append(
                    f'<div class="bar {cls}" style="left:{left:.3f}%;width:{width:.3f}%"></div>'
                    f'<div class="lab" style="left:{min(left + width + 0.6, 72):.3f}%">'
                    f'<b>{_html.escape(short)}</b><s>{span_txt}</s></div>')
            else:                                    # 靠右：标签放左（右对齐）
                bars.append(
                    f'<div class="bar {cls}" style="left:{left:.3f}%;width:{width:.3f}%"></div>'
                    f'<div class="lab" style="right:{100 - left + 0.6:.3f}%;justify-content:flex-end">'
                    f'<b>{_html.escape(short)}</b><s>{span_txt}</s></div>')
        cls_row = "row mnt" if kind == "维护" else "row"
        body.append(f'<div class="{cls_row}">' + "".join(bars) + "</div>")
    return (f'<div class="lane"><div class="tag"><b>{label}</b><i>{en}</i></div>'
            f'<div class="rows">{"".join(body)}</div></div>')


def calendar_html(items: list[dict]) -> str:
    m = build_model(items)
    if not m:
        raise ValueError("没有可上时间轴的数据")
    rows = m["rows"]
    lanes = "".join(_lane(k, label, en, cls, rows, m) for k, label, en, cls in KINDS)
    stats = []
    for k, label, _en, _cls in KINDS:
        n = sum(1 for r in rows if r.get("kind") == k)
        if n:
            stats.append(f'<div class="s"><i>{label}</i><b>{n}</b></div>')
    left = _pct(m["today"], m)
    sub = (f'{m["lo"].year}.{m["lo"].month:02d}.{m["lo"].day:02d}'
           f' — {m["hi"].year}.{m["hi"].month:02d}.{m["hi"].day:02d}　·　'
           f'官网公告同步（当前 + 未来）')
    legend = ('<div class="i"><s class="c-act"></s>活动</div>'
              '<div class="i"><s class="c-sum"></s>召唤</div>'
              '<div class="i"><s class="c-mnt"></s>维护</div>'
              f'<div class="i" style="margin-left:auto"><s style="background:#E4573F"></s>今天</div>')
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "SUB": sub,
        "STATS": "".join(stats),
        "AXIS": _axis(m),
        "LANES": (lanes + f'<div class="vline" style="left:{BARS_X + BARS_W * left / 100:.1f}px"></div>'),
        "LEGEND": legend,
        "FOOT_L": f'共 {len(rows)} 项　·　数据来源 FGO 官网公告（B 站）',
    }.items():
        html = html.replace("{{%s}}" % key, val)
    left_over = [x for x in html.split("{{") if "}}" in x and x.split("}}")[0].isupper()]
    if left_over:
        raise ValueError(f"模板还有未填充占位符：{left_over[:3]}")
    return html


async def get_calendar_png(items: list[dict], quality: str = "std") -> bytes | None:
    if not render.available():
        return None
    html = calendar_html(items)
    key = hashlib.sha1((html + quality).encode("utf-8")).hexdigest()[:12]
    d = store.file("cards")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"cal_{key}.img"
    if path.is_file():
        return path.read_bytes()
    png = await render.render_png(html, TEMPLATE.parent, quality=quality, bleed=28, margin=8)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("cal_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
