# -*- coding: utf-8 -*-
"""用户自定义别名：群/人维度持久化，支持从者、礼装、御主衣服三类目标。

存 ``<data>/FGOUID/user_aliases.json``：``{"g:<群号>": [ {...} ], "u:<QQ号>": [ {...} ]}``
群聊里加的别名全群可用，私聊加的只自己可用（与 settings 同一套 scope 逻辑）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

from .store import file

FILE = "user_aliases.json"
MAX_ALIAS = 20
_lock = threading.Lock()

# 不能当别名的词：会和内置指令打架
RESERVED = {
    "从者", "礼装", "活动", "卡池", "测试", "帮助", "今日老婆", "老婆", "每日一抽",
    "一抽", "抽卡", "图鉴", "下载资源", "设置", "设置画质", "设置语言", "设置出图",
    "别名", "fgo",
}


def _load() -> dict:
    p = file(FILE)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    p = file(FILE)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def add(scope: str, alias: str, etype: str, eid: str, ename: str, by: str = "") -> str:
    """返回 ok / reserved / exists（同名同目标）/ conflict（同名不同目标）/ bad。"""
    alias = (alias or "").strip()
    if not alias or len(alias) > MAX_ALIAS:
        return "bad"
    if alias in RESERVED:
        return "reserved"
    with _lock:
        data = _load()
        items = data.setdefault(scope, [])
        for it in items:
            if _norm(it.get("alias")) == _norm(alias):
                if it.get("type") == etype and str(it.get("id")) == str(eid):
                    return "exists"
                return "conflict"
        items.append({
            "alias": alias, "type": etype, "id": str(eid), "name": ename,
            "by": str(by or ""), "at": datetime.now().isoformat(timespec="seconds"),
        })
        _save(data)
    return "ok"


def remove(scope: str, alias: str) -> dict | None:
    with _lock:
        data = _load()
        items = data.get(scope, [])
        for i, it in enumerate(items):
            if _norm(it.get("alias")) == _norm(alias):
                removed = items.pop(i)
                _save(data)
                return removed
    return None


def list_of(scope: str) -> list[dict]:
    with _lock:
        data = _load()
    return list(data.get(scope, []))


def find(scope: str, text: str) -> dict | None:
    """按别名精确查找（大小写不敏感）。"""
    key = _norm(text)
    if not key:
        return None
    for it in list_of(scope):
        if _norm(it.get("alias")) == key:
            return it
    return None


def describe(items: list[dict], limit: int = 20) -> str:
    if not items:
        return "还没有自定义别名。用「fgo别名 添加 摩根 老婆」这种格式添加"
    type_cn = {"servant": "从者", "ce": "礼装", "mystic": "御主衣服"}
    lines = [f"自定义别名（{len(items)} 条）："]
    for it in items[:limit]:
        lines.append(f"· {it['alias']} → {type_cn.get(it['type'], it['type'])}「{it.get('name', '')}」")
    if len(items) > limit:
        lines.append(f"……还有 {len(items) - limit} 条")
    return "\n".join(lines)
