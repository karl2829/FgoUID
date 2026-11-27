"""FGOUID — FGO 查询插件（GsCore 指令版）"""

import asyncio
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV, Plugins

from .core import aliases as alias_store
from .core import news as news_mod
from .core import search as searcher
from .core.card import render_cards
from .core.ce_card import get_ce_png, load_details_for
from .core.event_card import get_event_png, prewarm_banners as prewarm_event_banners
from .core.gacha_card import get_gacha_png, prewarm_banners
from .core.fun import format_waifu, today_waifu
from .core.help_card import get_help_png
from .core.mystic_card import get_mystic_png
from .core.play import draw, format_draw, format_stats, stats
from .core.settings import (
    all_of,
    format_settings,
    image_on,
    parse_bool,
    parse_quality,
    parse_skill,
    put,
    quality_of,
    scope_of,
    skill_of,
    notice_of,
)


def candidate_text(rows, name: str, limit: int = 8) -> str:
    """重名从者：列候选 + 教用户怎么用职阶/星级精确查。"""
    lines = [f"「{name}」有 {len(rows)} 位，用「职阶 + 名称」区分："]
    for r in rows[:limit]:
        klass = (r["servant_class"] or "").lower()
        cn = CLASS_CN.get(klass, klass)
        stars = "★" * int(r["rarity"] or 0)
        star_n = int(r["rarity"] or 0)
        lines.append(f"· {klass.capitalize()}（{cn}）{stars} → fgo从者 {cn} {star_n}星 {r['name']}")
    if len(rows) > limit:
        lines.append(f"……还有 {len(rows) - limit} 位，加关键词再查")
    lines.append("提示：职阶后面也能加星级，例如 fgo从者 剑 5星 阿尔托莉雅·潘德拉贡")
    return "\n".join(lines)


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
    CLASS_CN,
    find_ce,
    find_ces,
    find_mystic_codes,
    find_servant,
    find_servants,
    format_mystic,
    parse_servant_query,
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
    "fgo<任意词> — 直接查从者/礼装/御主衣服\n"
    "fgo别名 添加 <名称> <叫法> — 自定义别名\n"
    "— 公共信息 —\n"
    "fgo从者 [职阶] <名称> — 从者卡图（重名可加职阶，如 剑 伊吹童子）\n"
    "fgo礼装 <名称> — 概念礼装\n"
    "fgo活动 [关键词] — 活动列表/搜索\n"
    "fgo卡池 [关键词] — 卡池日历/搜索\n"
    "fgo御主衣服 <名称> — 御主衣服技能\n"
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


@sv.on_fullmatch("fgo", block=True)
async def fgo_bare(bot: Bot, ev: Event):
    return await fgo_help(bot, ev)


@sv.on_fullmatch("fgo帮助", block=True)
async def fgo_help(bot: Bot, ev: Event):
    if not image_on(ev):
        return await bot.send(HELP_TEXT)
    # 三级降级：服务器端渲染 → 仓库内预渲染图 → 纯文字
    try:
        png = await get_help_png(quality_of(ev))
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


async def send_servant_card(bot: Bot, ev: Event, row) -> None:
    """发从者卡（多模组多张）；出图关闭或渲染失败时回落文字。"""
    if not image_on(ev):
        return await bot.send(format_servant(row))
    try:
        pngs = await render_cards(row["id"], lang=lang_of(ev), quality=quality_of(ev),
                                  skill=skill_of(ev))
    except Exception as e:
        logger.warning(f"[FGOUID] 从者卡渲染失败，降级文字：{e}")
        pngs = []
    if pngs:
        return await bot.send([MessageSegment.image(p) for p in pngs])
    await bot.send(format_servant(row))


