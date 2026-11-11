# -*- coding: utf-8 -*-
"""模型代理网关：统一 key、BYOK 不落库不落日志、成本归集、上游错误。"""

from __future__ import annotations

import json

import httpx
import pytest

from app.models import UsageEvent

from .helpers import db_session

UPSTREAM_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
}


def _install_transport(app, handler):
    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_managed_route_uses_server_key_and_attributes_cost(client, headers, app):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=UPSTREAM_RESPONSE)

    _install_transport(app, handler)
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == "ok"
    assert captured["authorization"] == "Bearer server-secret-key"
    assert captured["body"]["model"] == "deepseek-v4-flash"

    with db_session(app) as session:
        event = session.query(UsageEvent).one()
        assert event.metric == "model_token"
        assert event.quantity == 30
        assert event.meta["byok"] is False
        assert event.meta["route"] == "managed"


def test_byok_key_is_not_persisted_or_logged(client, headers, app, caplog):
    captured = {}
    secret = "user-byok-secret-key-123"

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json=UPSTREAM_RESPONSE)

    caplog.set_level("DEBUG")
    _install_transport(app, handler)
    response = client.post(
        "/v1/chat/completions",
        headers={**headers, "x-byok-key": secret},
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 200
    assert captured["authorization"] == f"Bearer {secret}"

    with db_session(app) as session:
        event = session.query(UsageEvent).one()
        stored = json.dumps(event.meta, ensure_ascii=False)
        assert event.meta["byok"] is True
        assert event.meta["route"] == "byok"
        assert secret not in stored

    assert secret not in caplog.text


def test_upstream_5xx_returns_safe_error(client, headers, app):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream internal detail that should not leak keys")

    _install_transport(app, handler)
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "upstream_error"
    assert "Bearer" not in body["error"]["message"]


def test_gateway_requires_auth(client):
    response = client.post(
        "/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
