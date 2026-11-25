"""FGOUID — FGO 查询插件（GsCore 指令版，纯文字）"""

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV, Plugins

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


@sv.on_fullmatch("fgo测试", block=True)
async def fgo_ping(bot: Bot, ev: Event):
    await bot.send("FGOUID 插件链路正常 ✅")


@sv.on_fullmatch("fgo帮助", block=True)
async def fgo_help(bot: Bot, ev: Event):
    await bot.send(
        "【FGO 插件】\n"
        "fgo从者 <名称> — 从者信息\n"
        "fgo礼装 <名称> — 概念礼装\n"
        "fgo活动 [关键词] — 活动列表/搜索\n"
        "fgo卡池 [关键词] — 卡池日历/搜索\n"
        "fgo测试 — 链路自检\n"
        "fgo帮助 — 本帮助"
    )


@sv.on_command("fgo从者", block=True)
async def fgo_servant(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo从者 <名称>，例如 fgo从者 摩根")
    row = find_servant(name)
    if row is None:
        return await bot.send(f"未找到从者：{name}")
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
