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
    ("召唤", "卡　池", "C A R D　P O O L", "c-sum"),
    ("维护", "维　护", "M A I N T.", "c-mnt"),
)
PAD_X = 44             # 模板 .inner 的左右 padding
LABEL_W = 0            # 分类标题改成整行表头，不再占左侧列
NAME_W = 372           # 名称列
STATUS_W = 112         # 右侧「截止 xx」列
CARD_W = 1080
BARS_X = NAME_W
BARS_W = CARD_W - PAD_X * 2 - NAME_W - STATUS_W   # 条块区实际宽度(px)


def _text_width(text: str, size: float = 15.0) -> float:
    """粗估文字像素宽：CJK ≈ 1em，ASCII ≈ 0.55em。"""
    total = 0.0
    for ch in text:
        total += 1.0 if ord(ch) > 0x2E7F else 0.55
    return total * size


def _fit_font(text: str, avail_px: float, base: float = 15.0, floor: float = 10.5) -> float:
    """按可用宽度缩字号，尽量把整句放下。"""
    if not text or avail_px <= 0:
        return floor
    unit = _text_width(text, 1.0)
    if unit <= 0:
        return base
    return max(floor, min(base, avail_px / unit))
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
    # 时间轴只画「今天 → 最晚结束」：过去的时间不留白，条块才够宽放标题
    lo = today
    latest = max(r["_e"] for r in rows)
    hi = max(min(latest, today + timedelta(days=45)), today + timedelta(days=14))
    span = max((hi - lo).days, 1)
    return {"rows": rows, "lo": lo, "hi": hi, "span": span, "today": today}


def _pct(d: date, m: dict) -> float:
    return (d - m["lo"]).days / m["span"] * 100


def _bounds(m: dict) -> list:
    """时间轴刻度 = 所有开始/结束日 + 今天，去重排序。"""
    pts = {m["today"]}
    for r in m["rows"]:
        pts.add(r["_s"])
        pts.add(r["_e"])
    pts = sorted(p for p in pts if m["lo"] <= p <= m["hi"])
    return pts or [m["lo"], m["hi"]]


def _axis(m: dict) -> str:
    """刻度线全画；标签按可用宽度避让，放不下就换行，仍放不下就省略。"""
    pts = _bounds(m)
    out = []
    rows_end = [-999.0, -999.0]        # 两行标签各自已占到的最右位置
    for d in pts:
        left = _pct(d, m)
        is_today = d == m["today"]
        label = f'{d.month}-{d.day:02d}'
        need = 6.0 if not is_today else 9.5      # 估宽（百分比，11.5px 字号 5 个字符）
        spot = None
        for row in (0, 1):
            if left - rows_end[row] >= need:
                spot = row
                break
        if is_today:
            spot = 0
        cls = "tk" + (" today" if is_today else "")
        style = f'left:{max(left, 0.2):.3f}%'
        span = ""
        if spot is not None:
            rows_end[spot] = left + need
            text = label + (" 今天" if is_today else "")
            top = "2px" if is_today else ("18px" if spot == 0 else "34px")
            span = f'<span style="top:{top};left:5px">{text}</span>'
        out.append(f'<div class="{cls}" style="{style}">{span}</div>')
    return "".join(out)


def _grid(m: dict) -> str:
    """贯穿泳道的竖线：每个起止日一条，今天的线用红色。"""
    out = []
    for d in _bounds(m):
        left = BARS_X + BARS_W * _pct(d, m) / 100
        if d == m["today"]:
            out.append(f'<div class="vline" style="left:{left:.1f}px"></div>')
        else:
            out.append(f'<div class="gline" style="left:{left:.1f}px"></div>')
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


def _status(it: dict, today) -> tuple[str, str]:
    """右侧状态：进行中显示截止日，未开始显示开始日，无终点显示「起」。"""
    d1 = f'{it["_s"].month:02d}-{it["_s"].day:02d}'
    if not it.get("end_at"):
        return f'{d1} 起', ""
    d2 = f'{it["_e"].month:02d}-{it["_e"].day:02d}'
    if str(it.get("end_guess") or "0").strip() == "1":
        d2 = "≈" + d2
    if it["_s"] > today:
        return f'{d1} 开始', ""
    left = (it["_e"] - today).days
    hot = left <= 3
    return f'截止 {d2}', (" hot" if hot else "")


def _lane(kind: str, label: str, en: str, cls: str, rows: list[dict], m: dict) -> str:
    if kind == "维护":
        items = _maint_items(rows)
    else:
        items = sorted([r for r in rows if r.get("kind") == kind], key=lambda r: (r["_s"], r["_e"]))
    if not items:
        return ""

    body = []
    for it in items:
        s_clamped = max(it["_s"], m["lo"])
        left = _pct(s_clamped, m)
        width = max(_pct(it["_e"], m) - left, 0.6)
        title = _clean(it.get("title", ""))
        status, hot = _status(it, m["today"])
        if kind == "维护":
            hour = f' {it["_hour"]}' if it.get("_hour") else ""
            title = "维护"
            status = f'{it["_s"].month:02d}-{it["_s"].day:02d}{hour}'
            hot = ""
        bar = (f'<div class="bar {cls}" style="left:{left:.3f}%;width:{width:.3f}%">'
               f'<span class="cap"></span></div>')
        body.append(
            f'<div class="row{" mnt" if kind == "维护" else ""}">'
            f'<div class="name">{_html.escape(title)}</div>'
            f'<div class="area">{bar}</div>'
            f'<div class="status{hot}">{status}</div></div>')

    head = (f'<div class="lane-hd"><b>{label}</b><s>{en}</s>'
            f'<span class="cnt">{len(items)}</i></span></div>')
    return head + "".join(body)


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
              '<div class="i"><s class="c-sum"></s>卡池</div>'
              '<div class="i"><s class="c-mnt"></s>维护</div>'
              '<div class="i" style="margin-left:auto"><s style="background:#E4573F"></s>今天</div>')
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "SUB": sub,
        "STATS": "".join(stats),
        "AXIS": _axis(m),
        "LANES": lanes + _grid(m),
        "LEGEND_COLOR": legend,

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
