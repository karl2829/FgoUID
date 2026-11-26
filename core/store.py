# -*- coding: utf-8 -*-
"""运行时数据目录（``<gsuid_core>/data/FGOUID``）与只读数据包 ``data/`` 分开。

``data/fgo.db`` 是构建期产物、随仓库分发、运行时只读；
用户抽卡记录/预热进度这类**会写**的东西一律落在 GsCore 的资源目录里，
这样插件更新（git pull）不会覆盖用户数据。
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def data_dir() -> Path:
    """可写数据目录；没有 GsCore 时退到临时目录（开发期自测用）。"""
    try:
        from gsuid_core.data_store import get_res_path

        p = get_res_path("FGOUID")
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        p = Path(tempfile.gettempdir()) / "FGOUID"
        p.mkdir(parents=True, exist_ok=True)
        return p


def file(name: str) -> Path:
    return data_dir() / name
