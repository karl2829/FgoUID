# -*- coding: utf-8 -*-
"""概念礼装卡：craft_essences + ce_details → 模型 → HTML → pytakumi 渲染 → 磁盘缓存。

数据分两张表（都是 wiki 的只读派生）：
  - ``craft_essences``：从 MD 来（名称/星级/COST/类型/一行效果）
  - ``ce_details``：从 raw JSON 来（卡面图、未破/满破效果、ATK/HP、图鉴编号）
缺 ``ce_details`` 的（主要是日服独有）就退回文字，不影响可用性。
"""
from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
from pathlib import Path

from . import render, store
from .db import DB_PATH

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "ce_card.html"

TITLE = "概念礼装"
EYEBROW_LEFT = "F G O U I D"
EYEBROW_RIGHT = "C R A F T　E S S E N C E"
FOOTER = {
    "l1": "数据来源　fgo-wiki 快照　·　Mooncell / Atlas Academy API",
    "l2": "版权所有　TYPE-MOON / FGO PROJECT　·　非官方插件",
    "r1": "DESIGN BY MILA",
    "r2": "DARK-CHALDEA FRAME ／ CE v1",
}

CE_TYPE_LABEL = {
    "servantEquip": "从者牵绊礼装",
    "normal": "普通礼装",
    "heroine": "剧情礼装",
    "eventReward": "活动奖励",
    "limited": "限定礼装",
    "storyLimited": "剧情限定",
    "valentine": "情人节礼物",
}


def load_details(con, ce_id: str, region: str) -> dict | None:
    row = con.execute(
        "SELECT * FROM ce_details WHERE id = ? ORDER BY CASE region WHEN ? THEN 0 ELSE 1 END LIMIT 1",
        (str(ce_id), region),
    ).fetchone()
    if row is None:
        row = con.execute(
            "SELECT * FROM ce_details WHERE id = ? LIMIT 1", (str(ce_id),)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["effects"] = json.loads(d.get("effects") or "[]")
    except Exception:
        d["effects"] = []
    return d


def load_details_for(ce) -> dict | None:
    """给一行 craft_essences 取对应的 ce_details（没有就 None → 文字降级）。"""
    import sqlite3

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return load_details(con, str(ce["id"]), ce["region"] or "CN")
    finally:
        con.close()


def art_name(ce_id: str) -> str:
    return f"ce_art_{ce_id}.png"


def ce_model(ce: dict, detail: dict | None) -> dict:
    detail = detail or {}
    rarity = int(ce.get("rarity") or 0)
    effects = detail.get("effects") or []
    return {
        "id": str(ce.get("id")),
        "name": (ce.get("name") or "").strip(),
        "name_jp": (detail.get("name_jp") or "").strip(),
        "rarity": rarity,
        "cost": ce.get("cost"),
        "type": CE_TYPE_LABEL.get(ce.get("ce_type") or "", ce.get("ce_type") or ""),
        "collection_no": detail.get("collection_no") or 0,
        "lv_max": detail.get("lv_max") or 0,
        "atk": [detail.get("atk_base") or 0, detail.get("atk_max") or 0],
        "hp": [detail.get("hp_base") or 0, detail.get("hp_max") or 0],
        "effects": effects,
        "fallback_effect": (ce.get("effect") or "").strip(),
        "art": art_name(ce.get("id")) if detail.get("art_url") else "",
        "art_url": detail.get("art_url") or "",
        "region": ce.get("region") or "CN",
    }


def _stars(n: int) -> str:
    return "★" * max(0, min(int(n or 0), 8))


def ce_html(model: dict) -> str:
    esc = _html.escape
    chips = []
    if model["rarity"]:
        chips.append(f'<span class="chip">{_stars(model["rarity"])}</span>')
    if model["type"]:
        chips.append(f'<span class="chip dim">{esc(model["type"])}</span>')
    if model["cost"]:
        chips.append(f'<span class="chip dim">COST {esc(str(model["cost"]))}</span>')
    if model["collection_no"]:
        chips.append(f'<span class="chip dim">No.{int(model["collection_no"]):03d}</span>')
    if model["region"] and model["region"] != "CN":
        chips.append(f'<span class="chip dim">{esc(model["region"])}</span>')

    nums = []
    for label, pair in (("ATK", model["atk"]), ("HP", model["hp"]), ("等级上限", [model["lv_max"]])):
        if label == "等级上限":
            val = str(pair[0] or "—")
        else:
            lo, hi = pair
            val = f"{lo} → {hi}" if lo or hi else "—"
        nums.append(f'<div class="n"><i>{label}</i><b>{esc(val)}</b></div>')

    effs = []
    if model["effects"]:
        for e in model["effects"]:
            label = "满破效果" if e.get("priority") == 2 else "未破效果"
            effs.append(
                f'<div class="ef"><div class="lb"><s></s>{label}</div>'
                f'<div class="tx">{esc(e.get("detail") or "")}</div></div>'
            )
    elif model["fallback_effect"]:
        effs.append(
            f'<div class="ef"><div class="lb"><s></s>效果</div>'
            f'<div class="tx">{esc(model["fallback_effect"])}</div></div>'
        )

    sub = "　·　".join(x for x in (model["type"], f"图鉴 No.{int(model['collection_no']):03d}" if model["collection_no"] else "") if x)
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "EYEBROW_LEFT": EYEBROW_LEFT,
        "EYEBROW_RIGHT": EYEBROW_RIGHT,
        "TITLE": TITLE,
        "SUB": sub or "离线快照",
        "PILL": model["region"] or "FGO",
        "NAME": esc(model["name"]),
        "NAME_JP": esc(model["name_jp"]) if model["name_jp"] and model["name_jp"] != model["name"] else "",
        "CHIPS": "".join(chips),
        "NUMS": "".join(nums),
        "EFFS": "".join(effs),
        "ART": model["art"],
        "FOOT_L1": FOOTER["l1"],
        "FOOT_L2": FOOTER["l2"],
        "FOOT_R1": FOOTER["r1"],
        "FOOT_R2": FOOTER["r2"],
    }.items():
        html = html.replace("{{%s}}" % key, val)
    left = [m for m in html.split("{{") if "}}" in m and m.split("}}")[0].isupper()]
    if left:
        raise ValueError(f"模板还有未填充占位符：{left[:3]}")
    return html


def _cache_key(model: dict) -> str:
    blob = json.dumps(model, ensure_ascii=False, sort_keys=True) + TEMPLATE.read_text(encoding="utf-8")
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


async def get_ce_png(ce: dict, detail: dict | None) -> bytes | None:
    """渲染礼装卡；没有卡面图或 pytakumi 不可用时返回 None（调用方降级文字）。"""
    if not detail or not detail.get("art_url"):
        return None
    model = ce_model(ce, detail)
    key = _cache_key(model)
    path = store.data_dir() / f"ce_{model['id']}_{key}.png"
    if path.is_file():
        return path.read_bytes()
    if not render.available():
        return None

    from ..card import fetch as card_fetch

    images = await asyncio.to_thread(
        card_fetch.remote_images, {model["art"]: model["art_url"]}
    )
    if not images:
        return None
    png = await render.render_png(ce_html(model), TEMPLATE.parent, extra_images=images)
    try:
        path.write_bytes(png)
        for stale in path.parent.glob(f"ce_{model['id']}_*.png"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
