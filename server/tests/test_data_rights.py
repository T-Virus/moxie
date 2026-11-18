# -*- coding: utf-8 -*-
"""用户数据权利：导出、注销申请、到期清除与对象存储级联。"""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import select

from app.db import utcnow
from app.models import Account, AccountDeletionRequest, AuditLog, StoredObject
from app.services.data_rights import purge_due_deletions


def _register(client, email: str):
    response = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(payload: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {payload['access_token']}"}


def test_export_includes_objects_and_redacts_secrets(client, app, account, headers):
    account_id = account["account"]["id"]
    key = f"uploads/{account_id}/export-sample.txt"
    app.state.storage.put_bytes(key, "正文内容".encode("utf-8"), "text/plain; charset=utf-8")

    response = client.get("/v1/me/export", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["schema_version"] == 1
    assert data["account"]["id"] == account_id
    assert data["account"].get("password_hash") in (None, "[redacted]")
    assert any(
        item["key"] == key and item.get("content") == "正文内容"
        for item in data["objects"]
    )
    # 密码哈希不得出现在任何导出片段
    exported = json.dumps(data, ensure_ascii=False)
    assert "scrypt$" not in exported


def test_delete_requires_password_and_explicit_confirmation(client, account, headers):
    wrong_password = client.post(
        "/v1/me/delete",
        json={"password": "wrong-password", "confirmation": "DELETE_MY_ACCOUNT"},
        headers=headers,
    )
    assert wrong_password.status_code == 401

    wrong_confirmation = client.post(
        "/v1/me/delete",
        json={"password": "password123", "confirmation": "just-do-it"},
        headers=headers,
    )
    assert wrong_confirmation.status_code == 422


def test_deletion_request_revokes_sessions_and_purges_on_due(client, app, account, headers):
    account_id = account["account"]["id"]
    key = f"uploads/{account_id}/purge-sample.txt"
    app.state.storage.put_bytes(key, b"purge me", "text/plain; charset=utf-8")

    response = client.post(
        "/v1/me/delete",
        json={"password": "password123", "confirmation": "DELETE_MY_ACCOUNT"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["account_id"] == account_id

    # 旧会话立即失效
    assert client.get("/v1/auth/me", headers=headers).status_code == 401

    with app.state.db.session() as session:
        row = session.scalar(
            select(AccountDeletionRequest).where(AccountDeletionRequest.account_id == account_id)
        )
        assert row is not None and row.status == "pending"
        assert session.get(Account, account_id).status == "closing"

    due = utcnow() + timedelta(days=30)
    with app.state.db.session() as session:
        assert purge_due_deletions(session, app.state.settings, now=due) == 1

    with app.state.db.session() as session:
        assert session.get(Account, account_id) is None
        assert session.scalar(
            select(AccountDeletionRequest.id).where(AccountDeletionRequest.account_id == account_id)
        ) is None
        assert session.scalar(select(StoredObject.key).where(StoredObject.key == key)) is None
        assert session.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "account.deleted",
                AuditLog.target_id == str(account_id),
            )
        ) is not None

    assert not app.state.storage.exists(key)


def test_admin_can_cancel_or_immediately_purge_deletion(client, app, account, headers):
    admin_id = account["account"]["id"]
    with app.state.db.session() as session:
        session.get(Account, admin_id).role = "admin"
        session.commit()

    target = _register(client, "deletion-target@example.com")
    target_id = target["account"]["id"]
    target_headers = _headers(target)

    first = client.post(
        "/v1/me/delete",
        json={"password": "password123", "confirmation": "DELETE_MY_ACCOUNT"},
        headers=target_headers,
    )
    assert first.status_code == 200, first.text
    request_id = first.json()["id"]

    cancelled = client.post(f"/v1/admin/account-deletions/{request_id}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    with app.state.db.session() as session:
        assert session.get(Account, target_id).status == "active"

    # 重新登录后再次申请，由管理员立即清除
    relogin = client.post(
        "/v1/auth/login",
        json={"email": "deletion-target@example.com", "password": "password123"},
    )
    assert relogin.status_code == 200, relogin.text
    second = client.post(
        "/v1/me/delete",
        json={"password": "password123", "confirmation": "DELETE_MY_ACCOUNT"},
        headers=_headers(relogin.json()),
    )
    assert second.status_code == 200, second.text
    request_id = second.json()["id"]

    purged = client.post(f"/v1/admin/account-deletions/{request_id}/purge", headers=headers)
    assert purged.status_code == 200, purged.text
    assert purged.json()["deleted"] is True
    with app.state.db.session() as session:
        assert session.get(Account, target_id) is None
