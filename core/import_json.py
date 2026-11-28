# -*- coding: utf-8 -*-
"""导入外部抓包/导出数据（A 路线）：不扫码也能出卡。

支持的输入：
1. Reqable/Charles 抓到的 login 响应原文（base64，可能带 gzip/zlib 包多层）
2. 已解码的 JSON：{"cache": {"replaced": ...}} 或 {"response": [...]}
3. 我们自己的 topLogin 缓存（直接是 replaced 字典）
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import zlib


def _try_json(blob: bytes) -> dict | None:
    try:
        data = json.loads(blob.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def decode_payload(raw: bytes) -> dict:
    """尽量把任意包装的响应解成 dict。"""
    raw = raw.strip()
    data = _try_json(raw)
    if data:
        return data
    # base64 层层解，最多 5 层（gzip/zlib 混合）
    cur = raw
    for _ in range(5):
        try:
            cur = base64.b64decode(cur + b"==", validate=False)
        except Exception:
            break
        data = _try_json(cur)
        if data:
            return data
        for opener in (gzip.decompress, zlib.decompress):
            try:
                inner = opener(cur)
            except Exception:
                continue
            data = _try_json(inner)
            if data:
                return data
            cur = inner
    raise ValueError("无法解析这段数据，请确认是召唤记录/login 的响应")


def to_replaced(data: dict) -> dict:
    """归一化成 cache.replaced 结构（附带 __updated__）。"""
    if "cache" in data:
        cache = data.get("cache") or {}
        rep = dict(cache.get("replaced") or {})
        rep["__updated__"] = cache.get("updated") or {}
        if rep.get("userGame"):
            return rep
    if "response" in data:
        # 少数导出的结构：把 response 里的表摊平
        rep = {}
        for row in data.get("response") or []:
            for k, v in (row.get("success") or {}).items():
                if isinstance(v, list):
                    rep[k] = v
        if rep.get("userGame"):
            return rep
    if data.get("userGame"):
        return dict(data, __updated__=data.get("__updated__") or {})
    # Chaldea 导出：server 字段 + 表名
    for key in ("server", "data", "result"):
        sub = data.get(key)
        if isinstance(sub, dict):
            try:
                return to_replaced(sub)
            except ValueError:
                continue
    raise ValueError("结构里没有 userGame，应该不是 FGO 账号数据")


def parse(raw: bytes) -> dict:
    return to_replaced(decode_payload(raw))
