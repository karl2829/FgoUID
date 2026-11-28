# -*- coding: utf-8 -*-
"""账号卡片：抽卡记录（五星网格 + 出金历史 + 欧非评级）。

数据来自扫码登录的 topLogin 响应（兄弟模块负责取数），这里只做
「payload → 模型 → HTML → 图」，和从者卡/礼装卡同一套路子。
"""
from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from . import render, store
from .db import DB_PATH

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates" / "account_card.html"
FACE = "https://static.atlasacademy.io/CN/Faces/f_{}0.png"

# 欧非评级（FGO 化）
TIERS = (
    (50, "冠位欧皇", "冠位指定级别的运气，人理都在为你让路。", "#FFE9A8"),
    (70, "异闻带欧皇", "在错误的概率里活成了正确的样子。", "#F7E7B6"),
    (90, "迦勒底欧皇", "被抑止力眷顾的御主。", "#EFD58C"),
    (110, "人理守护者", "标准出率，稳如人理定础。", "#D8E3F0"),
    (150, "平稳保底", "不欧不非，圣晶石按计划燃烧。", "#B7C2D2"),
    (200, "迦勒底非酋", "每次出金都要先打一场圣杯战争。", "#F0A87C"),
    (10**9, "终局非酋", "抽卡记录已被编入异闻带。", "#EE8A8A"),
)


def _rating(avg: float) -> tuple[str, str, str]:
    for limit, name, desc, color in TIERS:
        if avg < limit:
            return name, desc, color
    return TIERS[-1][1], TIERS[-1][2], TIERS[-1][3]


def _con():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_payload(path: str | Path) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    cache = d.get("cache") or {}
    rep = cache.get("replaced") or {}
    rep["__updated__"] = cache.get("updated") or {}
    return rep


