# -*- coding: utf-8 -*-
"""个人数据「汇总档」：只保存分析后的结果，不保存原始召唤记录。

一次同步流程：
    扫码 → 拉全量 + 各池召唤记录（内存里）→ 计算汇总 → 写 profile.json.gz → 丢弃原始数据

体积参考：一个账号约 15~40KB（gzip 后），不含任何逐抽记录。
"""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "data" / "FGOUID" / "users"


def path_for(uid: int | str) -> Path:
    return DIR / f"{uid}.json.gz"


def save(uid: int | str, model: dict, raw_meta: dict | None = None) -> Path:
    DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": 1,
        "uid": str(uid),
        "saved_at": int(time.time()),
        "model": model,
        "meta": raw_meta or {},
    }
    blob = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    path = path_for(uid)
    path.write_bytes(gzip.compress(blob, 6))
    path.chmod(0o600)
    return path


def load(uid: int | str) -> dict | None:
    path = path_for(uid)
    if not path.is_file():
        return None
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()))
    except Exception:
        return None
    return doc.get("model") or None


def info(uid: int | str) -> dict:
    path = path_for(uid)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()))
    except Exception:
        return {}
    return {"saved_at": doc.get("saved_at", 0), "size": path.stat().st_size,
            "name": (doc.get("model") or {}).get("name", "")}


def list_all() -> list[dict]:
    out = []
    if not DIR.is_dir():
        return out
    for p in sorted(DIR.glob("*.json.gz")):
        uid = p.name.split(".")[0]
        out.append({"uid": uid, **info(uid)})
    return out


def total_size() -> int:
    if not DIR.is_dir():
        return 0
    return sum(p.stat().st_size for p in DIR.glob("*.json.gz"))
