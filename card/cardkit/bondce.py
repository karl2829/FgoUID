"""羁绊加成礼装反查（插件内版）。

数据来源：``card/bondce.json``（由 tools/sync_bondce.py 从 fgo-wiki 的
``entities/bond-ce/从者适配反查.md`` + ``index.md`` 固化，约 100KB）。
运行时不再读 wiki，也不再联网。
"""
from __future__ import annotations
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "bondce.json"
_CACHE: dict | None = None

import re as _re

# 条件里的叫法 → 从者特性/阵营里的实际词
TERM_ALIAS = {
    "拥有灵衣之人": "持有灵衣之人",
    "星属性": "星", "天属性": "天", "地属性": "地", "人属性": "人", "兽属性": "兽",
    "七骑士职阶": "七骑士职阶",     # 由职阶推导出来的伪特性
    "兽科从者": "兽科从者", "活在当下的人类": "活在当下的人类",
}
SEVEN_KNIGHTS = {"saber", "archer", "lancer", "rider", "caster", "assassin", "berserker"}
_STAGE = _re.compile(r"〔仅[^〕]*〕")     # 〔仅第4阶段〕〔仅灵衣xxxx〕这类修饰，不参与判断
_TERM = _re.compile(r"〔([^〕]+)〕")


def _cond_terms(cond: str) -> list[str]:
    """拆条件串：去掉「仅第 N 阶段」修饰，取出所有〔词〕。"""
    return _TERM.findall(_STAGE.sub("", cond or ""))


def lookup(collection_no: int) -> list[dict]:
    """按图鉴编号取该从者可吃到的限定羁绊礼装。"""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(DATA.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {}
    return _CACHE.get(str(collection_no), [])


def fit(collection_no: int, traits: list[str], klass: str = "") -> tuple[list[str], set[str]]:
    """按该从者实际特性，算出能吃到加成的金色词 + 已被金色词消费的特性。

    以前用「条件原文 → 一个复合短词」（如〔秩序〕且〔女性〕→「秩序女」），
    结果卡片上把「秩序女」当成一个特性显示出来，既不是特性也很难看。
    现在拆成单个〔词〕逐个匹配：命中的词各自高亮，未在特性行出现的词只算条件、不显示。
    """
    have = set(traits)
    if (klass or "").lower() in SEVEN_KNIGHTS:
        have.add("七骑士职阶")
    gold, consumed = [], set()
    for ce in lookup(collection_no):
        cond = ce.get("cond", "")
        terms = _cond_terms(cond)
        if not terms:
            continue
        norm = [TERM_ALIAS.get(t, t) for t in terms]
        hit = [t for t in norm if t in have]
        if "或" in cond:
            ok = bool(hit)                      # 或关系：任一命中
            words = hit
        else:
            ok = len(hit) == len(norm)         # 且关系：全部命中
            words = norm if ok else []
        if not ok:
            continue
        for w in words:
            if w in traits and w not in gold:  # 只有会显示成特性的词才高亮
                gold.append(w)
        consumed.update(w for w in words if w in have)
    return gold, consumed


def gold_terms(collection_no: int) -> list[str]:
    """金色礼装适性词（按礼装顺序去重）。"""
    seen, out = set(), []
    for ce in lookup(collection_no):
        t = ce.get("short")
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
