# -*- coding: utf-8 -*-
"""后台套餐管理：改价 / 上下架 / 权益上限，且不被启动种子回滚。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Account, AuditLog, Plan
from app.seed import ensure_plans

from .helpers import db_session


def _promote(app, account_id: int, role: str = "admin") -> None:
    with db_session(app) as session:
        row = session.get(Account, account_id)
        assert row is not None
        row.role = role
        session.commit()


def test_admin_updates_plan_and_public_list_reflects_it(app, client, headers, account):
    _promote(app, account["account"]["id"])

    response = client.patch(
        "/v1/admin/plans/creator",
        headers=headers,
        json={
            "name": "创作版 Pro",
            "price_month_cents": 200,
            "price_year_cents": 2000,
            "active": False,
            "entitlements": {"books_month": 8},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "创作版 Pro"
    assert data["price_month_cents"] == 200
    assert data["price_year_cents"] == 2000
    assert data["active"] is False
    assert data["status"] == "已下架"
    books = next(item for item in data["entitlements"] if item["key"] == "books_month")
    assert books["limit"] == 8

    # 下架后公开套餐列表不再返回
    public = client.get("/v1/plans").json()["plans"]
    assert all(plan["code"] != "creator" for plan in public)

    with db_session(app) as session:
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "plan.update"))
        assert audit is not None
        assert audit.target_id == "creator"


def test_plan_update_rejects_unknown_entitlement(app, client, headers, account):
    _promote(app, account["account"]["id"])
    response = client.patch(
        "/v1/admin/plans/creator",
        headers=headers,
        json={"entitlements": {"not_a_metric": 1}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_entitlement"


def test_support_cannot_update_plan(app, client, headers, account):
    _promote(app, account["account"]["id"], role="support")
    response = client.patch(
        "/v1/admin/plans/creator",
        headers=headers,
        json={"price_month_cents": 1},
    )
    assert response.status_code == 403


def test_seed_does_not_overwrite_admin_edits(app, client):
    """启动初始化只补缺失套餐，不能把后台改过的价格/上下架状态回滚。"""
    with db_session(app) as session:
        plan = session.scalar(select(Plan).where(Plan.code == "creator"))
        assert plan is not None
        plan.price_month_cents = 321
        plan.active = False
        session.commit()

        ensure_plans(session)
        session.refresh(plan)
        assert plan.price_month_cents == 321
        assert plan.active is False
