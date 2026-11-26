# -*- coding: utf-8 -*-
"""从者卡渲染（插件内版）：数据模型 → HTML → pytakumi/Skia 位图。

这份代码来自 fgo-wiki/card-render/make_card.py（「出图脚本先写在 wiki」），
搬进插件时只改了三处：模板/资产路径、渲染改为进程内调用、去掉开发期产物落盘。

输入是 ``servant_cards`` 表里的模型 JSON（tools/sync_cards.py 用 wiki 的
build_data.parse_servant() 解析 MD 得到），渲染逻辑与 wiki 完全一致。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent          # FGOUID/card
TPL = HERE / "templates" / "servant_card_data.html"
ASSETS = HERE / "assets"

BREAK_LEVELS = {1, 6, 10}   # 技能本断点：Lv.1 / Lv.6 / Lv.10
HIGHLIGHT_LEVEL = 6         # 高亮常驻断点


def _clamp_text(text: str, budget: float = 72.0) -> str:
    """按字宽预算截断（Skia 不会给 -webkit-line-clamp 画省略号，只能自己补 …）。"""
    text = (text or "").strip()
    used, out = 0.0, []
    for ch in text:
        w = 1.0 if ord(ch) > 0x2E80 else 0.55
        if used + w > budget:
            return "".join(out).rstrip() + "…"
        out.append(ch)
        used += w
    return text


def _strip_rank(name_jp: str, rank: str = "") -> str:
    """日文技能名末尾一般带阶级（「カリスマ B」），卡面已有 RANK 栏，去掉避免重复。"""
    name_jp = (name_jp or "").strip()
    if not name_jp:
        return ""
    if rank and name_jp.endswith(" " + rank):
        return name_jp[: -len(rank) - 1].strip()
    m = re.match(r"^(.*?)\s+([A-ZＡ-Ｚ][A-ZＡ-Ｚ＋+\-]{0,3})$", name_jp)
    return m.group(1).strip() if m else name_jp


def _pick_names(cn: str, jp: str, rank: str = "", lang: str = "zh") -> tuple[str, str]:
    """按语言决定「主名称 + 副名称」：中文界面主中文、副日文；日文界面反过来。"""
    cn, jp = (cn or "").strip(), (jp or "").strip()
    if lang == "jp" and jp:
        return _strip_rank(jp, rank), (cn if cn and cn != jp else "")
    return cn, (jp if jp and jp != cn else "")

def _skill_effect(eff: dict) -> str:
    desc, values, fixed = eff.get("desc", ""), eff.get("values"), eff.get("fixed")
    head = f'<div class="sk-d"><span>{desc}</span></div>'

    if not values:                      # 恒定效果 / 无数值效果：都是通栏单格
        body = fixed if fixed else '<span class="empty">∅</span>'
        cls = "vb1" if fixed else "vb1 vb-empty"
        return f'<div class="sk-e">{head}<div class="v1"><div class="{cls}">{body}</div></div></div>'

    cells = []
    for i, v in enumerate(values, start=1):
        cls = "vb"
        mark = '<i class="brk"></i>' if i in BREAK_LEVELS else ""   # Lv.1/6/10 底部金线，不做高亮框
        cells.append(f'<div class="{cls}">{v}{mark}</div>')
    return f'<div class="sk-e">{head}<div class="v10">{"".join(cells)}</div></div>'


def _skill(sk: dict, lang: str = "zh") -> str:
    effects = "".join(_skill_effect(e) for e in sk["effects"])
    cn = sk.get("name", "")
    jp = _strip_rank(sk.get("name_jp", ""), sk.get("rank", ""))
    rank = sk.get("rank", "")
    primary, secondary = (jp, cn) if lang == "jp" and jp else (cn, jp)
    second = ""
    if secondary and secondary != primary:
        # 中日两版都带等级：中文名 B ／ 日文名 B
        second = (f'<span class="sep"></span><span class="nm-jp">{secondary}</span>'
                  f'<span class="rk sm">{rank}</span>')
    return f'''  <div class="sk">
    <div class="sk-h">
      <img src="../assets/{sk["icon"]}">
      <span class="nm">{primary}</span><span class="rk">{rank}</span>{second}
      <span class="sp"></span>
      <span class="cd">充能 <b>{sk["cd"]}</b></span>
    </div>
    {effects}
  </div>'''


def build_skills(skills: list[dict], lang: str = "zh") -> str:
    body = "\n".join(_skill(s, lang) for s in skills)
    return f'''<div class="sec-h"><span class="bar"></span><span class="t">持有技能</span>
  <span class="line"></span><span class="n">S K I L L S</span></div>

<section class="skills">
{body}
</section>
'''


def _np_effect(eff: dict) -> str:
    values, fixed = eff.get("values"), eff.get("fixed")
    if values:
        body = f'<div class="eb-v">{"".join(f"<div class=\"vb5\">{v}</div>" for v in values)}</div>'
    elif fixed:
        body = f'<div class="eb-v"><div class="vb5 vb5-fix">{fixed}</div></div>'
    else:                               # 无数值效果：通栏单格填 ∅
        body = '<div class="eb-v"><div class="vb5 vb5-fix vb-empty"><span class="empty">∅</span></div></div>' 
    return f'''  <div class="eb">
    <div class="eb-d"><span class="n">{eff["desc"]}</span><span class="h">{eff.get("hint","")}</span></div>
    {body}
  </div>'''


def build_np(np: dict, label: str = "", lang: str = "zh") -> str:
    name, _ = _pick_names(np.get("name", ""), np.get("name_jp", ""), "", lang)
    sub = np.get("name", "") if lang == "jp" and np.get("name_jp") else np.get("sub", "")
    chips = "".join(f'<div class="chip {c}">{t}</div>' for t, c in np["chips"])
    effects = "\n".join(_np_effect(e) for e in np["effects"])
    note = f'<span class="rk-note">{np["note"]}</span>' if np.get("note") else ""
    return f'''<section class="np">
  <div class="np-head">
    <div class="goldbar"></div>
    <div class="t">宝　具</div>
    <div class="dot"></div>
    {f'<div class="np-mod">{label}</div><div class="dot"></div>' if label else ''}
    <div class="stamp">N O B L E&nbsp;&nbsp;P H A N T A S M</div>
    <div class="spacer"></div>
    <div class="np-rule"></div>
    <div class="np-mark">N P</div>
  </div>
  <div class="name-row">
    <div>
      <div class="np-name">{name}</div>
      <div class="np-sub">{sub}</div>
    </div>
    <div class="rank"><span class="rk-lb">R A N K</span><span class="rk-v">{np["rank"]}</span>{note}</div>
  </div>
  <div class="chips">{chips}</div>
  <div class="div-weak"></div>
{effects}
</section>
'''



def _cw(t: str) -> float:
    """字宽估算：中日文字符 1，其余 0.55。"""
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in t)


def build_traits(data: dict, budget: float = 88.0) -> str:
    """特性行：能吃到羁绊加成礼装的条件词置顶金色（用 wiki 特性原词），其余灰白跟随。

    ``budget`` 按「两行」给（一行约 44 个 CJK 字宽，2 行 ≈ 88），排不下以 … 收尾。
    """
    from .cardkit import bondce
    traits = list(data.get("traits", []))
    if not traits:
        return ""
    no = int(data.get("collection_no", 0))
    pool = traits + [data["gender"]] if data.get("gender") else traits   # 性别也是礼装条件
    gold, consumed = bondce.fit(no, pool) if no else ([], set())

    limit = budget - 2.5          # 给末尾的 … 留点位置，别让它单独折到第 3 行
    parts, used, truncated = [], 0.0, False
    for w in gold:
        parts.append(("g", w)); used += _cw(w) + 1.8
    for t in traits:
        if t in consumed:
            continue
        if used + _cw(t) + 1.8 > limit:
            truncated = True
            break
        parts.append(("", t)); used += _cw(t) + 1.8

    html = "<i>・</i>".join(
        f'<span class="g">{w}</span>' if c == "g" else f"<span>{w}</span>" for c, w in parts)
    if truncated:
        html += '<span class="more">…</span>'
    return html


def assets_used(html: str) -> list[str]:
    """这张卡实际引用了 assets/ 下哪些文件（拷贝进插件时照单搬）。"""
    return sorted(set(re.findall(r'src="\.\./assets/([^"]+)"', html)))


def build_html(data: dict, hero_only: bool = False, lang: str = "zh") -> str:
    """把从者数据模型填进模板，返回完整 HTML（不落盘、不渲染）。"""
    html = TPL.read_text(encoding="utf-8")
    if hero_only:                       # 只出从者区模版：技能/宝具留空
        html = html.replace("<!--SKILLS-->", "").replace("<!--NP-->", "")
    else:
        html = html.replace("<!--SKILLS-->", build_skills(data["skills"], lang))
        nps = (data.get("np") or {}).get("modules") or ([data["np"]] if data.get("np") else [])
        multi = len(nps) > 1 or data.get("_module_total", 0) > 1   # 插件侧按模组拆图时会带 _module_*
        html = html.replace("<!--NP-->", "\n".join(
            build_np(n, lang=lang, label=(data.get("_form_label") or
                               (f"模组 {n.get('module', data.get('_module_no', i + 1))}" if multi else "")))
            for i, n in enumerate(nps)))

    _name, _name_jp = _pick_names(data.get("name", ""), data.get("name_jp", ""), "", lang)
    if not _name_jp:                    # 没有副名称就整行去掉
        html = html.replace('    <div class="name-jp">{{NAME_JP}}</div>', "")
    if not (data.get("bond") or {}).get("name"):     # 没有羁绊礼装（部分 NPC/活动从者）整块去掉
        html = re.sub(r"\s*<!--BOND_START-->.*?<!--BOND_END-->", "", html, flags=re.S)

    # ---- 头部字段全部来自 data（build_data.py 从 fgo-wiki MD 解析）----
    sid = str(data.get("servant_id") or data.get("id") or "")
    card_icon = {
        "Quick": "card_Q.png", "Arts": "card_A.png", "Buster": "card_B.png",
        "迅": "card_Q.png", "技": "card_A.png", "力": "card_B.png",
        "クイック": "card_Q.png", "アーツ": "card_A.png", "バスター": "card_B.png",
    }
    # 认不出来的类型宁可不出图，也不要默默退成 Arts（整排变蓝就是这么来的）
    cards_html = "".join(
        '<img src="../assets/%s">' % card_icon[c]
        for c in (data.get("cards") or []) if c in card_icon)
    hex_data = list(data.get("hex", []))
    if data.get("npgain"):
        hex_data.append(["NP获得", data["npgain"]])
    hex_html = "".join(f'<div class="hx"><i>{k}</i><b>{v}</b></div>' for k, v in hex_data)
    bond = data.get("bond") or {}
    bond_meta = "　·　".join(x for x in [bond.get("type", ""), bond.get("rarity", ""),
                                         f'COST {bond["cost"]}' if bond.get("cost") else ""] if x)
    klass = data.get("class", "")

    # 头部可配字段：星级图标按稀有度取金/银/铜，立绘裁切位置，限定标识
    rarity = int(data.get("rarity", 5))
    tier = "gold" if rarity >= 4 else ("silver" if rarity == 3 else "bronze")
    for k, v in {
        "STARS": f"★{rarity}",
        "STAR_TIER": tier,
        "ART_POS": data.get("art_pos", "50% 5%"),
        "LIMITED": data.get("limited", ""),
        "TRAITS": build_traits(data),
        "NPG": data.get("npgain", "—"),
        "RNUM": str(rarity),
        "NO": str(data.get("no", "")),
        "NAME": _name,
        "NAME_JP": _name_jp,
        "CLASS_EN": klass.upper(),
        "CLASS_ICON": "%s_%s.png" % (klass, "gold" if rarity >= 4 else ("silver" if rarity == 3 else "bronze")) if klass else "saber_gold.png",
        "ATK": f'{int(data["atk"]):,}' if isinstance(data.get("atk"), int) else data.get("atk", ""),
        "HP": f'{int(data["hp"]):,}' if isinstance(data.get("hp"), int) else data.get("hp", ""),
        "LEVEL": str(data.get("level", "90")),
        "CARDS": cards_html,
        "HEX": hex_html,
        "CAMP": data.get("camp") or "—",
        "ALIGN": data.get("alignment") or "—",
        "GENDER": data.get("gender") or "—",
        "ARTIST": data.get("artist", ""),
        "CV": data.get("cv", ""),
        "ART": f"art_{sid}.png",
        "BOND_IMG": f"bond_ce_{sid}.png",
        "BOND_NAME": bond.get("name", ""),
        "BOND_EFFECT": _clamp_text(bond.get("effect", ""), 72),
    }.items():
        html = html.replace("{{" + k + "}}", str(v))
    return html




def render_card(data: dict, out: Path, *, hero_only: bool = False,
                extra_images: Optional[dict[str, bytes]] = None, dpr: int = 2) -> dict:
    """渲染一张从者卡到 out。"""
    from .cardkit.render import render_html

    html = build_html(data, hero_only=hero_only)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = render_html(html, out, base=TPL.parent, dpr=dpr, extra_images=extra_images)
    log = f'{r["path"]}  {r["size"][0]}x{r["size"][1]}  {r["ms"]:.0f} ms  {r["bytes"] / 1024:.0f} KB'
    return {"out": str(out), "log": log, "assets": assets_used(html), "render": r}
