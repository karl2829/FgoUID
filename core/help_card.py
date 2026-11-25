# -*- coding: utf-8 -*-
"""帮助卡：数据模型 → HTML 投影 →（将来可换）PIL 投影。

分三层，故意拆开：
  1. ``help_model()``  —— 纯数据（文案、数字、区块结构），不含任何渲染细节
  2. ``help_html(model)`` —— 把模型投影成 HTML 片段（当前后端：pytakumi/Skia）
  3. ``get_help_png()`` —— 渲染 + 磁盘缓存 + 降级

将来若要把渲染换成 PIL，只需要照着 ``help_model()`` 再写一个 ``help_pil(model)``，
模型层不用动——这也是当初把模板拆成「外框 + 区块占位符」的原因。
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import sqlite3
import tempfile
from pathlib import Path

from . import render
from .db import DB_PATH

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "help_card.html"
META = PKG / "data" / "meta.json"

EYEBROW_LEFT = "F G O U I D"
EYEBROW_RIGHT = "G S - C O R E&nbsp;&nbsp;·&nbsp;&nbsp;P L U G I N"
TITLE = "指令帮助"
SUB = "FGO 查询插件　·　指令即查　·　数据来自 fgo-wiki 离线快照"
PILL = "运行中"

# 指令区（改命令就改这里，HTML 与将来的 PIL 共用）
SECTION_COMMANDS = {
    "title": "查询指令",
    "en": "C O M M A N D S",
    "kind": "rows",
    "rows": [
        {"k": "fgo从者 &lt;名称&gt;", "d": "星级、职阶、攻击 / HP、属性、阵营、性别、特性、卡池",
         "e": "fgo从者 摩根"},
        {"k": "fgo礼装 &lt;名称&gt;", "d": "星级、COST、类型、效果", "e": "fgo礼装 宝石翁"},
        {"k": "fgo活动 [关键词]", "d": "未来 730 天内的活动；带关键词则在全部活动中搜索",
         "e": "fgo活动 特异点"},
        {"k": "fgo卡池 [关键词]", "d": "近期卡池与 UP 从者；带关键词则按卡池名搜索",
         "e": "fgo卡池 摩根"},
    ],
}

SECTION_UTILITY = {
    "title": "辅助指令",
    "en": "U T I L I T Y",
    "kind": "duo",
    "rows": [
        {"k": "fgo测试", "d": "链路自检：能收到回复即插件正常"},
        {"k": "fgo帮助", "d": "显示本图，随时查看指令与用法"},
    ],
}

FOOTER = {
    "l1": "数据来源　fgo-wiki 快照　·　Mooncell / Atlas Academy API",
    "l2": "版权所有　TYPE-MOON / FGO PROJECT　·　非官方插件",
    "r1": "DESIGN BY MILA",
    "r2": "DARK-CHALDEA FRAME ／ HELP v1",
}


def _alias_count() -> int:
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
            return con.execute("select count(*) from aliases").fetchone()[0]
    except Exception:
        return 0


def help_model() -> dict:
    """卡片内容模型（唯一数据源，渲染后端无关）。"""
    meta = json.loads(META.read_text(encoding="utf-8"))
    counts = meta.get("counts", {})
    aliases = _alias_count()
    return {
        "header": {"eyebrow_left": EYEBROW_LEFT, "eyebrow_right": EYEBROW_RIGHT,
                   "title": TITLE, "sub": SUB, "pill": PILL},
        "stats": [
            ("从　者", f"{counts.get('servants', 0):,}"),
            ("礼　装", f"{counts.get('ce', 0):,}"),
            ("活　动", f"{counts.get('events', 0):,}"),
            ("卡　池", f"{counts.get('gacha', 0):,}"),
        ],
        "sections": [
            SECTION_COMMANDS,
            SECTION_UTILITY,
            {
                "title": "使用提示",
                "en": "N O T E S",
                "kind": "notes",
                "notes": [
                    {"mark": "◆", "hl": True,
                     "html": f"共 <b>{aliases:,}</b> 条别名可直接用：<b>C呆</b> → 阿尔托莉雅·卡斯特、"
                             "<b>宝石翁</b> → 万华镜、<b>黑杯</b> → 黑之圣杯"},
                    {"mark": "◇", "hl": False,
                     "html": "国服优先，无国服条目时回落日服；名称支持部分匹配，不必打全名"},
                    {"mark": "◇", "hl": False,
                     "html": f"数据为离线快照（wiki @ {str(meta.get('source_commit', ''))[:7]}），"
                             "查询不联网、无外部依赖"},
                    {"mark": "◇", "hl": False, "html": "直接发送指令即可，无需 @ 机器人"},
                ],
            },
        ],
        "footer": FOOTER,
    }


# ---------------------------------------------------------------- HTML 投影

def _sec_head(title: str, en: str) -> str:
    return (
        '<div class="sec-h"><div class="bar"></div>'
        f'<div class="t">{title}</div><div class="line"></div><div class="n">{en}</div></div>'
    )


def _section_html(sec: dict) -> str:
    kind = sec["kind"]
    head = _sec_head(sec["title"], sec["en"])
    if kind == "rows":
        rows = "".join(
            f'<div class="row"><div class="k">{r["k"]}</div>'
            f'<div class="d">{r["d"]}</div>'
            f'<div class="e">例　<b>{r["e"]}</b></div></div>'
            for r in sec["rows"]
        )
        return head + f'<div class="cmds">{rows}</div>'
    if kind == "duo":
        rows = "".join(
            f'<div class="row"><div class="k">{r["k"]}</div><div class="d">{r["d"]}</div></div>'
            for r in sec["rows"]
        )
        return head + f'<div class="duo">{rows}</div>'
    if kind == "notes":
        items = "".join(
            f'<div class="nt{" hl" if n.get("hl") else ""}"><i>{n["mark"]}</i><div>{n["html"]}</div></div>'
            for n in sec["notes"]
        )
        return head + f'<div class="notes">{items}</div>'
    raise ValueError(f"未知区块类型：{kind}")


def help_html(model: dict) -> str:
    stats = "".join(f'<div class="st"><i>{lb}</i><b>{v}</b></div>' for lb, v in model["stats"])
    body = "\n".join(_section_html(sec) for sec in model["sections"])
    hd, ft = model["header"], model["footer"]
    out = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "EYEBROW_LEFT": hd["eyebrow_left"],
        "EYEBROW_RIGHT": hd["eyebrow_right"],
        "TITLE": hd["title"],
        "SUB": hd["sub"],
        "PILL": hd["pill"],
        "STATS": stats,
        "BODY": body,
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


# ---------------------------------------------------------------- 缓存 + 渲染

def cache_dir() -> Path:
    try:
        from gsuid_core.data_store import get_res_path

        return get_res_path("FGOUID")
    except Exception:
        p = Path(tempfile.gettempdir()) / "FGOUID"
        p.mkdir(parents=True, exist_ok=True)
        return p


def _cache_key(model: dict) -> str:
    blob = json.dumps(model, ensure_ascii=False, sort_keys=True) + TEMPLATE.read_text(encoding="utf-8")
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def get_help_png() -> bytes | None:
    """返回帮助图 PNG bytes；pytakumi 不可用或渲染失败时返回 None（调用方降级）。"""
    model = help_model()
    key = _cache_key(model)
    path = cache_dir() / f"help_{key}.png"
    if path.is_file():
        return path.read_bytes()
    if not render.available():
        return None

    png = await render.render_png(help_html(model), TEMPLATE.parent)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("help_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
