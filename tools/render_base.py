#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染卡片基础模板（templates/base_card.html）——只出骨架，用来评审版式。

用法：
    .render-venv/bin/python tools/render_base.py -o out/base.png
    .render-venv/bin/python tools/render_base.py --dpr 1   # 快速预览
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "base_card.html"

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def fonts() -> list[bytes]:
    got = [open(p, "rb").read() for p in FONT_CANDIDATES if pathlib.Path(p).is_file()]
    fb = ROOT / "assets" / "fonts" / "DejaVuSans.ttf"
    if fb.is_file():
        got.append(fb.read_bytes())
    if not got:
        raise RuntimeError("找不到中文字体，先装 fonts-wqy-zenhei")
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", type=pathlib.Path, default=ROOT / "out" / "base_card.png")
    ap.add_argument("--dpr", type=float, default=2)
    a = ap.parse_args()

    import pytakumi
    from PIL import Image

    html = TEMPLATE.read_text(encoding="utf-8")
    t0 = time.perf_counter()
    png = pytakumi.html_to_pic(
        html, width=int((1080 + 80) * a.dpr), device_pixel_ratio=a.dpr,
        format="png", fonts=fonts(),
    )
    ms = (time.perf_counter() - t0) * 1000
    im = Image.open(io.BytesIO(png))
    cut = int(30 * a.dpr)
    im = im.crop((cut, cut, im.width - cut, im.height - cut))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    im.save(a.out, format="PNG", optimize=True)
    print(f"{a.out}  {im.size[0]}x{im.size[1]}  {ms:.0f} ms  {a.out.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
