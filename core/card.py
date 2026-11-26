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


def _card_cache_key(model: dict) -> str:
    blob = json.dumps(model, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def split_modules(model: dict) -> list[dict]:
    """多宝具/多模组从者：拆成多张卡（每个模组一张），否则返回单张。

    玛修、玉兔、卫宫这种从者有 2~4 套宝具，硬塞进一张图会拉到上万像素，
    不如按模组各出一张，用户自己翻。
    """
    modules = (model.get("np") or {}).get("modules") or []
    if len(modules) < 2:
        return [model]
    out = []
    for i, mod in enumerate(modules):
        variant = dict(model)
        variant["np"] = mod
        variant["_module_no"] = mod.get("module", i + 1)
        variant["_module_total"] = len(modules)
        out.append(variant)
    return out


async def render_cards(servant_id: str) -> list[bytes]:
    """渲染某从者的卡图（多模组时返回多张）。"""
    if not render.available():
        return []
    model = load_card_model(servant_id)
    if model is None:
        return []

    variants = split_modules(model)
    if len(variants) == 1:
        one = await render_card_from_model(servant_id, model)
        return [one] if one else []
    return [p for p in [await render_card_from_model(servant_id, v, suffix=f"_m{v['_module_no']}")
                        for v in variants] if p]


async def render_card_from_model(servant_id: str, model: dict, suffix: str = "") -> bytes | None:
    if not render.available():
        return None
    key = _card_cache_key(model)
    path = cache_dir() / f"{servant_id}{suffix}_{key}.png"
    if path.is_file():
        return path.read_bytes()

    from ..card import build, fetch

    html = build.build_html(model)
    names = build.assets_used(html)
    extra = await asyncio.to_thread(fetch.extra_images, model, names)
    png = await render.render_png(html, CARD / "templates", extra_images=extra)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"{servant_id}{suffix}_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png


async def render_card(servant_id: str) -> bytes | None:
    """渲染某从者的卡图；无卡片数据或渲染器不可用时返回 None（调用方降级成文字）。"""
    if not render.available():
        return None
    model = load_card_model(servant_id)
    if model is None:
        return None

    key = _card_cache_key(model)
    path = cache_dir() / f"{servant_id}_{key}.png"
    if path.is_file():
        return path.read_bytes()

    from ..card import build, fetch  # 延迟导入 + 相对导入（插件包名不固定）

    html = build.build_html(model)
    names = build.assets_used(html)
    extra = await asyncio.to_thread(fetch.extra_images, model, names)

    png = await render.render_png(html, CARD / "templates", extra_images=extra)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"{servant_id}_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
