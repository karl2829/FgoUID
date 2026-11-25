#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计所有从者卡引用了哪些素材（决定什么随包、什么按需拉）。

不渲染、不联网，只跑 build_html + assets_used 聚合，几秒出结果。

用法：
    .render-venv/bin/python tools/asset_manifest.py                 # 控制台摘要
    .render-venv/bin/python tools/asset_manifest.py -o manifest.json
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sqlite3
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fgo.db"
BUNDLED = ROOT / "card" / "assets"


def load_build():
    spec = importlib.util.spec_from_file_location(
        "fgouid_card", ROOT / "card" / "__init__.py", submodule_search_locations=[str(ROOT / "card")]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fgouid_card"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    import fgouid_card.build as build  # noqa: E402

    return build


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--db", type=Path, default=DB)
    a = ap.parse_args()

    build = load_build()
    con = sqlite3.connect(a.db)
    rows = con.execute("SELECT id, region, data FROM servant_cards ORDER BY id").fetchall()
    con.close()

    counter: collections.Counter = collections.Counter()
    per_card: dict[str, list[str]] = {}
    failed = []
    for sid, region, blob in rows:
        try:
            model = json.loads(zlib.decompress(blob))
            names = build.assets_used(build.build_html(model))
            per_card[sid] = names
            counter.update(names)
        except Exception as e:
            failed.append((sid, f"{type(e).__name__}: {e}"))

    from fgouid_card.fetch import ALIASES  # noqa: E402
    import fgouid_card.fetch as _fetch  # noqa: E402

    bundled = {n for n in counter if (BUNDLED / n).is_file()}
    aliased = {n for n in counter
               if n not in bundled and n in ALIASES and (_fetch.BUNDLED / ALIASES[n]).is_file()}
    remote = sorted(n for n in counter if n not in bundled and n not in aliased)
    remote_kind = collections.Counter()
    for n in remote:
        if n.startswith("art_"):
            remote_kind["立绘 art_<id>.png"] += 1
        elif n.startswith("bond_ce_"):
            remote_kind["羁绊礼装 bond_ce_<id>.png"] += 1
        elif n.startswith("skill_"):
            remote_kind["技能图标 skill_<id>.png"] += 1
        else:
            remote_kind["其他"] += 1

    print(f"卡片 {len(rows)} 张，解析失败 {len(failed)}")
    print(f"随包素材被引用：{len(bundled)} 种（另有 {len(aliased)} 种走别名：{sorted(aliased)}）")
    print(f"需要外部获取：{len(remote)} 种")
    for k, v in remote_kind.most_common():
        print(f"  - {k}: {v}")
    if failed:
        print("失败样例：", failed[:5])

    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({
            "cards": len(rows),
            "bundled_used": sorted(bundled),
            "remote": {n: counter[n] for n in remote},
            "per_card": per_card,
            "failed": failed,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
