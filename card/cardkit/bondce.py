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

# 条件原文 → (卡片金色词, 需要的特性)。金色词优先用 wiki 特性原词。
COND_RULES = {
    "〔秩序〕且〔善〕": ("秩序善", ["秩序", "善"]),
    "〔拥有灵衣之人〕": ("持有灵衣之人", ["持有灵衣之人"]),
    "〔秩序〕且〔女性〕": ("秩序女", ["秩序", "女性"]),
    "〔兽科从者〕": ("兽科从者", ["兽科从者"]),
    "〔活在当下的人类〕": ("活在当下的人类", ["活在当下的人类"]),
    "〔中立〕": ("中立", ["中立"]),
}
# 或关系条件单独处理：任一命中即可
COND_ANY = {"〔恶〕或〔星属性〕": ["恶", "星"]}


def lookup(collection_no: int) -> list[dict]:
    """按图鉴编号取该从者可吃到的限定羁绊礼装。"""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(DATA.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {}
    return _CACHE.get(str(collection_no), [])


def fit(collection_no: int, traits: list[str]) -> tuple[list[str], set[str]]:
    """按该从者实际特性，算出能吃到加成的金色词 + 已被金色词消费的特性。"""
    have = set(traits)
    gold, consumed = [], set()
    for ce in lookup(collection_no):
        cond = ce["cond"]
        words: list[str] = []
        need: list[str] = []
        if cond in COND_RULES:
            word, need = COND_RULES[cond]
            if all(t in have for t in need):
                words = [word]
        elif cond in COND_ANY:
            hit = [t for t in COND_ANY[cond] if t in have]
            if hit:
                words, need = hit, hit
        for w in words:
            if w not in gold:
                gold.append(w)
        consumed.update(need)
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
