# -*- coding: utf-8 -*-
"""登录 / 刷新 / 登出。"""

from __future__ import annotations


def test_register_returns_tokens_and_me(client, account):
    assert account["token_type"] == "bearer"
    assert account["access_token"] and account["refresh_token"]
    response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {account['access_token']}"})
    assert response.status_code == 200
    assert response.json()["email"] == "tester@example.com"


def test_login_with_password(client, account):
    response = client.post(
        "/v1/auth/login",
        json={"email": "tester@example.com", "password": "password123"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_wrong_password_rejected(client, account):
    response = client.post(
        "/v1/auth/login",
        json={"email": "tester@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_refresh_rotates_and_invalidates_old_tokens(client, account):
    old_access = account["access_token"]
    old_refresh = account["refresh_token"]

    response = client.post("/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert response.status_code == 200, response.text
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != old_refresh

    # 旧 refresh token 不可再次使用（轮换后吊销）
    replay = client.post("/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh"

    # 旧 access token 所属会话已被吊销
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert me.status_code == 401
    assert me.json()["error"]["code"] == "session_revoked"

    # 新 access token 可用
    me2 = client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"}
    )
    assert me2.status_code == 200


def test_logout_revokes_session(client, account):
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    assert client.post("/v1/auth/logout", headers=headers).status_code == 200
    response = client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_revoked"


def test_duplicate_registration_conflict(client, account):
    response = client.post(
        "/v1/auth/register",
        json={"email": "tester@example.com", "password": "password123"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_exists"


def test_register_requires_email_verification(client):
    client.app.state.settings.email_verification_required = True
    response = client.post(
        "/v1/auth/register",
        json={"email": "verify@example.com", "password": "password123"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending_verification"
    assert body["email"] == "verify@example.com"
    # 测试环境未配置 SMTP，验证链接直接回传，便于本地验证
    assert "verify_url" in body
    token = body["verify_url"].split("token=")[1]

    # 未验证不能登录
    login = client.post(
        "/v1/auth/login",
        json={"email": "verify@example.com", "password": "password123"},
    )
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "email_not_verified"

    # 点击链接完成验证并拿到 token
    verified = client.post("/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["access_token"]

    # 验证后登录成功
    login2 = client.post(
        "/v1/auth/login",
        json={"email": "verify@example.com", "password": "password123"},
    )
    assert login2.status_code == 200


def test_verify_email_invalid_token(client):
    response = client.post("/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_token"


def test_resend_verification_returns_link_for_pending(client):
    client.app.state.settings.email_verification_required = True
    # 注册时已发送过一封验证邮件；本用例验证「链接回显」而非冷却逻辑，
    # 关闭冷却以免被防邮件轰炸的 429 拦截（冷却本身另有安全测试覆盖）。
    client.app.state.settings.email_resend_cooldown_seconds = 0
    reg = client.post(
        "/v1/auth/register",
        json={"email": "resend@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    resend = client.post("/v1/auth/resend-verification", json={"email": "resend@example.com"})
    assert resend.status_code == 200, resend.text
    # 测试环境回传验证链接
    assert "verify_url" in resend.json()


def test_resend_verification_does_not_leak_account_existence(client):
    resend = client.post("/v1/auth/resend-verification", json={"email": "nobody@example.com"})
    assert resend.status_code == 200
    # 不暴露该邮箱是否注册
    assert "verify_url" not in resend.json()
