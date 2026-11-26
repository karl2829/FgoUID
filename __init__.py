"""FGOUID — FGO 查询插件（GsCore 指令版）"""

import asyncio
from pathlib import Path

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV, Plugins

from .core.card import render_cards
from .core.ce_card import get_ce_png, load_details_for
from .core.gacha_card import get_gacha_png, prewarm_banners
from .core.fun import format_waifu, today_waifu
from .core.help_card import get_help_png
from .core.play import draw, format_draw, format_stats, stats
from .core.settings import (
    all_of,
    format_settings,
    image_on,
    parse_bool,
    put,
    scope_of,
)


def lang_of(ev: Event) -> str:
    """当前会话的显示语言（zh / jp）。"""
    return str(all_of(scope_of(ev)).get("lang") or "zh")
from .core.prewarm import (
    DEFAULT_BATCH,
    MAX_BATCH,
    format_status,
    run as prewarm_run,
    status as prewarm_status,
)

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
    "fgo每日一抽 — 今天的一抽（出货记进图鉴）\n"
    "fgo图鉴 — 收集进度\n"
    "— 设置 —\n"
    "fgo设置 — 看当前配置\n"
    "fgo设置出图 开/关 — 只发文字 / 发卡片图\n"
    "fgo下载资源 [数量] — 后台预热素材\n"
    "— 其他 —\n"
    "fgo测试 — 链路自检\n"
    "fgo帮助 — 本帮助"
)


@sv.on_fullmatch("fgo测试", block=True)
async def fgo_ping(bot: Bot, ev: Event):
    await bot.send("FGOUID 插件链路正常 ✅")


