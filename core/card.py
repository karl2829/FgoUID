# -*- coding: utf-8 -*-
"""从者卡：数据库模型 → 素材按需拉取 → pytakumi 渲染 → 磁盘缓存。

和帮助卡共用 ``core/render.py``（同一套并发送流与字体策略），
版式与素材来自 ``card/``（从 fgo-wiki/card-render 搬来的那一份）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from . import render
from .db import load_card_model

HERE = Path(__file__).resolve().parent.parent
CARD = HERE / "card"


def cache_dir() -> Path:
    try:
        from gsuid_core.data_store import get_res_path

        return get_res_path("FGOUID/cards")
    except Exception:
        p = Path(tempfile.gettempdir()) / "FGOUID" / "cards"
        p.mkdir(parents=True, exist_ok=True)
        return p


_TPL_SIG: str | None = None


def _template_sig() -> str:
    """版式指纹：模板 + 渲染代码（build.py）任何一处变了都要让旧缓存失效。

    只哈希模板不够——像「∅ / Ø 占位符」「技能标题排版」这种改动在 build.py 里，
    不失效的话用户会一直看到老图。
    """
    global _TPL_SIG
    if _TPL_SIG is None:
        h = hashlib.sha1()
        for f in (CARD / "templates" / "servant_card_data.html", CARD / "build.py"):
            if f.is_file():
                h.update(f.read_bytes())
        _TPL_SIG = h.hexdigest()[:8]
    return _TPL_SIG


def _card_cache_key(model: dict, lang: str = "zh", quality: str = "hd") -> str:
    blob = (json.dumps(model, ensure_ascii=False, sort_keys=True) + "|" + lang
            + "|" + quality + "|" + _template_sig())
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def split_modules(model: dict) -> list[dict]:
    """多宝具/多模组从者：拆成多张卡（每个模组一张），否则返回单张。

    玛修、玉兔、卫宫这种从者有 2~4 套宝具，硬塞进一张图会拉到上万像素，
    不如按模组各出一张，用户自己翻。
    """
    # 多形态（玛修）：每种形态一张卡，用该形态自己的技能组与宝具
    forms = model.get("forms") or []
    if len(forms) >= 2:
        return [dict(model, skills=f.get("skills") or [],
                     np=f.get("np") or (model.get("np") or {}),
                     _module_no=i + 1, _module_total=len(forms),
                     _form_label=f.get("form", f"形态 {i + 1}"))
                for i, f in enumerate(forms)]

    modules = (model.get("np") or {}).get("modules") or []
    if len(modules) < 2:
        return [model]

    # Atlas 里有些「多模组」其实是同一条数据挂两个 num（玉兔就是这样），去掉完全相同的
    seen, uniq = set(), []
    for mod in modules:
        sig = json.dumps({k: mod.get(k) for k in ("name", "rank", "sub", "chips", "effects")},
                         ensure_ascii=False, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(mod)
    if len(uniq) < 2:
        variant = dict(model)
        variant["np"] = uniq[0]
        return [variant]
    out = []
    for i, mod in enumerate(uniq):
        variant = dict(model)
        variant["np"] = mod
        variant["_module_no"] = mod.get("module", i + 1)
        variant["_module_total"] = len(uniq)
        out.append(variant)
    return out


async def render_cards(servant_id: str, lang: str = "zh", quality: str = "hd") -> list[bytes]:
    """渲染某从者的卡图（多模组时返回多张）。lang=jp 时名称用日文名主显。"""
    if not render.available():
        return []
    model = load_card_model(servant_id)
    if model is None:
        return []

    variants = split_modules(model)
    if len(variants) == 1:
        one = await render_card_from_model(servant_id, model, lang=lang, quality=quality)
        return [one] if one else []
    return [p for p in [await render_card_from_model(servant_id, v, suffix=f"_m{v['_module_no']}",
                                                     lang=lang, quality=quality)
                        for v in variants] if p]


async def render_card_from_model(servant_id: str, model: dict, suffix: str = "",
                                 lang: str = "zh", quality: str = "hd") -> bytes | None:
    if not render.available():
        return None
    key = _card_cache_key(model, lang, quality)
    path = cache_dir() / f"{servant_id}{suffix}_{key}.img"
    if path.is_file():
        return path.read_bytes()

    from ..card import build, fetch

    html = build.build_html(model, lang=lang)
    names = build.assets_used(html)
    extra = await asyncio.to_thread(fetch.extra_images, model, names)
    png = await render.render_png(html, CARD / "templates", extra_images=extra, quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"{servant_id}{suffix}_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png


async def render_card(servant_id: str, lang: str = "zh", quality: str = "hd") -> bytes | None:
    """渲染某从者的卡图；无卡片数据或渲染器不可用时返回 None（调用方降级成文字）。"""
    if not render.available():
        return None
    model = load_card_model(servant_id)
    if model is None:
        return None

    key = _card_cache_key(model, lang, quality)
    path = cache_dir() / f"{servant_id}_{key}.img"
    if path.is_file():
        return path.read_bytes()

    from ..card import build, fetch  # 延迟导入 + 相对导入（插件包名不固定）

    html = build.build_html(model, lang=lang)
    names = build.assets_used(html)
    extra = await asyncio.to_thread(fetch.extra_images, model, names)

    png = await render.render_png(html, CARD / "templates", extra_images=extra, quality=quality)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"{servant_id}_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
