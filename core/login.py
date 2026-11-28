# -*- coding: utf-8 -*-
"""FGO 国服扫码登录 + 数据同步（插件内实现）。

流程：二维码 → 轮询授权 → B站 SDK 换 access_key → 游戏登录 → topLogin 全量
      → 遍历卡池取召唤记录 → 计算汇总 → 存 data/FGOUID/users/<uid>.json.gz

安全约定：
- 凭据只存在内存里，不落盘、不进日志
- 超时 5 分钟自动放弃；同一用户 10 分钟内只能发起一次
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
PROTO_PATH = PKG / "data" / "fgo_protocol.json"
SDK_BASE = "https://line3-sdk-center-login-sh.biligame.net"
GAME_BASE = "https://line3-s2-bili-fate.bilibiligame.net"
OS_STR = "Android OS 9 / API-28 (SP1A.210812.016/G998BXXU4BULF)"
PTYPE = "samsung SM-G998B"
UA_SDK = "Mozilla/5.0 BSGameSDK"
UA_GAME = "Dalvik/2.1.0 (Linux; U; Android 9)"

# 直连，绕过系统代理
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def profile() -> dict:
    return json.loads(PROTO_PATH.read_text(encoding="utf-8"))


def _post(url: str, fields: dict, timeout: int = 20) -> bytes:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data, headers={
        "User-Agent": UA_SDK, "Content-Type": "application/x-www-form-urlencoded"})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read()


def _decode(raw: bytes) -> dict:
    import base64
    import zlib

    for fn in (None, base64.b64decode, lambda b: base64.b64decode(b + b"=="),
               lambda b: zlib.decompress(base64.b64decode(b))):
        try:
            blob = raw if fn is None else fn(raw)
            return json.loads(blob.decode("utf-8"))
        except Exception:
            continue
    raise ValueError("响应无法解析")


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _sign(params: dict, key: str) -> dict:
    items = sorted((k, str(v)) for k, v in params.items() if v != "")
    params["sign"] = _md5("".join(v for _, v in items) + key)
    return params


def issue_qr() -> tuple[str, str]:
    """返回 (ticket, 二维码内容)。"""
    p = profile()
    params = {
        "merchant_id": p["sdk_base"]["merchant_id"], "game_id": p["sdk_base"]["game_id"],
        "app_id": p["sdk_base"]["app_id"], "server_id": p["sdk_base"]["server_id"],
        "version": p["sdk_base"]["version"], "sdk_type": p["sdk_base"]["sdk_type"],
        "action": "create", "type": "web", "state": str(uuid.uuid4()),
        "ticket": "", "access_key": "", "uid": "", "online": "1", "app_ver": "0",
    }
    params = _sign(params, p["sdk_key"])
    raw = _post(f"{SDK_BASE}/api/createQrCode", params)
    data = _decode(raw)
    ticket = str(data.get("ticket") or (data.get("data") or {}).get("ticket") or "")
    if not ticket:
        raise ValueError(f"创建二维码失败：{str(data)[:120]}")
    return ticket, f"https://game.bilibili.com/sdk/scanH5/?ticket={ticket}&fromNative=b"


def poll_ticket(ticket: str) -> dict:
    p = profile()
    params = {"ticket": ticket, "merchant_id": p["sdk_base"]["merchant_id"],
              "game_id": p["sdk_base"]["game_id"], "app_id": p["sdk_base"]["app_id"],
              "server_id": p["sdk_base"]["server_id"], "version": p["sdk_base"]["version"],
              "sdk_type": p["sdk_base"]["sdk_type"], "action": "poll"}
    params = _sign(params, p["sdk_key"])
    return _decode(_post(f"{SDK_BASE}/api/getQrCodeStatus", params))


def login_game(access_key: str, uid: str, nickname: str = "") -> dict:
    """用 access_key 换游戏会话并 topLogin，返回 (session, payload)。"""
    p = profile()
    base = GAME_BASE
    device = uuid.uuid4().hex
    common = {"deviceid": device, "os": OS_STR, "ptype": PTYPE, "appVer": p["version"],
              "dateVer": "0", "lastAccessTime": str(int(time.time())), "try": "", "dataVer": "0",
              "developmentAuthCode": p["development_code"]}

    def game(path: str, fields: dict) -> dict:
        url = base + path
        req = urllib.request.Request(url, urllib.parse.urlencode(fields).encode(),
                                     headers={"User-Agent": UA_GAME,
                                              "X-Unity-Version": "2019.4.40f1",
                                              "Content-Type": "application/x-www-form-urlencoded"})
        with _OPENER.open(req, timeout=30) as r:
            return _decode(r.read())

    member = game("/rongame_beta/rgfate/60_member/logintomembercenter.php", dict(
        common, t="22360", v="1.0.1", s="1", mac="0", imei="", bundleid="com.bilibili.fatego",
        username=nickname, type="token", rkuid=str(uid), access_token=access_key,
        rksdkid="1", rkchannel="24", version="0"))
    info = member.get("success") or {}
    if not info.get("rguid"):
        raise ValueError(f"SDK 换游戏账号失败：{str(member)[:120]}")
    for k in ("dateVer", "dataVer"):
        common[k] = str(info.get(k, "0"))
    login = game("/rongame_beta/rgfate/60_1001/login.php", dict(
        common, rgsid="1001", rguid=info["rguid"], rgusk=info["rgusk"], idfa="", v="1.0.1",
        mac="0", imei="", type="login", nickname=str(info["rgusk"])[:10], rkchannel="24",
        assetbundleFolder="", userAgent="1", t="20399", s="1", rksdkid="1"))
    sess = login.get("success") or {}
    if not sess.get("sguid"):
        raise ValueError(f"游戏登录失败：{str(login)[:120]}")
    st = {"sguid": str(sess["sguid"]), "sgusk": str(sess["sgusk"]),
          "sgtype": str(sess.get("sgtype", "")), "sgtag": str(sess.get("sgtag", "")),
          "dateVer": common["dateVer"], "dataVer": common["dataVer"], "deviceid": device}
    return st


def ac_action(st: dict, key: str, usk: str, extra: dict | None = None) -> tuple[dict, str]:
    p = profile()
    params = {"ac": "action", "key": key, "deviceid": st["deviceid"], "os": OS_STR, "ptype": PTYPE,
              "usk": usk, "umk": "", "rgsid": 1001, "rkchannel": 24, "cPlat": 3, "uPlat": 3,
              "userId": st["sguid"], "appVer": p["version"], "dateVer": st["dateVer"],
              "lastAccessTime": str(int(time.time())), "idempotencyKey": str(uuid.uuid4()),
              "developmentAuthCode": p["development_code"], "userAgent": 1,
              "dataVer": st["dataVer"], **(extra or {})}
    q = urllib.parse.urlencode({"_userId": st["sguid"], "_key": key,
                                "_clientLocalTime": f"{time.time() % 1000:.4f}"})
    url = f"{GAME_BASE}/rongame_beta/rgfate/60_1001/ac.php?{q}"
    req = urllib.request.Request(url, urllib.parse.urlencode(params).encode(), headers={
        "User-Agent": UA_GAME, "X-Unity-Version": "2019.4.40f1",
        "Content-Type": "application/x-www-form-urlencoded"})
    with _OPENER.open(req, timeout=40) as r:
        root = _decode(r.read())
    row = next((x for x in (root.get("response") or []) if x.get("nid") == key),
               (root.get("response") or [{}])[0])
    nu = row.get("usk")
    return root, (_md5(p["session_prefix"] + nu) if nu else usk)


def initial_usk(st: dict) -> str:
    return _md5(profile()["session_prefix"] + st["sgusk"])


async def fetch_all(st: dict, delay: float = 0.45, limit: int = 0,
                    progress=None) -> tuple[dict, dict]:
    """拉全量 + 所有卡池记录，返回 (payload_replaced, histories)。"""
    proto = profile()
    root, usk = await asyncio.to_thread(ac_action, st, "toplogin", initial_usk(st))
    cache = root.get("cache") or {}
    rep = cache.get("replaced") or {}
    rep["__updated__"] = cache.get("updated") or {}
    pools = [(int(r["gachaId"]), int(r.get("num") or 0))
             for r in (rep.get("userGacha") or []) if int(r.get("num") or 0) > 0]
    pools.sort(key=lambda x: -x[1])
    if limit:
        pools = pools[:limit]
    histories: dict[str, list[dict]] = {}
    for i, (gid, _n) in enumerate(pools, 1):
        try:
            r, usk = await asyncio.to_thread(ac_action, st, "gachadrawhistory", usk,
                                             {"gachaId": str(gid)})
            rows = ((r.get("cache") or {}).get("replaced") or {}).get("userGachaDrawHistory") or []
            if rows:
                histories[str(gid)] = rows
        except Exception:
            pass
        if progress and (i % 25 == 0 or i == len(pools)):
            await progress(i, len(pools), len(histories))
        await asyncio.sleep(delay)
    return rep, histories