def card_model(rep: dict, histories: dict[str, list[dict]]) -> dict:
    con = _con()
    try:
        def by_id(sql: str) -> dict:
            return {int(r["id"]): dict(r) for r in con.execute(sql)}

        # 只取国服行（同 id 有 CN/JP 两份）
        svt = by_id("SELECT id, name, rarity, servant_class FROM servants WHERE region='CN'")
        cno = {}
        try:
            import zlib
            for r in con.execute("SELECT id, data FROM servant_cards"):
                try:
                    d2 = json.loads(zlib.decompress(r[1]))
                    if d2.get("collection_no"):
                        cno[int(r[0])] = int(d2["collection_no"])
                except Exception:
                    continue
        except Exception:
            cno = {}
        ce = by_id("SELECT id, name, rarity FROM craft_essences WHERE region='CN'")
        gtype = by_id("SELECT id, name, gacha_type, started_at, ended_at FROM gacha_names")
    finally:
        con.close()

    ug = rep["userGame"][0]
    upd = (rep.get("__updated__") or {}).get("userLogin") or rep.get("userLogin") or [{}]
    login_row = upd[0] if upd else {}
    coll = rep.get("userSvtCollection") or []
    login = ((rep.get("userLogin") or [{}])[0] or {})
    totals = Counter()
    for r in rep.get("userGacha") or []:
        t = gtype.get(int(r["gachaId"]), {}).get("gacha_type", "unknown")
        totals[t] += int(r["num"])
    draws = totals["stone"] + totals["chargeStone"]

    BEAST = ("beast", "loregrand")

    def playable(r) -> bool:
        cls = str(svt.get(int(r["svtId"]), {}).get("servant_class") or "").lower()
        return cls and not any(k in cls for k in BEAST)

    def rarity_of(r) -> int:
        try:
            return int(svt.get(int(r["svtId"]), {}).get("rarity") or 0)
        except (TypeError, ValueError):
            return 0

    five = [r for r in coll if rarity_of(r) == 5 and playable(r)]
    four = [r for r in coll if rarity_of(r) == 4 and playable(r)]
    avg = draws / max(len(five), 1)
    tier, desc, tier_color = _rating(avg)

    # 五星网格：限定/常驻简单用是否在常驻卡池近似不了，先按职阶+宝具等级排
    owned_ids = {int(r["svtId"]) for r in (rep.get("userSvt") or [])}
    coll_by_id = {}
    for r in coll:
        try:
            coll_by_id[int(r["svtId"])] = r
        except (TypeError, ValueError):
            continue

    grid = []
    for r in five:
        sid = int(r["svtId"])
        if sid not in owned_ids:          # 只展示当前持有的
            continue
        meta = svt.get(sid, {})
        grid.append({
            "svt_id": sid,
            "cno": cno.get(sid, 0),
            "name": meta.get("name", ""),
            "class": meta.get("servant_class", ""),
            "count": max(int(r.get("totalGetNum") or 0), int(r.get("getNum") or 0), 1),
            "ts": int(r.get("createdAt") or 0),
            "np": int(r.get("treasureDeviceLv1") or 1),
            "face": f"face_{sid}.png",
            "face_url": FACE.format(sid),
        })
    grid.sort(key=lambda x: -x["cno"] or -x["svt_id"])   # 按实装顺序倒排（图鉴编号）
    year = datetime.now().year
    # 今年新获得（图鉴口径，含已变还的），按实装顺序倒排
    yg = []
    for r in five:
        try:
            ts = int(r.get("createdAt") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts and datetime.fromtimestamp(ts).year >= year:
            sid = int(r["svtId"])
            meta = svt.get(sid, {})
            yg.append({
                "svt_id": sid, "name": meta.get("name", ""),
                "cno": cno.get(sid, 0),
                "count": max(int(r.get("totalGetNum") or 0), int(r.get("getNum") or 0), 1),
                "owned": sid in owned_ids,
                "face": f"face_{sid}.png", "face_url": FACE.format(sid),
            })
    yg.sort(key=lambda x: -x["cno"] or -x["svt_id"])
    recent = yg or grid

    # 单推从者（头部头像）
    push = {}
    try:
        uid = str(ug.get("pushUserSvtId") or ug.get("favoriteUserSvtId") or "")
        owned = {str(r["id"]): r for r in (rep.get("userSvt") or [])}
        row = owned.get(uid)
        if row:
            sid = int(row["svtId"])
            meta = svt.get(sid, {})
            push = {"svt_id": sid, "name": meta.get("name", ""), "lv": int(row.get("lv") or 0),
                    "face": f"face_{sid}.png", "face_url": FACE.format(sid)}
    except Exception:
        push = {}

    # 出金历史
    events = []
    for gid, rows in histories.items():
        g = gtype.get(int(gid), {})
        for r in rows:
            if r.get("giftType") != 1:
                continue
            oid = int(r["objectId"])
            meta = svt.get(oid) or {}
            name = meta.get("name")
            rarity = meta.get("rarity")
            kind = "从者"
            if not name:
                cmeta = ce.get(oid) or {}
                name = cmeta.get("name")
                rarity = cmeta.get("rarity")
                kind = "礼装"
            if not name:
                continue
            events.append({
                "ts": int(r["createdAt"]),
                "pool": g.get("name", f"卡池 {gid}"),
                "name": name,
                "kind": kind,
                "rarity": rarity,
            })
    gacha_num = {int(r["gachaId"]): int(r["num"]) for r in (rep.get("userGacha") or [])}
    pools = []
    for gid, rows in histories.items():
        g = gtype.get(int(gid), {})
        if g.get("gacha_type") == "friendPoint":      # 友情池不展示
            continue
        cards = [r for r in rows if r.get("giftType") == 1]
        five_n = 0
        for r in cards:
            if int(svt.get(int(r["objectId"]), {}).get("rarity") or 0) == 5:
                five_n += 1
        ts = [int(r["createdAt"]) for r in rows]
        faces = []
        for r in cards:
            sid = int(r["objectId"])
            meta = svt.get(sid) or {}
            if not meta:
                continue
            faces.append({"face": f"face_{sid}.png", "face_url": FACE.format(sid),
                          "name": meta.get("name", ""), "rarity": int(meta.get("rarity") or 0)})
        kind = "福袋" if g.get("gacha_type") == "chargeStone" else (
            "常驻" if "剧情" in (g.get("name") or "") or "常驻" in (g.get("name") or "") else "限定")
        pools.append({
            "kind": kind,
            "faces": faces[:12],
            "name": g.get("name", f"卡池 {gid}"),
            "draws": gacha_num.get(int(gid), 0),
            "records": len(cards),
            "five": five_n,
            "time": (datetime.fromtimestamp(max(ts)).strftime("%m-%d") if ts else ""),
            "last_ts": max(ts) if ts else 0,
        })
    pools.sort(key=lambda p: -p["last_ts"])
    events.sort(key=lambda e: -e["ts"])
    for e in events:
        e["time"] = datetime.fromtimestamp(e["ts"]).strftime("%m-%d %H:%M")

    return {
        "name": ug.get("name", ""),
        "lv": ug.get("lv"),
        "start": datetime.fromtimestamp(int(ug.get("createdAt") or 0)).strftime("%Y-%m-%d"),
        "login_days": int(login_row.get("totalLoginCount") or 0),
        "friend_code": ug.get("friendCode", ""),
        "draws": draws,
        "bag_draws": totals["chargeStone"],
        "five": len(five),
        "five_owned": len(grid),
        "four": len(four),
        "avg": avg,
        "tier": tier,
        "tier_desc": desc,
        "tier_color": tier_color,
        "grid": grid,
        "grid_year": recent,
        "year": year,
        "grid_total": len(grid),
        "push": push,
        "pools": pools[:10],
        "events": events[:40],
    }


def _nick_html(name: str) -> str:
    """游戏昵称里 [xxx] 是颜色标记（如 [g] 金色），不显示，只影响颜色。"""
    esc = _html.escape
    m = re.match(r"^\[[a-zA-Z]\](.*)$", name or "")
    return esc(m.group(1) if m else (name or ""))


def card_html(model: dict) -> str:
    esc = _html.escape
    cells = "".join(
        f'<div class="cell"><img src="../assets/{g["face"]}">'
        f'<span class="cnt">×{g["count"]}</span></div>'
        for g in model["grid_year"])
    pool_rows = "".join(
        f'<div class="pb"><div class="ph">'
        f'<span class="tag">{p["kind"]}</span>'
        f'<span class="pn">{esc(p["name"][:26])}</span>'
        f'<span class="pt">{p["time"]}</span>'
        f'<span class="pd">{p["draws"]:,} 抽</span></div>'
        + ('<div class="pf">' + "".join(
            f'<div class="fc"><img src="../assets/{f["face"]}"></div>' for f in p["faces"]) + '</div>'
           if p["faces"] else '')
        + '</div>'
        for p in model["pools"])
    rows = "".join(
        f'<div class="ev"><span class="t">{e["time"]}</span>'
        f'<span class="nm">{esc(e["name"])}</span>'
        f'<span class="pool">{esc(e["pool"][:18])}</span></div>'
        for e in model["events"])
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, val in {
        "NAME": _nick_html(model["name"]),
        "LV": str(model["lv"]),
        "START": esc(model.get("start", "")),
        "LOGIN": f"{model.get('login_days', 0):,}",
        "FRIEND": esc(str(model["friend_code"])),
        "DRAWS": f"{model['draws']:,}",
        "BAG": f"{model['bag_draws']:,}",
        "FIVE": str(model["five_owned"]),
        "FIVE_COLL": str(model["five"]),
        "FOUR": str(model["four"]),
        "AVG": f"{model['avg']:.1f}",
        "RATE_W": f"{min(100, max(6, 3000 / max(model['avg'], 1))):.0f}",
        "TIER": esc(model["tier"]),
        "TIER_DESC": esc(model["tier_desc"]),
        "TIER_COLOR": model["tier_color"],
        "GRID": cells or '<div class="empty">今年还没有五星记录</div>',
        "GRID_N": str(len(model["grid_year"])),
        "GRID_TOTAL": str(model["grid_total"]),
        "YEAR": str(model["year"]),
        "EVENTS": rows or '<div class="empty">还没有出金记录</div>',
        "PUSH_FACE": f'../assets/{model["push"]["face"]}' if model.get("push") else "",
        "PUSH_NAME": esc(model["push"].get("name", "")) if model.get("push") else "",
        "PUSH_LV": str(model["push"].get("lv", "")) if model.get("push") else "",
        "POOLS": pool_rows or '<div class="empty">还没有卡池记录</div>',
    }.items():
        html = html.replace("{{%s}}" % key, val)
    left = [m for m in html.split("{{") if "}}" in m and m.split("}}")[0].isupper()]
    if left:
        raise ValueError(f"模板还有未填充占位符：{left[:3]}")
    return html


async def get_card_png(model: dict, quality: str = "std") -> bytes | None:
    if not render.available() or not model.get("grid"):
        return None
    html = card_html(model)
    key = hashlib.sha1((html + quality).encode("utf-8")).hexdigest()[:12]
    d = store.file("cards")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"acct_{key}.img"
    if path.is_file():
        return path.read_bytes()

    from ..card import fetch as card_fetch

    need = list(model["grid_year"]) + list(model["grid"]) + list(model["pools"])
    mapping = {g["face"]: g["face_url"] for g in model["grid_year"]}
    for p in model["pools"]:
        for f in p["faces"]:
            mapping[f["face"]] = f["face_url"]
    if model.get("push"):
        mapping[model["push"]["face"]] = model["push"]["face_url"]
    images = await asyncio.to_thread(card_fetch.remote_images, mapping, 8)
    png = await render.render_png(html, TEMPLATE.parent, quality=quality,
                                  extra_images=images, bleed=28, margin=8)
    try:
        path.write_bytes(png)
        for stale in d.glob("acct_*.img"):
            if stale.name != path.name:
                stale.unlink(missing_ok=True)
    except Exception:
        pass
    return png
