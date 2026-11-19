# -*- coding: utf-8 -*-
"""忘记密码 / 重置密码 / 修改密码全链路。"""

from __future__ import annotations

from datetime import timedelta

from app.db import utcnow
from app.models import Account, PasswordResetToken

FORGOT = "/v1/auth/forgot-password"
RESET = "/v1/auth/reset-password"
CHANGE = "/v1/auth/change-password"
LOGIN = "/v1/auth/login"


def _register(client, email: str, password: str = "password123") -> dict:
    resp = client.post("/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, email: str, password: str):
    return client.post(LOGIN, json={"email": email, "password": password})


def _token_from(resp) -> str:
    body = resp.json()
    url = body.get("reset_url")
    assert url, f"测试环境无 SMTP 时应回传 reset_url：{body}"
    return url.split("token=", 1)[1]


def test_forgot_then_reset_changes_password(client, account):
    resp = client.post(FORGOT, json={"email": "  TESTER@Example.com  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"
    token = _token_from(resp)

    # 重置前旧密码可用
    assert _login(client, "tester@example.com", "password123").status_code == 200

    reset = client.post(RESET, json={"token": token, "new_password": "newpassword456"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["ok"] is True

    assert _login(client, "tester@example.com", "password123").status_code == 401
    assert _login(client, "tester@example.com", "newpassword456").status_code == 200

    # 令牌一次性：重复使用 409
    again = client.post(RESET, json={"token": token, "new_password": "another123"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "token_used"


def test_forgot_password_hides_account_existence(client, account):
    known = client.post(FORGOT, json={"email": "tester@example.com"})
    unknown = client.post(FORGOT, json={"email": "nobody-here@example.com"})
    assert known.status_code == 200 and unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]
    assert "reset_url" not in unknown.json()


def test_forgot_password_channel_separates_web_and_admin_links(client, app, account):
    """管理端发起的重置走 /admin 的 hash 路由，用户端走 history 路由，互不串线。"""
    settings = app.state.settings
    (
        original_client,
        original_admin,
        original_cooldown,
    ) = (
        settings.app_client_base_url,
        settings.app_admin_base_url,
        settings.password_reset_cooldown_seconds,
    )
    settings.app_client_base_url = "http://web.example:5190"
    settings.app_admin_base_url = "http://web.example:5180/admin"
    settings.password_reset_cooldown_seconds = 0
    try:
        web = client.post(
            FORGOT, json={"email": "tester@example.com", "channel": "web"}
        )
        assert web.status_code == 200, web.text
        web_url = web.json()["reset_url"]
        assert web_url.startswith("http://web.example:5190/reset-password?token=")
        assert "/#/" not in web_url

        admin = client.post(
            FORGOT, json={"email": "tester@example.com", "channel": "admin"}
        )
        assert admin.status_code == 200, admin.text
        admin_url = admin.json()["reset_url"]
        assert admin_url.startswith("http://web.example:5180/admin/#/reset-password?token=")
        assert "/admin/" in admin_url
    finally:
        settings.app_client_base_url = original_client
        settings.app_admin_base_url = original_admin
        settings.password_reset_cooldown_seconds = original_cooldown


def test_forgot_password_rejects_unknown_channel(client, account):
    resp = client.post(FORGOT, json={"email": "tester@example.com", "channel": "hacker"})
    assert resp.status_code == 422


def test_forgot_password_send_cooldown(client, account):
    assert client.post(FORGOT, json={"email": "tester@example.com"}).status_code == 200
    second = client.post(FORGOT, json={"email": "tester@example.com"})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "too_frequent"


def test_reset_rejects_expired_token(client, app, account):
    token = _token_from(client.post(FORGOT, json={"email": "tester@example.com"}))
    with app.state.db.session() as session:
        row = session.query(PasswordResetToken).order_by(PasswordResetToken.id.desc()).first()
        row.expires_at = utcnow() - timedelta(minutes=1)
        session.commit()

    resp = client.post(RESET, json={"token": token, "new_password": "newpassword456"})
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "token_expired"


def test_reset_rejects_invalid_and_weak(client, account):
    bad = client.post(RESET, json={"token": "x" * 32, "new_password": "newpassword456"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_token"

    weak = client.post(
        RESET, json={"token": "x" * 32, "new_password": "short"}
    )
    assert weak.status_code == 422


def test_reset_also_marks_email_verified(client, app, account):
    with app.state.db.session() as session:
        session.get(Account, account["account"]["id"]).email_verified_at = None
        session.commit()
    token = _token_from(client.post(FORGOT, json={"email": "tester@example.com"}))
    assert client.post(RESET, json={"token": token, "new_password": "newpassword456"}).status_code == 200
    with app.state.db.session() as session:
        assert session.get(Account, account["account"]["id"]).email_verified_at is not None


def test_reset_activates_pending_account(client, app, account):
    """待验证邮箱的账号重置密码后应可直接登录（令牌已证明邮箱归属）。"""
    with app.state.db.session() as session:
        row = session.get(Account, account["account"]["id"])
        row.status = "pending"
        row.email_verified_at = None
        session.commit()

    token = _token_from(client.post(FORGOT, json={"email": "tester@example.com"}))
    assert client.post(RESET, json={"token": token, "new_password": "newpassword456"}).status_code == 200

    with app.state.db.session() as session:
        row = session.get(Account, account["account"]["id"])
        assert row.status == "active"
        assert row.email_verified_at is not None
    assert _login(client, "tester@example.com", "newpassword456").status_code == 200


def test_change_password_revokes_other_sessions(client, account, headers):
    second = _login(client, "tester@example.com", "password123").json()

    wrong = client.post(
        CHANGE, json={"old_password": "not-my-password", "new_password": "newpassword456"}, headers=headers
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_password"

    same = client.post(
        CHANGE, json={"old_password": "password123", "new_password": "password123"}, headers=headers
    )
    assert same.status_code == 422
    assert same.json()["error"]["code"] == "same_password"

    ok = client.post(
        CHANGE, json={"old_password": "password123", "new_password": "newpassword456"}, headers=headers
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["revoked_sessions"] >= 1

    assert _login(client, "tester@example.com", "password123").status_code == 401
    assert _login(client, "tester@example.com", "newpassword456").status_code == 200

    # 另一台设备的 refresh token 已被吊销，当前会话仍可用
    revoked = client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert revoked.status_code == 401
    assert client.get("/v1/auth/me", headers=headers).status_code == 200


def test_admin_can_send_reset_mail(client, app, account, headers):
    with app.state.db.session() as session:
        session.get(Account, account["account"]["id"]).role = "admin"
        session.commit()
    target = _register(client, "reset-target@example.com")

    resp = client.post(
        f"/v1/admin/users/{target['account']['id']}/reset-password", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is False  # 测试环境未配置 SMTP
    assert body["reset_url"]

    # 非管理员不可代发
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}
    denied = client.post(
        f"/v1/admin/users/{target['account']['id']}/reset-password", headers=target_headers
    )
    assert denied.status_code == 403
