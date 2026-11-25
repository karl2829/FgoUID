# -*- coding: utf-8 -*-
"""服务器端卡片渲染：pytakumi（HTML/CSS → Skia 位图），不启浏览器进程。

定位（对齐 GsCore 文档三档：PIL → 纯 HTML 渲染 → playwright）：
从者卡/帮助卡版式密集、要 CSS 渐变与金属质感，又不想拉 playwright，所以走第 2 档。

实测（2 核 2G 阿里云，容器上限 900M）：
  dpr=2 单张 ≈ 1.1s，进程峰值 +82MB，容器 452MiB
  dpr=1 单张 ≈ 0.6s，进程峰值 +59MB
  并发 4 张 → 容器 577MiB（所以这里限并发 2，留足余量给别的插件）

为什么要限并发：8 张并发能把容器顶到 840MiB+，逼近 900MiB 上限。
配了 ``Semaphore`` 之后，最坏情况稳定在 500MiB 上下。
"""
from __future__ import annotations

import asyncio
import io
import os
import re
from pathlib import Path
from typing import Optional

MAX_CONCURRENCY = 2

_sem = asyncio.Semaphore(MAX_CONCURRENCY)
_fonts: Optional[list[bytes]] = None

# 中文字体必须显式注入：pytakumi 不扫系统字体，缺字渲染成豆腐块。
# 优先用 GsCore 自带的 MiSans（安装即存在），其次系统文泉驿。
_SYSTEM_FONTS = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def available() -> bool:
    """pytakumi 是否可用（未安装时插件降级到预渲染图/纯文字）。"""
    try:
        import pytakumi  # noqa: F401
    except Exception:
        return False
    return True


def font_path() -> Optional[Path]:
    try:
        from gsuid_core.utils.fonts.fonts import FONT_ORIGIN_PATH

        if FONT_ORIGIN_PATH.exists():
            return FONT_ORIGIN_PATH
    except Exception:
        pass
    for candidate in _SYSTEM_FONTS:
        p = Path(candidate)
        if p.exists():
            return p
    return None


def load_fonts() -> Optional[list[bytes]]:
    global _fonts
    if _fonts is None:
        p = font_path()
        if p is None:
            return None
        _fonts = [p.read_bytes()]
    return _fonts


def collect_images(html: str, base: Path) -> Optional[dict[str, bytes]]:
    """把 HTML 里引用的本地图片读成 bytes（pytakumi 不会自己读盘）。"""
    out: dict[str, bytes] = {}
    for src in set(re.findall(r'src="([^"]+)"', html)):
        if src.startswith(("http://", "https://", "data:")):
            continue
        p = base / src
        if p.is_file():
            out[src] = p.read_bytes()
    return out or None


def _render_sync(html: str, base: Path, width: int, dpr: int, bleed: int, margin: int) -> bytes:
    """线程内执行：渲染 + 裁掉外发光预留边。"""
    import pytakumi
    from PIL import Image

    png = pytakumi.html_to_pic(
        html,
        width=int((width + 2 * bleed) * dpr),
        device_pixel_ratio=dpr,
        format="png",
        images=collect_images(html, base),
        fonts=load_fonts(),
    )
    if margin is None:
        return png
    im = Image.open(io.BytesIO(png))
    cut = max(0, bleed - margin) * dpr
    im = im.crop((cut, cut, im.width - cut, im.height - cut))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def render_png(
    html: str,
    base: Path,
    *,
    width: int = 1080,
    dpr: int = 2,
    bleed: int = 40,
    margin: int = 10,
) -> bytes:
    """渲染 HTML 为 PNG bytes。并发受限（见模块 docstring）。"""
    if not available():
        raise RuntimeError("pytakumi 不可用")
    async with _sem:
        return await asyncio.to_thread(_render_sync, html, base, width, dpr, bleed, margin)