async def send_mystic_card(bot: Bot, ev: Event, row) -> None:
    """御主衣服卡；出图关闭 / 渲染失败时回落文字。"""
    if not image_on(ev):
        return await bot.send(format_mystic(row))
    try:
        png = await asyncio.wait_for(get_mystic_png(row, quality_of(ev)), timeout=40)
    except asyncio.TimeoutError:
        logger.info("[FGOUID] 御主衣服卡首次渲染超时，先发文字版")
        return await bot.send(format_mystic(row) + "\n（首次生成要下图，稍后再发一次就有图了）")
    except Exception as e:
        logger.warning(f"[FGOUID] 御主衣服卡渲染失败，降级文字：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    await bot.send(format_mystic(row))


async def send_ce_card(bot: Bot, ev: Event, row) -> None:
    """发礼装卡；没有卡面数据 / 出图关闭 / 渲染失败时回落文字。"""
    if not image_on(ev):
        return await bot.send(format_ce(row))
    try:
        png = await asyncio.wait_for(
            get_ce_png(dict(row), load_details_for(row), lang_of(ev), quality_of(ev)), timeout=45)
    except asyncio.TimeoutError:
        logger.info("[FGOUID] 礼装卡首次渲染超时，先发文字版")
        return await bot.send(format_ce(row) + "\n（礼装卡首次生成要下图，稍后再发一次就有图了）")
    except Exception as e:
        logger.warning(f"[FGOUID] 礼装卡渲染失败，降级文字：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    await bot.send(format_ce(row))


@sv.on_command("fgo从者", block=True)
async def fgo_servant(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo从者 <名称>，例如 fgo从者 摩根")
    rows = find_servants(name)
    if not rows:
        return await bot.send(f"未找到从者：{name}（可用「职阶 + 名称」区分重名，如 fgo从者 剑 伊吹童子）")
    if len(rows) > 1:
        shown = parse_servant_query(name)[0] or name
        return await bot.send(candidate_text(rows, shown))
    await send_servant_card(bot, ev, rows[0])


@sv.on_command("fgo礼装", block=True)
async def fgo_ce(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo礼装 <名称>，例如 fgo礼装 宝石翁")
    rows = find_ces(name)
    if not rows:
        return await bot.send(f"未找到礼装：{name}")
    if len(rows) > 1:
        lines = [f"「{name}」有 {len(rows)} 张礼装："]
        lines += [f"· {searcher.describe_hit('ce', r)}" for r in rows[:8]]
        lines.append("加关键词再查，或者直接发 fgo<更完整的名称>")
        return await bot.send("\n".join(lines))
    await send_ce_card(bot, ev, rows[0])


@sv.on_command("fgo御主衣服", block=True)
async def fgo_mystic(bot: Bot, ev: Event):
    name = (ev.text or "").strip()
    if not name:
        return await bot.send("用法：fgo御主衣服 <名称>，例如 fgo御主衣服 决战用迦勒底制服")
    rows = find_mystic_codes(name)
    if not rows:
        return await bot.send(f"未找到御主衣服：{name}")
    if len(rows) > 1:
        lines = [f"「{name}」有 {len(rows)} 件御主衣服："]
        lines += [f"· {searcher.describe_hit('mystic', r)}" for r in rows[:8]]
        lines.append("加关键词再查，或者直接发 fgo<更完整的名称>")
        return await bot.send("\n".join(lines))
    await send_mystic_card(bot, ev, rows[0])


@sv.on_command("fgo活动", block=True)
async def fgo_event(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    if not kw:                       # 不带词 = 日历（活动 + 维护），不再单独出一张列表卡
        return await fgo_calendar(bot, ev)
    rows = search_events(kw)
    if not image_on(ev):
        return await bot.send(format_events(rows))
    try:
        png = await asyncio.wait_for(get_event_png(rows, kw, quality_of(ev)), timeout=25)
    except asyncio.TimeoutError:
        logger.info("[FGOUID] 活动卡首次渲染超时，先发文字版")
        return await bot.send(format_events(rows) + "\n（活动卡首次生成要下图，稍后再发一次就有图了）")
    except Exception as e:
        logger.warning(f"[FGOUID] 活动卡渲染失败，降级文字：{e}")
        png = None
    if png:
        return await bot.send(MessageSegment.image(png))
    await bot.send(format_events(rows))


@sv.on_command("fgo卡池", block=True)
async def fgo_gacha(bot: Bot, ev: Event):
    kw = (ev.text or "").strip()
    rows = list_gacha(kw)
    if not kw:
        # 不带关键词时优先用官网公告（数据更及时，横幅也是官网原图）
        try:
            from .core.gacha_card import rows_from_news

            news_rows = await asyncio.to_thread(news_mod.gacha_rows, 20)
            live = rows_from_news(news_rows)
            if len(live) >= 2:
                rows = live
        except Exception as e:
            logger.warning(f"[FGOUID] 官网卡池取数失败，回落 wiki 快照：{e}")
    if not image_on(ev):
        return await bot.send(format_gacha(rows))
    try:
        # 首屏要下横幅（~150KB/张），给个上限，超时先发文字，缓存会留给下一次
        from .core.gacha_card import get_gacha_timeline_png

        png = await asyncio.wait_for(
            get_gacha_timeline_png(rows, kw, quality_of(ev)), timeout=25)
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
        pngs = await render_cards(pick["id"], lang=lang_of(ev), quality=quality_of(ev),
                                  skill=skill_of(ev))
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
        pngs = await render_cards(res["servant_id"], lang=lang_of(ev), quality=quality_of(ev),
                                  skill=skill_of(ev))
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


@sv.on_command("fgo设置画质", block=True)
async def fgo_set_quality(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    val = parse_quality(arg)
    if val is None:
        return await bot.send("用法：fgo设置画质 高清 / 标准 / 省流\n"
                              "高清（PNG 1.3MB）· 标准（WebP 360KB）· 省流（小图 WebP 200KB）")
    put(scope_of(ev), "quality", val)
    tip = {"hd": "高清：PNG，最清晰", "std": "标准：WebP，体积约 1/3.6，手机上看不出差别",
           "lite": "省流：分辨率降到 1.5 倍，体积约 1/6"}[val]
    await bot.send(f"画质已切换为{tip} ✅")


@sv.on_command("fgo设置技能", block=True)
async def fgo_set_skill(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    val = parse_skill(arg)
    if val is None:
        return await bot.send("用法：fgo设置技能 精简 / 完整\n"
                              "精简＝只显示 Lv.1/6/10 三格（默认，卡矮约 25%）· 完整＝十级全列")
    put(scope_of(ev), "skill", val)
    tip = "精简：只显示技能本断点 Lv.1/6/10" if val == "compact" else "完整：显示 Lv.1–10 全部数值"
    await bot.send(f"技能数值已切换为{tip} ✅")


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
        await prewarm_banners(12)
    except Exception as e:
        logger.debug(f"[FGOUID] 卡池横幅预热跳过：{e}")
    try:
        await prewarm_event_banners(6)
    except Exception as e:
        logger.debug(f"[FGOUID] 活动横幅预热跳过：{e}")


try:
    from gsuid_core.server import on_core_start

    @on_core_start(priority=30)
    async def _fgouid_core_start() -> None:
        asyncio.create_task(_startup_prewarm())
        asyncio.create_task(_notice_loop())
except Exception as e:  # 老版本 core 没有这个钩子就跳过
    logger.debug(f"[FGOUID] on_core_start 不可用：{e}")


# ---------------------------------------------------------------- 别名 / 统一检索
TYPE_WORDS = {
    "从者": "servant", "servant": "servant",
    "礼装": "ce", "ce": "ce", "概念礼装": "ce",
    "御主衣服": "mystic", "mystic": "mystic", "魔术礼装": "mystic", "衣服": "mystic",
}

# 「fgo<词>」这种裸查询要避开的内置指令，否则会跟专门的命令抢
KNOWN_SUBCOMMANDS = (
    "从者", "礼装", "活动", "卡池", "御主衣服", "测试", "帮助", "今日老婆", "老婆",
    "每日一抽", "一抽", "抽卡", "图鉴", "下载资源", "设置", "别名",
)


def _entity_rows(etype: str, rows) -> str:
    """跨类型/多候选时列候选。"""
    lines = []
    for etype_one, rows_one in rows:
        for r in rows_one[:5]:
            lines.append(f"· {searcher.describe_hit(etype_one, r)} → {searcher.hint_for(etype_one, r)}")
        if len(rows_one) > 5:
            lines.append(f"  （{searcher.TYPE_CN.get(etype_one, etype_one)}还有 {len(rows_one) - 5} 条，加关键词再查）")
    return "\n".join(lines)


async def _reply_matches(bot: Bot, ev: Event, query: str, matches) -> None:
    if len(matches) == 1:
        etype, rows = matches[0]
        if etype == "servant":
            if len(rows) > 1:
                shown = parse_servant_query(query)[0] or query
                return await bot.send(candidate_text(rows, shown))
            return await send_servant_card(bot, ev, rows[0])
        if etype == "ce":
            if len(rows) > 1:
                lines = [f"「{query}」有 {len(rows)} 张礼装："]
                lines += [f"· {searcher.describe_hit('ce', r)} → {searcher.hint_for('ce', r)}" for r in rows[:8]]
                return await bot.send("\n".join(lines))
            return await send_ce_card(bot, ev, rows[0])
        if len(rows) > 1:
            lines = [f"「{query}」有 {len(rows)} 件御主衣服："]
            lines += [f"· {searcher.describe_hit('mystic', r)} → {searcher.hint_for('mystic', r)}" for r in rows[:8]]
            return await bot.send("\n".join(lines))
        return await send_mystic_card(bot, ev, rows[0])

    total = sum(len(r) for _, r in matches)
    types = "、".join(searcher.TYPE_CN.get(t, t) for t, _ in matches)
    head = f"「{query}」匹配到 {total} 条（{types}），用指令收窄："
    await bot.send(head + "\n" + _entity_rows("", matches))


@sv.on_prefix("fgo", block=False)
async def fgo_any(bot: Bot, ev: Event):
    """fgo<任意词>：从者（含用户别名）/ 礼装 / 御主衣服 统一检索。

    内置指令（fgo从者、fgo活动…）有各自的 handler，这里遇到就跳过，
    避免同一条消息被回两遍。
    """
    text = (ev.text or "").strip()
    if not text or text.startswith(KNOWN_SUBCOMMANDS):
        return
    # 去掉可能残留的空格/标点
    query = text.strip(" 　·・,，。")
    if not query:
        return
    matches = searcher.resolve(query, scope_of(ev))
    if not matches:
        return await bot.send(
            f"没找到「{query}」\n"
            "· 查从者：fgo从者 <名称>　· 查礼装：fgo礼装 <名称>　· 查御主衣服：fgo御主衣服 <名称>\n"
            "· 想给它起个短名：fgo别名 添加 <名称> <你的叫法>"
        )
    await _reply_matches(bot, ev, query, matches)


@sv.on_command("fgo别名", block=True)
async def fgo_alias(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    scope = scope_of(ev)
    if not arg or arg in ("列表", "list", "ls"):
        return await bot.send(alias_store.describe(alias_store.list_of(scope)))

    parts = arg.split()
    action = parts[0]
    rest = parts[1:]

    if action in ("添加", "add", "加"):
        if len(rest) < 2:
            return await bot.send(
                "用法：fgo别名 添加 <名称> <你的叫法>\n"
                "例：fgo别名 添加 摩根 老婆\n"
                "重名时先在前面写类型：fgo别名 添加 礼装 万华镜 宝石爷"
            )
        etype = None
        if rest[0] in TYPE_WORDS and len(rest) >= 3:
            etype = TYPE_WORDS[rest[0]]
            rest = rest[1:]
        alias = rest[-1]
        target = " ".join(rest[:-1]).strip()

        matches = searcher.resolve(target, scope)
        if etype:
            matches = [(t, rows) for t, rows in matches if t == etype]
        if not matches:
            return await bot.send(f"没找到「{target}」，先在前面加上类型试试（从者/礼装/御主衣服）")
        total = sum(len(rows) for _, rows in matches)
        if total > 1:
            lines = [f"「{target}」有 {total} 个候选，请写清楚是哪一个（可在前面加类型）："]
            lines += [f"· {searcher.describe_hit(t, r)}" for t, rows in matches for r in rows[:5]]
            return await bot.send("\n".join(lines))

        etype_one, rows_one = matches[0]
        row = rows_one[0]
        name = searcher.entity_name(etype_one, row)
        eid = str(row["id"])
        status = alias_store.add(scope, alias, etype_one, eid, name, by=ev.user_id)
        if status == "reserved":
            return await bot.send(f"「{alias}」是内置指令词，换一个吧")
        if status == "bad":
            return await bot.send("别名不能为空，且不超过 20 个字")
        if status == "exists":
            return await bot.send(f"「{alias}」已经指向 {searcher.TYPE_CN[etype_one]}「{name}」了")
        if status == "conflict":
            return await bot.send(
                f"「{alias}」已经被别的条目占用了，先发「fgo别名 删除 {alias}」再添加"
            )
        where = "本群" if scope.startswith("g:") else "你"
        return await bot.send(
            f"已记住：{where}发「{alias}」= {searcher.TYPE_CN[etype_one]}「{name}」✅\n"
            f"以后直接发 fgo{alias} 就行"
        )

    if action in ("删除", "del", "删", "移除"):
        if not rest:
            return await bot.send("用法：fgo别名 删除 <你的叫法>")
        removed = alias_store.remove(scope, rest[0])
        if not removed:
            return await bot.send(f"没找到别名「{rest[0]}」")
        return await bot.send(f"已删除别名「{removed['alias']}」")

    return await bot.send(
        "别名用法：\n"
        "· fgo别名 添加 <名称> <你的叫法>\n"
        "· fgo别名 删除 <你的叫法>\n"
        "· fgo别名 — 看当前有哪些别名"
    )


# ---------------------------------------------------------------- 官网公告 / 日历
NOTICE_TASK = "FGO维护公告"
NOTICE_HOURS = range(8, 23)          # 白天 8-23 点之间每小时扫一次


async def _notice_push_once() -> int:
    """扫一次官网：入库 + 推未发过的维护公告。返回推送条数。"""
    try:
        from gsuid_core.subscribe import gs_subscribe
    except Exception as e:
        logger.warning(f"[FGOUID] 公告订阅不可用：{e}")
        return 0

    subs = await gs_subscribe.get_subscribe(NOTICE_TASK)
    if not subs:
        return 0

    res = await asyncio.to_thread(news_mod.sync, 3)
    pending = news_mod.pending_maintenance()
    if not pending:
        return 0

    sent = 0
    delivered: list[str] = []
    for item in pending:
        when = item.get("start_at") or (item.get("ctime") or "")[:10]
        png = None
        try:
            from .core.news_card import get_news_png

            png = await asyncio.wait_for(get_news_png(item, "std"), timeout=25)
        except Exception as e:
            logger.warning(f"[FGOUID] 公告卡渲染失败，改发文字：{e}")
        caption = f"【FGO 维护公告】{item['title']}" + (f"\n维护日：{when}" if when else "")
        ok = False
        for sub in subs:
            try:
                if png:                       # 正常只发图，文字说明没人看
                    ret = await sub.send(MessageSegment.image(png))
                else:                         # 出图失败才退化成一句话
                    ret = await sub.send(caption)
                if ret == -1:                    # 机器人不在线，Subscribe.send 返回 -1
                    logger.warning(f"[FGOUID] 推送失败：bot {sub.bot_id} 未连接（组 {sub.group_id}）")
                    continue
                sent += 1
                ok = True
            except Exception as e:
                logger.warning(f"[FGOUID] 公告推送失败：{e}")
        if ok:
            delivered.append(item["id"])
        else:
            logger.warning(f"[FGOUID] 公告「{item['title'][:20]}」未送达任何订阅，下个小时重试")

    news_mod.mark_pushed(delivered)
    logger.info(f"[FGOUID] 维护公告已推送 {len(pending)} 条 → {len(subs)} 个订阅")
    return sent


async def _notice_loop() -> None:
    """每小时检查；白天窗口内才真正抓取。"""
    while True:
        try:
            now = datetime.now()
            if now.hour in NOTICE_HOURS:
                await _notice_push_once()
            # 睡到下一个整点
            nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            await asyncio.sleep(max(60, (nxt - datetime.now()).total_seconds()))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[FGOUID] 公告循环异常：{e}")
            await asyncio.sleep(600)


def _fmt_span(item: dict) -> str:
    start = item.get("start_at") or ""
    end = item.get("end_at") or ""
    if start and end:
        return f"{start[5:]} ~ {end[5:]}"
    if start:
        return f"{start[5:]} 起"
    return "时间待定"


def calendar_text(limit: int = 12) -> str:
    items = [i for i in news_mod.calendar(limit) if i.get("start_at")]
    if not items:
        return "日历还是空的：还没有抓到带时间的活动公告（官网公告每小时同步一次）"
    today = date.today().isoformat()
    lines = [f"【FGO 日历】进行中 / 即将开始（{len(items)} 项）"]
    for it in items:
        tag = "进行中" if (it["start_at"] <= today and (not it["end_at"] or it["end_at"] >= today)) else "即将"
        if it["start_at"] > today:
            tag = "即将"
        title = re.sub(r"[「」『』【】]", "", it["title"]).strip("！! ").strip()
        title = re.sub(r"^(限时|预告|公告)", "", title).strip()
        lines.append(f"· {_fmt_span(it)} ｜{tag}｜ {title[:38]}")
    extra = news_mod.dateless_count()
    if extra:
        lines.append(f"（另有 {extra} 条活动公告没标注时间，未列入）")
    lines.append("数据来自 FGO 官网公告，过期条目自动清理")
    return "\n".join(lines)


@sv.on_fullmatch(("fgo日历", "fgo活动日历"), block=True)
async def fgo_calendar(bot: Bot, ev: Event):
    try:
        if not news_mod.timeline(1):                  # 库空就先抓一次
            await asyncio.to_thread(news_mod.sync, 4)
    except Exception as e:
        logger.warning(f"[FGOUID] 日历首次抓取失败：{e}")

    if image_on(ev):
        try:
            from .core.calendar_card import get_calendar_png

            png = await asyncio.wait_for(
                get_calendar_png(news_mod.timeline(), quality_of(ev)), timeout=40)
            if png:
                return await bot.send(MessageSegment.image(png))
        except Exception as e:
            logger.warning(f"[FGOUID] 日历卡渲染失败，改发文字：{e}")
    await bot.send(calendar_text())


@sv.on_fullmatch(("fgo公告测试", "fgo推送测试"), block=True)
async def fgo_notice_test(bot: Bot, ev: Event):
    """把最近一条维护公告发到当前会话，用来确认推送链路。"""
    try:
        await asyncio.to_thread(news_mod.sync, 1)
    except Exception as e:
        logger.warning(f"[FGOUID] 公告测试同步失败：{e}")
    rows = news_mod.pending_maintenance(within_days=60)
    if not rows:
        con = news_mod._conn()
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM news WHERE kind='维护' ORDER BY ctime DESC LIMIT 1").fetchall()]
        con.close()
    if not rows:
        return await bot.send("还没抓到维护公告，稍后再试")
    item = rows[0]
    try:
        from .core.news_card import get_news_png

        png = await asyncio.wait_for(get_news_png(item, "std"), timeout=25)
        if png:
            return await bot.send(MessageSegment.image(png))
    except Exception as e:
        logger.warning(f"[FGOUID] 公告测试出图失败：{e}")
    await bot.send(f"【FGO 维护公告】{item['title']}\n维护日：{item.get('start_at', '')}")


@sv.on_command("fgo设置公告", block=True)
async def fgo_set_notice(bot: Bot, ev: Event):
    arg = (ev.text or "").strip()
    sub_type = "session" if getattr(ev, "user_type", "") == "group" else "single"
    if arg in ("开", "开启", "on", "1"):
        put(scope_of(ev), "notice", True)
        try:
            from gsuid_core.subscribe import gs_subscribe

            await gs_subscribe.add_subscribe(sub_type, NOTICE_TASK, ev)
        except Exception as e:
            logger.warning(f"[FGOUID] 订阅写入失败：{e}")
        return await bot.send("已订阅官网维护公告 ✅\n8-23 点每小时扫一次，只推维护，其他人发的活动公告不进推送")
    if arg in ("关", "关闭", "off", "0"):
        put(scope_of(ev), "notice", False)
        try:
            from gsuid_core.subscribe import gs_subscribe

            await gs_subscribe.delete_subscribe(sub_type, NOTICE_TASK, ev)
        except Exception as e:
            logger.warning(f"[FGOUID] 订阅删除失败：{e}")
        return await bot.send("已关闭维护公告推送 ✅")
    return await bot.send("用法：fgo设置公告 开 / 关")