@sv.on_fullmatch("fgo帮助", block=True)
async def fgo_help(bot: Bot, ev: Event):
    if not image_on(ev):
        return await bot.send(HELP_TEXT)
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
    if not image_on(ev):
        return await bot.send(format_servant(row))
    # 有卡片数据就发主题卡图（多宝具从者按模组各发一张）；没有/渲染失败则退回文字
    try:
        pngs = await render_cards(row["id"], lang=lang_of(ev))
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
    if not image_on(ev):
        return await bot.send(format_ce(row))
    try:
        png = await asyncio.wait_for(
            get_ce_png(dict(row), load_details_for(row), lang_of(ev)), timeout=45)
    except asyncio.TimeoutError:
        logger.info("[FGOUID] 礼装卡首次渲染超时，先发文字版")
        return await bot.send(format_ce(row) + "\n（礼装卡首次生成要下图，稍后再发一次就有图了）")
    except Exception as e:
        logger.warning(f"[FGOUID] 礼装卡渲染失败，降级文字：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    await bot.send(format_ce(row))


@sv.on_command("fgo活动", block=True)
async def fgo_event(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    await bot.send(format_events(search_events(kw)))


@sv.on_command("fgo卡池", block=True)
async def fgo_gacha(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    rows = list_gacha(kw)
    if not image_on(ev):
        return await bot.send(format_gacha(rows))
    try:
        # 首屏要下横幅（~150KB/张），给个上限，超时先发文字，缓存会留给下一次
        png = await asyncio.wait_for(get_gacha_png(rows, kw), timeout=25)
    except asyncio.TimeoutError:
        logger.info("[FGOUID] 卡池卡首次渲染超时，先发文字版")
        return await bot.send(format_gacha(rows) + "\n（卡池卡首次生成要下图，稍后再发一次就有图了）")
    except Exception as e:
        logger.warning(f"[FGOUID] 卡池卡渲染失败，降级文字：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    await bot.send(format_gacha(rows))


@sv.on_fullmatch(("fgo今日老婆", "今日老婆", "fgo老婆"), block=True)
async def fgo_waifu(bot: Bot, ev: Event):
    pick = today_waifu(ev.user_id)
    if pick is None:
        return await bot.send("数据还没同步好，稍后再试")
    if not image_on(ev):
        return await bot.send(format_waifu(pick))
    try:
        pngs = await render_cards(pick["id"], lang=lang_of(ev))
    except Exception as e:
        logger.warning(f"[FGOUID] 今日老婆卡渲染失败，降级文字：{e}")
        pngs = []
    if pngs:
        return await bot.send([MessageSegment.image(p) for p in pngs])
    await bot.send(format_waifu(pick))


@sv.on_fullmatch(("fgo每日一抽", "每日一抽", "fgo一抽"), block=True)
async def fgo_daily_draw(bot: Bot, ev: Event):
    try:
        res = draw(ev.user_id)
    except Exception as e:
        logger.warning(f"[FGOUID] 每日一抽读写失败：{e}")
        return await bot.send("抽卡记录暂时读写不了，稍后再试")
    if res is None:
        return await bot.send("数据还没同步好，稍后再试")
    await bot.send(format_draw(res))
    if not image_on(ev):
        return
    try:
        pngs = await render_cards(res["servant_id"], lang=lang_of(ev))
    except Exception as e:
        logger.warning(f"[FGOUID] 每日一抽卡图渲染失败，只发文字：{e}")
        pngs = []
    if pngs:
        await bot.send([MessageSegment.image(p) for p in pngs])


@sv.on_fullmatch("fgo设置", block=True)
async def fgo_settings(bot: Bot, ev: Event):
    await bot.send(format_settings(ev))


@sv.on_command("fgo设置出图", block=True)
async def fgo_set_image(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    val = parse_bool(arg)
    if val is None:
        return await bot.send("用法：fgo设置出图 开 / 关（关掉后从者、礼装、卡池都只发文字）")
    put(scope_of(ev), "image", val)
    await bot.send("出图已" + ("开启 ✅ 之后会发卡片图" if val else "关闭 ✅ 之后只发文字"))


@sv.on_command("fgo设置语言", block=True)
async def fgo_set_lang(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    if arg in ("中", "中文", "zh"):
        want = "zh"
    elif arg in ("日", "日文", "jp", "ja"):
        want = "jp"
    else:
        return await bot.send("用法：fgo设置语言 中 / 日")
    cur = all_of(scope_of(ev))
    if want == cur.get("lang"):
        return await bot.send(f"语言已经是{'中文' if want == 'zh' else '日文'}了")
    put(scope_of(ev), "lang", want)
    if want == "jp":
        await bot.send("语言已切换为日文 ✅ 从者卡/礼装卡的名称改成日文主显、中文小字（帮助卡与卡池仍中文）")
    else:
        await bot.send("语言已切换为中文 ✅")


@sv.on_fullmatch(("fgo图鉴", "从者图鉴"), block=True)
async def fgo_collection(bot: Bot, ev: Event):
    await bot.send(format_stats(stats(ev.user_id)))


# 后台任务要留引用，否则可能被 GC 掉
_bg_tasks: set[asyncio.Task] = set()


async def _prewarm_then_report(bot: Bot, limit: int) -> None:
    try:
        r = await prewarm_run(limit)
    except Exception as e:
        logger.warning(f"[FGOUID] 素材预热中断：{e}")
        try:
            await bot.send(f"素材预热中断：{e}")
        except Exception:
            pass
        return
    st = r["status"]
    msg = f"素材预热完成：本批 {r['ok']}/{r['asked']} 张"
    if r["failed"]:
        msg += f"（{r['failed']} 张没下来，下次会重试）"
    msg += f"\n总进度 {st['done']}/{st['total']}"
    try:
        await bot.send(msg)
    except Exception as e:
        logger.debug(f"[FGOUID] 预热完成消息发送失败：{e}")


@sv.on_command("fgo下载资源", block=True)
async def fgo_prewarm(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    if arg in ("全部", "all"):
        limit = MAX_BATCH
    elif arg.isdigit():
        limit = max(1, min(int(arg), MAX_BATCH))
    else:
        limit = DEFAULT_BATCH
    st = prewarm_status()
    if st["pending"] <= 0:
        return await bot.send(f"素材已经全部预热完了（{st['total']} 张），直接查就行")
    n = min(limit, st["pending"])
    task = asyncio.create_task(_prewarm_then_report(bot, limit))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    await bot.send(
        f"开始后台预热 {n} 张素材（全量 {st['total']}，已完成 {st['done']}）\n"
        "下载期间查图会更快，完事我再报一次"
    )


# 启动时静默预热接下来几期的卡池横幅：首图慢主要慢在下这 150KB/张的图
async def _startup_prewarm() -> None:
    try:
        n = await prewarm_banners(12)
        logger.debug(f"[FGOUID] 卡池横幅预热 {n} 张")
    except Exception as e:
        logger.debug(f"[FGOUID] 卡池横幅预热跳过：{e}")


try:
    from gsuid_core.server import on_core_start

    @on_core_start(priority=30)
    async def _fgouid_core_start() -> None:
        asyncio.create_task(_startup_prewarm())
except Exception as e:  # 老版本 core 没有这个钩子就跳过
    logger.debug(f"[FGOUID] on_core_start 不可用：{e}")
