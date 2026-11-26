# -*- coding: utf-8 -*-
"""按群/按人的偏好设置（不需要账号数据的那些开关）。

存 ``<data>/FGOUID/settings.json``，结构 ``{"g:<群号>": {...}, "u:<QQ号>": {...}}``：
群聊按群走（换了谁的号都一样），私聊按人走。没设置过的键用默认值，不写盘。

为什么不用 GsCore 的插件配置：那套是按「插件」全局配置、需要重启/网页端改；
这里要的是用户当场发指令就能改的开关。
"""
from __future__ import annotations

import json
import threading

from .store import file

FILE = "settings.json"
_lock = threading.Lock()

DEFAULTS: dict[str, object] = {
    "image": True,     # 出图开关：关掉后所有卡片命令回落到文字
    "lang": "zh",      # zh / jp（名称语言，日文名数据来自模型里的 name_jp）
}

# 给「fgo设置」文案用的中文名
LABELS = {"image": "出图", "lang": "语言"}
CHOICES = {
    "image": {True: "开", False: "关"},
    "lang": {"zh": "中文", "jp": "日文"},
}


def scope_of(ev) -> str:
    gid = getattr(ev, "group_id", None)
    if gid and str(gid) not in ("0", "None", ""):
        return f"g:{gid}"
    return f"u:{getattr(ev, 'user_id', '0')}"


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


def get(scope: str, key: str):
    with _lock:
        data = _load()
    return data.get(scope, {}).get(key, DEFAULTS.get(key))


def put(scope: str, key: str, value) -> None:
    with _lock:
        data = _load()
        data.setdefault(scope, {})[key] = value
        _save(data)


def all_of(scope: str) -> dict:
    with _lock:
        data = _load()
    merged = dict(DEFAULTS)
    merged.update(data.get(scope, {}))
    return merged


def image_on(ev) -> bool:
    return bool(get(scope_of(ev), "image"))


def parse_bool(text: str) -> bool | None:
    t = (text or "").strip().lower()
    if t in ("开", "开图", "on", "true", "1", "是", "图片", "图"):
        return True
    if t in ("关", "关图", "off", "false", "0", "否", "文字", "别发图", "不发图"):
        return False
    return None


def format_settings(ev) -> str:
    scope = scope_of(ev)
    cur = all_of(scope)
    where = "本群" if scope.startswith("g:") else "私聊"
    lines = [f"【FGOUID 设置】{where}"]
    for key in ("image", "lang"):
        val = cur.get(key)
        shown = CHOICES.get(key, {}).get(val, str(val))
        lines.append(f"{LABELS[key]}：{shown}")
    lines.append("")
    lines.append("fgo设置出图 开/关 — 关掉后只看文字")
    lines.append("fgo设置语言 中/日 — 名称语言（施工中）")
    return "\n".join(lines)
