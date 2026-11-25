"""FGOUID — FGO 查询插件（GsCore 指令版）"""

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV, Plugins

from .core.db import find_servant, format_servant

Plugins(name="FGOUID", alias=["fgo"])

sv = SV("FGO查询")


@sv.on_fullmatch("fgo测试", block=True)
async def fgo_ping(bot: Bot, ev: Event):
    await bot.send("FGOUID 插件链路正常 ✅")


@sv.on_fullmatch("fgo帮助", block=True)
async def fgo_help(bot: Bot, ev: Event):
    await bot.send(
        "【FGO 插件】\n"
        "fgo从者 <名称> — 查询从者\n"
        "fgo测试 — 链路自检\n"
        "fgo帮助 — 本帮助\n"
        "（更多命令开发中）"
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
