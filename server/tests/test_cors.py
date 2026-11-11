# -*- coding: utf-8 -*-
"""管理端 CORS：白名单预检、普通请求回显来源、拒绝未知来源。"""

from __future__ import annotations

ADMIN_ORIGIN = "http://127.0.0.1:5180"


def test_cors_preflight_allows_admin_origin(client):
    response = client.options(
        "/v1/admin/users",
        headers={
            "Origin": ADMIN_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-rights-confirmed,content-type",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "x-rights-confirmed" in allowed_headers
    assert "GET" in response.headers["access-control-allow-methods"]


def test_cors_actual_request_echoes_origin_and_request_id(client):
    response = client.get("/healthz", headers={"Origin": "http://localhost:5180"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5180"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in response.headers
    assert response.headers["access-control-allow-origin"] != "*"


def test_cors_rejects_unknown_origin(client):
    response = client.options(
        "/v1/admin/users",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
