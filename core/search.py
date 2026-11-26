# -*- coding: utf-8 -*-
"""统一检索：一条查询词同时试「从者（含自定义别名）/ 礼装 / 御主衣服」三个维度。

给 ``fgo<任意词>`` 用：先查用户自定义别名（精确命中，优先级最高），
再按内置数据查三类；跨类型命中时返回多组，由调用方列候选让用户收窄。

优先级别搞混：别名是「用户说了算」的，所以放在最前面；
内置数据内部保持 从者 → 礼装 → 御主衣服 的顺序。
"""
from __future__ import annotations

from . import aliases as alias_store
from .db import (
    CLASS_CN,
    alias_types,
    find_ces,
    find_mystic_codes,
    find_servants,
    load_entity,
)

TYPE_CN = {"servant": "从者", "ce": "礼装", "mystic": "御主衣服"}

_SEARCHERS = (
    ("servant", find_servants),
    ("ce", find_ces),
    ("mystic", find_mystic_codes),
)


def resolve(query: str, scope: str) -> list[tuple[str, list]]:
    """返回 [(类型, 命中行列表)]；空列表表示没命中。"""
    q = (query or "").strip()
    if not q:
        return []

    hit = alias_store.find(scope, q)
    if hit:
        row = load_entity(hit.get("type", ""), hit.get("id", ""))
        if row:
            return [(hit["type"], [row])]

    # 内置别名精确命中（如「宝石翁」→礼装、「迦勒底」→御主衣服）优先，
    # 否则「摩根」会同时命中从者和礼装「摩根尼亚物语」，用户没法用
    hit_types = alias_types(q)
    if len(hit_types) == 1:
        etype = next(iter(hit_types))
        searcher = dict(_SEARCHERS).get(etype)
        if searcher:
            rows = searcher(q)
            if rows:
                return [(etype, rows)]

    out: list[tuple[str, list]] = []
    for etype, searcher in _SEARCHERS:
        try:
            rows = searcher(q)
        except Exception:
            rows = []
        if rows:
            out.append((etype, rows))

    # 名称完全一致的优先（避免从者「摩根」被礼装「摩根尼亚物语」拖进模糊匹配）
    exact = [(t, [r for r in rows if _get(r, "name") == q]) for t, rows in out]
    exact = [(t, rs) for t, rs in exact if rs]
    if exact:
        return exact
    return out


def _get(row, key, default=""):
    """sqlite3.Row 和 dict 都兼容。"""
    try:
        return row[key]
    except Exception:
        return default


def entity_name(etype: str, row) -> str:
    return _get(row, "name")


def describe_hit(etype: str, row) -> str:
    """候选行的一行描述（带类型标签）。"""
    tag = TYPE_CN.get(etype, etype)
    name = _get(row, "name")
    if etype == "servant":
        klass = str(_get(row, "servant_class") or "").lower()
        stars = "★" * int(_get(row, "rarity", 0) or 0)
        return f"{tag}｜{klass.capitalize()} {stars}｜{name}"
    if etype == "ce":
        stars = "★" * int(_get(row, "rarity", 0) or 0)
        return f"{tag}｜{stars} COST {_get(row, 'cost')}｜{name}"
    return f"{tag}｜{name}"


def hint_for(etype: str, row) -> str:
    """可直接复制的精确指令。"""
    name = _get(row, "name")
    if etype == "servant":
        klass = str(_get(row, "servant_class") or "").lower()
        cn = CLASS_CN.get(klass, klass)
        return f"fgo从者 {cn} {int(_get(row, 'rarity', 0) or 0)}星 {name}"
    if etype == "ce":
        return f"fgo礼装 {name}"
    return f"fgo御主衣服 {name}"
