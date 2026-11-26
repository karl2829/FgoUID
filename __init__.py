"""FGOUID — FGO 查询插件（GsCore 指令版）"""

from pathlib import Path

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV, Plugins

from .core.card import render_cards
from .core.fun import format_waifu, today_waifu
from .core.help_card import get_help_png

from .core.db import (
    find_ce,
    find_servant,
    format_ce,
    format_events,
    format_gacha,
    format_servant,
    list_gacha,
    search_events,
)

Plugins(name="FGOUID", alias=["fgo"])

sv = SV("FGO查询")

# 预渲染兜底图：pytakumi 不可用 / 渲染失败时发这个（构建期生成，随仓库分发）
HELP_IMG = Path(__file__).resolve().parent / "assets" / "help.png"

HELP_TEXT = (
    "【FGO 插件】\n"
    "— 公共信息 —\n"
    "fgo从者 <名称> — 从者卡图\n"
    "fgo礼装 <名称> — 概念礼装\n"
    "fgo活动 [关键词] — 活动列表/搜索\n"
    "fgo卡池 [关键词] — 卡池日历/搜索\n"
    "— 趣味互动 —\n"
    "fgo今日老婆 — 今天的老婆\n"
    "— 其他 —\n"
    "fgo测试 — 链路自检\n"
    "fgo帮助 — 本帮助"
)


@sv.on_fullmatch("fgo测试", block=True)
async def fgo_ping(bot: Bot, ev: Event):
    await bot.send("FGOUID 插件链路正常 ✅")


@sv.on_fullmatch("fgo帮助", block=True)
async def fgo_help(bot: Bot, ev: Event):
    # 三级降级：服务器端渲染 → 仓库内预渲染图 → 纯文字
    try:
        png = await get_help_png()
    except Exception as e:
        logger.warning(f"[FGOUID] 帮助图渲染失败，降级：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    if HELP_IMG.is_file():
        return await bot.send(MessageSegment.image(HELP_IMG))
    await bot.send(HELP_TEXT)


# 让 FGOUID 出现在 core帮助 的「插件帮助一览」里
try:
    from PIL import Image

    from gsuid_core.help.utils import register_help

    _emblem = Path(__file__).resolve().parent / "assets" / "emblem.png"
    register_help(
        "FGOUID",
        "fgo帮助",
        Image.open(_emblem) if _emblem.is_file() else None,
    )
except Exception as e:  # 老版本 core 没有 register_help 时静默跳过
    logger.debug(f"[FGOUID] register_help 跳过：{e}")


@sv.on_command("fgo从者", block=True)
async def fgo_servant(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo从者 <名称>，例如 fgo从者 摩根")
    row = find_servant(name)
    if row is None:
        return await bot.send(f"未找到从者：{name}")
    # 有卡片数据就发主题卡图（多宝具从者按模组各发一张）；没有/渲染失败则退回文字
    try:
        pngs = await render_cards(row["id"])
    except Exception as e:
        logger.warning(f"[FGOUID] 从者卡渲染失败，降级文字：{e}")
        pngs = []
    if pngs:
        return await bot.send([MessageSegment.image(p) for p in pngs])
    await bot.send(format_servant(row))


@sv.on_command("fgo礼装", block=True)
async def fgo_ce(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo礼装 <名称>，例如 fgo礼装 宝石翁")
    row = find_ce(name)
    if row is None:
        return await bot.send(f"未找到礼装：{name}")
    await bot.send(format_ce(row))


@sv.on_command("fgo活动", block=True)
async def fgo_event(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    await bot.send(format_events(search_events(kw)))


@sv.on_command("fgo卡池", block=True)
async def fgo_gacha(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    await bot.send(format_gacha(list_gacha(kw)))


@sv.on_fullmatch(("fgo今日老婆", "今日老婆", "fgo老婆"), block=True)
async def fgo_waifu(bot: Bot, ev: Event):
    pick = today_waifu(ev.user_id)
    if pick is None:
        return await bot.send("数据还没同步好，稍后再试")
    try:
        pngs = await render_cards(pick["id"])
    except Exception as e:
        logger.warning(f"[FGOUID] 今日老婆卡渲染失败，降级文字：{e}")
        pngs = []
    if pngs:
        return await bot.send([MessageSegment.image(p) for p in pngs])
    await bot.send(format_waifu(pick))
