# -*- coding: utf-8 -*-
"""安全与运维基线：错误格式、请求 ID、提示词不下发、写操作必须鉴权。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def test_error_response_has_code_and_request_id(client):
    response = client.get("/v1/tasks/does-not-exist")
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "unauthorized"
    assert body["request_id"]
    assert "Traceback" not in response.text


def test_request_id_is_echoed(client):
    response = client.get("/healthz", headers={"x-request-id": "req-test-123"})
    assert response.headers["x-request-id"] == "req-test-123"


def test_traceparent_is_propagated_and_validated(client):
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get(
        "/healthz",
        headers={"traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"},
    )
    assert response.headers["x-trace-id"] == trace_id
    assert response.headers["traceparent"].startswith(f"00-{trace_id}-")

    invalid = client.get("/healthz", headers={"traceparent": "not-a-traceparent"})
    assert invalid.headers["x-trace-id"]
    assert invalid.headers["x-trace-id"] != trace_id


def test_openapi_contains_no_prompt_endpoint(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"].keys()
    assert "/api/prompts" not in paths
    assert not any("prompt" in path for path in paths)
    assert "/v1/chat/completions" in paths


def test_health_and_ready(client):
    healthy = client.get("/healthz")
    assert healthy.status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["database"] is True
    assert ready.json()["redis_backend"] == "fakeredis"


def test_write_endpoints_require_auth(client):
    assert client.post("/v1/devices", json={"device_hash": "x" * 16, "platform": "windows"}).status_code == 401
    assert client.post("/v1/tasks", json={"type": "decompose"}).status_code == 401
    assert client.post("/v1/subscriptions", json={"plan_code": "creator"}).status_code == 401
    assert client.post("/v1/chat/completions", json={}).status_code == 401


def test_strict_csp_on_api_responses(client):
    """普通 API 响应必须是严格 CSP：同源脚本、禁内联脚本、禁插件对象。"""
    resp = client.get("/healthz")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_docs_uses_looser_csp_for_swagger(client):
    """Swagger UI 依赖内联脚本，/docs 与 /openapi.json 不能用 strict CSP。"""
    resp = client.get("/openapi.json")
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp
    # 宽松策略不含 default-src，避免拦掉 Swagger 的内联脚本
    assert "default-src" not in csp


def test_client_ip_only_trusts_proxy_when_enabled():
    """nginx 覆盖 XFF 后，trust_proxy 才允许读取；默认忽略不可信头。"""
    from app.deps import client_ip

    def request(trust: bool, forwarded: str | None):
        headers = {"x-forwarded-for": forwarded} if forwarded else {}
        return SimpleNamespace(
            headers=headers,
            client=SimpleNamespace(host="10.0.0.1"),
            app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(trust_proxy=trust))),
        )

    assert client_ip(request(False, "1.2.3.4")) == "10.0.0.1"
    assert client_ip(request(True, "1.2.3.4, 10.0.0.1")) == "1.2.3.4"
    assert client_ip(request(True, None)) == "10.0.0.1"


def test_payload_body_limit_rejects_chunked_overflow():
    """载荷解密层必须在读取阶段限长，阻断 chunked 绕过。"""
    from app.payload_middleware import PayloadCryptoMiddleware, PayloadTooLarge

    mw = PayloadCryptoMiddleware(
        app=None, settings=SimpleNamespace(max_request_body_bytes=4), crypto=object()
    )
    chunks = iter([{"type": "http.request", "body": b"abc", "more_body": True},
                   {"type": "http.request", "body": b"def", "more_body": False}])

    async def receive():
        return next(chunks)

    with pytest.raises(PayloadTooLarge):
        asyncio.run(mw._read_body(receive))
