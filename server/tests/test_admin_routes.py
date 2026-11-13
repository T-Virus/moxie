# -*- coding: utf-8 -*-
"""管理端路由注册顺序回归：静态段不能被动态段抢先匹配。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Account


def _promote(app, account_id: int) -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = "admin"
        session.commit()


def test_delete_user_by_email_is_not_shadowed(client, headers, app, account):
    """DELETE /users/by-email 曾排在 /users/{account_id} 之后，被动态段吞掉返回 422。"""
    _promote(app, account["account"]["id"])

    created = client.post(
        "/v1/auth/register",
        json={"email": "route-check@example.com", "password": "password123"},
    )
    assert created.status_code == 201, created.text

    # DELETE 携带 JSON body 需用 TestClient.request（delete 不支持 json= 关键字）
    resp = client.request(
        "DELETE",
        "/v1/admin/users/by-email",
        json={"email": "route-check@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert resp.json()["email"] == "route-check@example.com"

    with app.state.db.session() as session:
        assert (
            session.scalar(
                select(Account.id).where(Account.email == "route-check@example.com")
            )
            is None
        )


def test_delete_user_by_id_still_works(client, headers, app, account):
    """前置静态路由后，整数 id 的动态路由仍需正常。"""
    _promote(app, account["account"]["id"])

    created = client.post(
        "/v1/auth/register",
        json={"email": "route-by-id@example.com", "password": "password123"},
    )
    assert created.status_code == 201, created.text
    target_id = created.json()["account"]["id"]

    resp = client.delete(f"/v1/admin/users/{target_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True, "id": target_id}

    with app.state.db.session() as session:
        assert (
            session.scalar(select(Account.id).where(Account.id == target_id)) is None
        )
