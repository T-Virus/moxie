# -*- coding: utf-8 -*-
"""SSE 公共封装：统一鉴权流帧加密与响应头。

所有新增事件流都走这里，避免每个端点重复处理 x-payload-sse 与 AAD 路径。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

SSE_POLL_SECONDS = 0.2
SSE_MAX_TICKS = 300  # 单条约 60s；客户端按 since / ready 重连
FEED_POLL_SECONDS = 1.0
FEED_MAX_TICKS = 300  # 聚合流约 5min；只发 refresh，不重复推业务数据


def sse_context(request: Request) -> tuple[Callable[[dict[str, Any]], str], dict[str, str]]:
    """返回 (帧编码器, 响应头)。加密 AAD 固定为当前 GET 路径+查询。"""
    payload_key = getattr(request.state, "payload_key", None)
    crypto = request.app.state.payload_crypto
    encrypted = payload_key is not None
    path_with_query = request.url.path + (f"?{request.url.query}" if request.url.query else "")

    def frame(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if encrypted:
            return crypto.encrypt_sse(payload_key, raw, path_with_query)
        return raw.decode("utf-8")

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    if encrypted:
        headers["X-Payload-Sse"] = "1"
    return frame, headers


def sse_response(stream: Iterator[str], headers: dict[str, str]) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream", headers=headers)
