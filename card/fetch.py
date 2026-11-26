# -*- coding: utf-8 -*-
"""卡面素材：随仓库附带的小图标 + 按需拉取的大图（立绘/羁绊礼装/技能图标）。

分层：
  - ``card/assets/``  随插件分发的小素材（职阶图标、星级、徽标、指令卡，约 800KB）
  - ``<数据目录>/FGOUID/art/``  运行时下载并缓存的立绘/羁绊礼装/技能图标

立绘约 500KB、羁绊礼装约 600KB、技能图标约 20KB；945 个从者全量约 1GB，
所以只在渲染某张卡时才拉，并做容量上限 + LRU 淘汰。
"""
from __future__ import annotations

import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLED = HERE / "assets"

SKILL_HOSTS = ("CN", "JP")

# 模板里会出现、但素材库里没有的名字 → 退到最接近的现成图标
ALIASES = {
    "badge_0.png": "badge_1.png",          # 稀有度 0（安哥拉曼纽、E-玛丽等）
    "beasteresh_gold.png": "beast_gold.png",
    "beastiv_gold.png": "beast_gold.png",
    "unknown_gold.png": "beast_gold.png",
    "unknown_bronze.png": "beast_gold.png",
}
UA = {"User-Agent": "Mozilla/5.0 (compatible; FGOUID/0.1)"}
CACHE_LIMIT_MB = int(os.environ.get("FGOUID_ART_CACHE_MB", "300"))


def cache_dir() -> Path:
    try:
        from gsuid_core.data_store import get_res_path

        p = get_res_path("FGOUID/art")
    except Exception:
        p = Path(tempfile.gettempdir()) / "FGOUID" / "art"
        p.mkdir(parents=True, exist_ok=True)
    return p


def _url_for(name: str, data: dict) -> str:
    if name.startswith("art_"):
        return data.get("art_url") or ""
    if name.startswith("bond_ce_"):
        return (data.get("bond") or {}).get("img_url") or ""
    if name.startswith("skill_"):
        return ""
    return ""


def _quote_url(url: str) -> str:
    """Atlas/jsdelivr 的路径里有中文和全角符号，urllib 只吃 ASCII。"""
    return urllib.parse.quote(url, safe=":/?=@&%~+,;[]!$&'()*")


def _download(url: str, dest: Path, timeout: int = 20) -> bool:
    if not url:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(_quote_url(url), headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            tmp.write_bytes(r.read())
        tmp.replace(dest)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def _evict_if_needed() -> None:
    """超过容量上限就按 mtime 淘汰最旧的缓存文件。"""
    d = cache_dir()
    try:
        files = sorted((f for f in d.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        limit = CACHE_LIMIT_MB * 1024 * 1024
        for f in files:
            if total <= limit:
                break
            size = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= size
    except Exception:
        pass


def ensure(name: str, data: dict) -> bytes | None:
    """取一个素材：先看随包小素材，再看缓存，最后按 URL 下载。"""
    bundled = BUNDLED / name
    if bundled.is_file():
        return bundled.read_bytes()
    alias = ALIASES.get(name)
    if alias and (BUNDLED / alias).is_file():
        return (BUNDLED / alias).read_bytes()

    cached = cache_dir() / name
    if cached.is_file():
        return cached.read_bytes()

    data = data or {}
    url = _url_for(name, data)
    if not url and name.startswith("skill_"):
        # 技能图标按国服/日服 CDN 依次试
        for region in SKILL_HOSTS:
            if _download(f"https://static.atlasacademy.io/{region}/SkillIcons/{name}", cached):
                _evict_if_needed()
                return cached.read_bytes()
        return None

    if _download(url, cached):
        _evict_if_needed()
        return cached.read_bytes()
    return None


def extra_images(data: dict, names: list[str], workers: int = 4) -> dict[str, bytes]:
    """把模板里 ``../assets/<name>`` 形式的引用解析成 {src: bytes}。

    冷启动要下 3~5 个文件（立绘/羁绊礼装/技能图标），串行要十几秒，
    所以这里并发下载（I/O 密集，4 线程足够，也避免打爆小服务器）。
    """
    from concurrent.futures import ThreadPoolExecutor

    want = [n for n in names if not (BUNDLED / n).is_file()
            and not ALIASES.get(n) and not (cache_dir() / n).is_file()]
    if want:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda n: ensure(n, data), want))

    out: dict[str, bytes] = {}
    for name in names:
        if (BUNDLED / name).is_file():
            continue  # 随包素材由 collect_images 自己读盘
        blob = ensure(name, data)
        if blob:
            out[f"../assets/{name}"] = blob
    return out


def ensure_remote(name: str, url: str, timeout: int = 25) -> bytes | None:
    """按名字 + 外链取图（卡池横幅这类不属于立绘/技能图标的素材）。

    URL 里带中文，所以统一 quote；缓存与立绘共用 ``data/FGOUID/art``，
    同样吃 300MB 上限的 LRU。
    """
    if not url:
        return None
    cached = cache_dir() / name
    if cached.is_file():
        return cached.read_bytes()
    if _download(url, cached, timeout=timeout):
        _evict_if_needed()
        return cached.read_bytes()
    return None


def remote_images(mapping: dict[str, str], workers: int = 4) -> dict[str, bytes]:
    """{缓存名: 外链} → {``../assets/<缓存名>``: bytes}，并发下载。"""
    from concurrent.futures import ThreadPoolExecutor

    want = [(n, u) for n, u in mapping.items() if u and not (cache_dir() / n).is_file()]
    if want:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda kv: ensure_remote(*kv), want))

    out: dict[str, bytes] = {}
    for name, url in mapping.items():
        blob = ensure_remote(name, url) if url else None
        if blob:
            out[f"../assets/{name}"] = blob
    return out


def warm(names: list[str], data: dict) -> int:
    """预热一组素材（定时任务用），返回成功条数。"""
    n = 0
    for name in names:
        t0 = time.time()
        if ensure(name, data) is not None:
            n += 1
        if time.time() - t0 > 30:  # 单个别卡太久就放弃，避免任务堆积
            break
    return n
