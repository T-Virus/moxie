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
