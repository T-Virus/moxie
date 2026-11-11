# -*- coding: utf-8 -*-
"""应用层加密公钥：客户端用它完成 ECDH 会话派生。

只返回公钥与算法标识，不包含任何私钥或会话密钥。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/crypto", tags=["crypto"])


@router.get("/public-key")
def payload_public_key(request: Request):
    crypto = request.app.state.payload_crypto
    return crypto.public_key_payload()
