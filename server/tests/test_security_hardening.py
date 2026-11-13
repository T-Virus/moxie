# -*- coding: utf-8 -*-
"""输入 trim、全局限流、登录失败锁定等安全加固测试。"""

from __future__ import annotations

from app.models import Account
from app.schemas import AgentCollectionsUpdateRequest, RegisterRequest


def test_body_strings_trimmed_but_password_preserved(client):
    # 邮箱首尾空格被统一清洗；密码属于敏感字段，不做静默改写
    registered = client.post(
        "/v1/auth/register",
        json={"email": "  Trim@Example.com  ", "password": "  spaced password  "},
    )
    assert registered.status_code == 201, registered.text

    ok = client.post(
        "/v1/auth/login", json={"email": "trim@example.com", "password": "  spaced password  "}
    )
    assert ok.status_code == 200, ok.text

    # 密码若被误 trim，下面这次也会成功，属于静默降低口令强度
    stripped = client.post(
        "/v1/auth/login", json={"email": "trim@example.com", "password": "spaced password"}
    )
    assert stripped.status_code == 401


def test_nested_collection_strings_trimmed():
    model = AgentCollectionsUpdateRequest(
        characters=[{"name": "  张三  ", "desc": "  描述  ", "aliases": ["  别名  "]}]
    )
    assert model.characters[0] == {"name": "张三", "desc": "描述", "aliases": ["别名"]}


def test_query_param_trim(client, headers, app, account):
    with app.state.db.session() as session:
        session.get(Account, account["account"]["id"]).role = "admin"
        session.commit()
    # list_users 内部不做 trim，只有全局中间件生效才能命中
    response = client.get(
        "/v1/admin/users", headers=headers, params={"q": "  tester@example.com  "}
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1


def test_global_rate_limit_returns_429_with_retry_after(client, app):
    app.state.settings.rate_limit_enabled = True
    app.state.settings.global_rate_limit_per_minute = 2
    app.state.limiter.reset("global:testclient")

    first = client.get("/v1/plans")
    second = client.get("/v1/plans")
    limited = client.get("/v1/plans")
    assert first.status_code != 429 and second.status_code != 429
    assert limited.status_code == 429, limited.text
    assert limited.json()["error"]["code"] == "rate_limited"
    assert limited.headers.get("retry-after")


def test_login_failure_lock(client, app):
    registered = client.post(
        "/v1/auth/register", json={"email": "lock@example.com", "password": "password123"}
    )
    assert registered.status_code == 201, registered.text

    app.state.settings.login_failure_limit = 2
    app.state.limiter.reset("login_fail:lock@example.com")
    for _ in range(2):
        wrong = client.post(
            "/v1/auth/login", json={"email": "lock@example.com", "password": "wrong-password"}
        )
        assert wrong.status_code == 401, wrong.text

    # 锁定后即便输入正确密码也拒绝，并给出重试时间
    blocked = client.post(
        "/v1/auth/login", json={"email": "lock@example.com", "password": "password123"}
    )
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["error"]["code"] == "too_many_attempts"
    assert blocked.headers.get("retry-after")

    # 清零后可正常登录
    app.state.limiter.reset("login_fail:lock@example.com")
    recovered = client.post(
        "/v1/auth/login", json={"email": "lock@example.com", "password": "password123"}
    )
    assert recovered.status_code == 200, recovered.text


def test_ip_rate_limit_ignores_spoofed_xff(client, app):
    # trust_proxy 默认关闭：伪造 X-Forwarded-For 不应让每次请求"换 IP"从而
    # 绕过限流，否则 IP 维度的限流与失败锁定可被轻易绕过（DDoS / 撞库防护失效）。
    app.state.limiter.reset("register:testclient")
    codes = []
    for i in range(12):  # register_rate_limit_per_minute 默认 10
        r = client.post(
            "/v1/auth/register",
            json={
                "email": f"xff{i}@example.com",
                "password": "password123",
                "phone": f"1390000{i:04d}",
            },
            headers={"X-Forwarded-For": "9.9.9.9"},
        )
        codes.append(r.status_code)
    assert 429 not in codes[:10], codes
    assert 429 in codes, codes


def test_large_request_body_rejected(client):
    # 超过 4MB 的请求体直接 413（Content-Length 路径）
    big = "x" * (5 * 1024 * 1024)
    r = client.post(
        "/v1/auth/login",
        content=big,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413, (r.status_code, r.text)


def test_security_headers_present(client):
    # 传输 / UI 边界：统一安全响应头应覆盖所有响应
    r = client.get("/docs")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    csp = r.headers.get("Content-Security-Policy") or ""
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    # HSTS 仅在真实 HTTPS 连接下下发，本地 http 测试不应出现
    assert "Strict-Transport-Security" not in r.headers
