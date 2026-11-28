# -*- coding: utf-8 -*-
"""QQ ↔ FGO UID 绑定与汇总档读取。"""
from __future__ import annotations

import json
from pathlib import Path

from . import userprofile

INDEX = userprofile.DIR / "index.json"


def _load_index() -> dict:
    if not INDEX.is_file():
        return {}
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {}


def bind(qq: str, uid: int) -> None:
    idx = _load_index()
    idx[str(qq)] = str(uid)
    userprofile.DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def unbind(qq: str) -> bool:
    idx = _load_index()
    if str(qq) not in idx:
        return False
    idx.pop(str(qq))
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def uid_of(qq: str) -> str | None:
    return _load_index().get(str(qq))


def model_of(qq: str) -> dict | None:
    uid = uid_of(qq)
    if not uid:
        return None
    return userprofile.load(uid)
