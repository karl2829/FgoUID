#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 fgo帮助 卡片图（构建期一次性生成 ``assets/help.png``，作为渲染失败时的兜底）。

直接用插件自己的 ``core/help_card.py``（模型 + HTML 投影），保证兜底图和
运行时渲染出来的图**同源**——以前这里另抄了一份上下文，模板一改就悄悄失配了。

用法：
    .render-venv/bin/python tools/render_help.py            # → assets/help.png
    .render-venv/bin/python tools/render_help.py --dpr 1    # 低分辨率预览
    .render-venv/bin/python tools/render_help.py -o /tmp/x.png
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "help_card.html"
OUT = ROOT / "assets" / "help.png"

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def load_plugin_core():
    """按包路径导入插件的 core 包（不用 sys.path hack，避免和 GsCore 撞名）。"""
    spec = importlib.util.spec_from_file_location(
        "fgouid_core", ROOT / "core" / "__init__.py",
        submodule_search_locations=[str(ROOT / "core")],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fgouid_core"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    import fgouid_core.help_card as help_card  # noqa: E402

    return help_card


def load_fonts() -> list[bytes]:
    got = [open(p, "rb").read() for p in FONT_CANDIDATES if pathlib.Path(p).is_file()]
    if not got:
        raise RuntimeError("缺少中文字体，请安装 fonts-wqy-zenhei")
    return got


def collect_images(html: str, base: pathlib.Path) -> dict[str, bytes] | None:
    out: dict[str, bytes] = {}
    for src in sorted(set(re.findall(r'src="([^"]+)"', html))):
        if src.startswith(("http://", "https://", "data:")):
            continue
        p = base / src
        if p.is_file():
            out[src] = p.read_bytes()
        else:
            raise FileNotFoundError(f"模板引用的图片不存在：{p}")
    return out or None


def render(html: str, out: pathlib.Path, *, width=1080, dpr=2, bleed=40, margin=10) -> dict:
    import pytakumi
    from PIL import Image

    t0 = time.perf_counter()
    png = pytakumi.html_to_pic(
        html,
        width=int((width + 2 * bleed) * dpr),
        device_pixel_ratio=dpr,
        format="png",
        images=collect_images(html, TEMPLATE.parent),
        fonts=load_fonts(),
    )
    ms = (time.perf_counter() - t0) * 1000

    im = Image.open(io.BytesIO(png))
    cut = max(0, bleed - margin) * dpr
    im = im.crop((cut, cut, im.width - cut, im.height - cut))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, format="PNG", optimize=True)
    return {"path": str(out), "size": im.size, "ms": round(ms), "bytes": out.stat().st_size}


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 FGOUID 帮助卡")
    ap.add_argument("-o", "--out", type=pathlib.Path, default=OUT)
    ap.add_argument("--dpr", type=int, default=2)
    a = ap.parse_args()

    help_card = load_plugin_core()
    html = help_card.help_html(help_card.help_model())

    r = render(html, a.out, dpr=a.dpr)
    print(f"{r['path']}  {r['size'][0]}x{r['size'][1]}  {r['ms']} ms  {r['bytes'] / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
