#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 fgo帮助 卡片图（构建期一次性生成，运行时不依赖 pytakumi）。

用法：
    .render-venv/bin/python tools/render_help.py            # → assets/help.png
    .render-venv/bin/python tools/render_help.py --dpr 1    # 低分辨率预览

数据（数量、别名数、wiki commit）从 data/meta.json 与 data/fgo.db 现读，
所以数据刷新后重跑一次即可，不会出现图里数字和库对不上的情况。

依赖：pytakumi（HTML/CSS → Skia）。中文字体必须显式注入，否则全是豆腐块。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import sqlite3
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "help_card.html"
OUT = ROOT / "assets" / "help.png"
META = ROOT / "data" / "meta.json"
DB = ROOT / "data" / "fgo.db"

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def load_fonts() -> list[bytes]:
    got = [open(p, "rb").read() for p in FONT_CANDIDATES if os.path.exists(p)]
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


def build_context() -> dict[str, str]:
    meta = json.loads(META.read_text(encoding="utf-8"))
    counts = meta.get("counts", {})
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        aliases = conn.execute("select count(*) from aliases").fetchone()[0]
    return {
        "SERVANTS": f"{counts.get('servants', 0):,}",
        "CE": f"{counts.get('ce', 0):,}",
        "EVENTS": f"{counts.get('events', 0):,}",
        "GACHA": f"{counts.get('gacha', 0):,}",
        "ALIASES": f"{aliases:,}",
        "COMMIT": str(meta.get("source_commit", ""))[:7],
    }


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

    html = TEMPLATE.read_text(encoding="utf-8")
    for k, v in build_context().items():
        html = html.replace("{{%s}}" % k, v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if left:
        raise SystemExit(f"模板还有未填充占位符：{sorted(set(left))}")

    r = render(html, a.out, dpr=a.dpr)
    print(f"{r['path']}  {r['size'][0]}x{r['size'][1]}  {r['ms']} ms  {r['bytes'] / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
