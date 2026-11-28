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

# 四块结构（改命令就改这里，HTML 与将来的 PIL 共用）
SECTION_WIKI = {
    "title": "公共信息",
    "en": "W I K I",
    "kind": "rows",
    "rows": [
        {"k": "fgo&lt;任意词&gt;", "d": "直接查：从者（含你的自定义别名）／礼装／御主衣服",
         "e": "fgo 宝石翁"},
        {"k": "fgo从者 [职阶] &lt;名称&gt;", "d": "从者卡图：立绘、六维、宝具、技能；重名加职阶区分",
         "e": "fgo从者 剑 伊吹童子"},
        {"k": "fgo礼装 &lt;名称&gt;", "d": "礼装卡：卡面、星级、COST、未破/满破效果",
         "e": "fgo礼装 宝石翁"},
        {"k": "fgo御主衣服 &lt;名称&gt;", "d": "御主衣服卡：衣服图、技能词条与逐级数值、说明",
         "e": "fgo御主衣服 决战用迦勒底制服"},
        {"k": "fgo别名 添加", "d": "格式：添加 &lt;名称&gt; &lt;叫法&gt;；之后 fgo&lt;叫法&gt; 直接命中",
         "e": "fgo别名 添加 摩根 老婆"},
        {"k": "fgo活动 [词]", "d": "不带词=日历（活动+维护）；带词按名称搜历史活动",
         "e": "fgo活动 特异点"},
        {"k": "fgo卡池 [词]", "d": "不带词=官网在开的卡池时间轴；带词搜历史卡池",
         "e": "fgo卡池 摩根"},
        {"k": "fgo日历", "d": "官网公告里的当前／未来活动，按时间轴排；过期自动清",
         "e": "fgo日历"},
    ],
}

SECTION_ACCOUNT = {
    "title": "个人数据",
    "en": "A C C O U N T",
    "kind": "grid",
    "items": [
        {"k": "fgo登录", "d": "私聊发我，用 B站App 扫码授权（2 分钟有效）", "on": True},
        {"k": "fgo档案", "d": "御主档案：资源、图鉴职阶分布、主助战编成", "on": True},
        {"k": "fgo抽卡记录", "d": "当年五星记录：欧非评级、出货率、卡池抽数", "on": True},
        {"k": "fgo全部抽卡记录", "d": "全部五星 + 历史抽数最高的 10 个卡池", "on": True},
        {"k": "fgo登出", "d": "解绑账号并删除本地数据", "on": True},
    ],
}

SECTION_FUN = {
    "title": "趣味互动",
    "en": "F U N",
    "kind": "grid",
    "cols": 2,
    "items": [
        {"k": "fgo今日老婆", "d": "每天换一位，按你的 ID + 日期定种子", "on": True},
        {"k": "fgo每日一抽", "d": "每天一抽，出货记进图鉴；同一天重发不刷新运气", "on": True},
        {"k": "fgo图鉴", "d": "看自己收集了多少从者：星级分布与最近几抽", "on": True},
        {"k": "fgo年终总结", "d": "一年抽了多少、养了谁（需绑定账号）", "on": False},
    ],
}

SECTION_SETTINGS = {
    "title": "设置",
    "en": "S E T T I N G S",
    "kind": "grid",
    "items": [
        {"k": "fgo设置", "d": "看当前配置；出图 开/关 当场生效", "on": True},
        {"k": "fgo设置语言 中/日", "d": "从者卡/礼装卡名称语言：日文名主显或中文主显", "on": True},
        {"k": "fgo设置画质 高清/标准/省流", "d": "图大小：PNG 1.3MB ／ WebP 360KB ／ 小图 200KB", "on": True},
        {"k": "fgo设置技能 完整/精简", "d": "技能数值：十级全列 ／ 只显示 Lv.1·6·10（默认精简）", "on": True},
        {"k": "fgo设置公告 开/关", "d": "订阅官网维护公告，8-23 点每小时扫一次，只推维护",
         "on": True},
        {"k": "fgo下载资源", "d": "后台预热立绘/图标，减少首次出图等待", "on": True},
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
            SECTION_WIKI,
            SECTION_ACCOUNT,
            SECTION_FUN,
            SECTION_SETTINGS,
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
                    {"mark": "◇", "hl": False,
                     "html": "每日一抽 / 今日老婆按「账号 + 日期」定种子：同一天结果固定，次日自动换"},
                ],
            },
        ],
        "footer": FOOTER,
    }


# ---------------------------------------------------------------- HTML 投影

def _sec_head(title: str, en: str, status: str = "") -> str:
    tag = f'<span class="wip">{status}</span>' if status else ""
    return (
        '<div class="sec-h"><div class="bar"></div>'
        f'<div class="t">{title}</div>{tag}<div class="line"></div><div class="n">{en}</div></div>'
    )


def _grid_html(items: list[dict], cols: int = 3) -> str:
    """三列卡片：可用项金框实线，未开放项虚线灰字。"""
    out = []
    for i in range(0, len(items), cols):
        cells = "".join(
            '<div class="gi%s"><div class="gk">%s</div><div class="gd">%s</div>'
            '<div class="go">%s</div></div>'
            % (" on" if it.get("on") else "", it["k"], it["d"],
               "可　用" if it.get("on") else "施 工 中")
            for it in items[i:i + cols]
        )
        out.append(f'<div class="grid">{cells}</div>')
    return "".join(out)


def _section_html(sec: dict) -> str:
    kind = sec["kind"]
    head = _sec_head(sec["title"], sec["en"], sec.get("status", ""))
    if kind == "grid":
        return head + _grid_html(sec["items"], cols=sec.get("cols", 3))
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


def _cache_key(model: dict, quality: str = "hd") -> str:
    blob = (json.dumps(model, ensure_ascii=False, sort_keys=True) + quality
            + TEMPLATE.read_text(encoding="utf-8"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def get_help_png(quality: str = "hd") -> bytes | None:
    """返回帮助图 bytes；pytakumi 不可用或渲染失败时返回 None（调用方降级）。"""
    model = help_model()
    key = _cache_key(model, quality)
    path = cache_dir() / f"help_{key}.img"
    if path.is_file():
        return path.read_bytes()
    if not render.available():
        return None

    png = await render.render_png(help_html(model), TEMPLATE.parent, quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob("help_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
