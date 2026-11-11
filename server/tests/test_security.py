# -*- coding: utf-8 -*-
"""安全与运维基线：错误格式、请求 ID、提示词不下发、写操作必须鉴权。"""

from __future__ import annotations


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
