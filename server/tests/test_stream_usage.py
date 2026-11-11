# -*- coding: utf-8 -*-
"""网关 SSE usage 解析：真实 usage 优先，缺失时估算并标 estimated。"""

from __future__ import annotations

import json

import httpx


class _SSEStream(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self._data = data

    async def __aiter__(self):
        yield self._data

    async def aclose(self):
        return None


def _install_stream_client(client, sse: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SSEStream(sse),
        )

    client.app.state.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=5
    )


def _account_id(client, headers) -> int:
    return client.get("/v1/auth/me", headers=headers).json()["id"]


def test_stream_usage_from_upstream(client, headers):
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "你"}}]},
        {"choices": [{"index": 0, "delta": {"content": "好"}}]},
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42},
        },
    ]
    sse = b"".join(
        f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8") for item in chunks
    ) + b"data: [DONE]\n\n"
    _install_stream_client(client, sse)

    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "test-model", "stream": True, "messages": [{"role": "user", "content": "写一段"}]},
    )
    assert response.status_code == 200, response.text
    assert response.text.count("data:") >= 3

    with client.app.state.db.session() as session:
        from app.models import UsageEvent

        event = (
            session.query(UsageEvent)
            .filter(
                UsageEvent.account_id == _account_id(client, headers),
                UsageEvent.metric == "model_token",
            )
            .order_by(UsageEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.quantity == 42
        assert event.meta["estimated"] is False
        assert event.meta["route"] == "managed"


def test_stream_usage_estimated_when_missing(client, headers):
    text = "林默" * 200
    chunks = [{"choices": [{"index": 0, "delta": {"content": text}}]}]
    sse = b"".join(
        f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode("utf-8") for item in chunks
    ) + b"data: [DONE]\n\n"
    _install_stream_client(client, sse)

    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "test-model", "stream": True, "messages": [{"role": "user", "content": "继续"}]},
    )
    assert response.status_code == 200, response.text

    with client.app.state.db.session() as session:
        from app.models import UsageEvent

        event = (
            session.query(UsageEvent)
            .filter(
                UsageEvent.account_id == _account_id(client, headers),
                UsageEvent.metric == "model_token",
            )
            .order_by(UsageEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.meta["estimated"] is True
        assert event.quantity > 0
        assert event.meta["completion_tokens"] > 0
