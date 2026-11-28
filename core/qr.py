# -*- coding: utf-8 -*-
"""二维码生成：优先 qrcode，其次 segno，都没有就返回 None。"""
from __future__ import annotations

import io


def make_png(text: str, box: int = 8) -> bytes | None:
    try:
        import qrcode  # type: ignore

        img = qrcode.make(text, box_size=box, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass
    try:
        import segno  # type: ignore

        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="png", scale=box, border=2)
        return buf.getvalue()
    except Exception:
        return None
