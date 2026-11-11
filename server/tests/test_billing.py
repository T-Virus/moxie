# -*- coding: utf-8 -*-
"""订阅状态机、mock 支付回调幂等、续费与到期。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import utcnow
from app.errors import ApiError
from app.models import Account, Entitlement, Order, Plan, Subscription, WebhookEvent
from app.services import subscription as subsvc

from .helpers import db_session, subscribe


def _seed_legacy_plan(session, *, active: bool) -> Plan:
    """模拟线上遗留的工作室版套餐（新库不会再种出来）。"""
    plan = Plan(
        code="studio_managed",
        name="工作室版",
        price_month_cents=19900,
        price_year_cents=199000,
        currency="CNY",
        features={"byok": True, "managed": True, "support": "priority"},
        active=active,
    )
    session.add(plan)
    session.flush()
    for key, limit_value, unit in (
        ("books_month", 20, "book"),
        ("adapt_chapters", 800, "chapter"),
        ("review_month", 20, "call"),
        ("concurrency", 8, "count"),
        ("seats", 10, "seat"),
        ("managed_chars", 5_000_000, "char"),
        ("storage_gb", 100, "gb"),
    ):
        session.add(
            Entitlement(
                plan_id=plan.id,
                key=key,
                limit_value=limit_value,
                unit=unit,
                reset_period="month",
            )
        )
    session.commit()
    return plan


def test_plans_are_public(client):
    response = client.get("/v1/plans")
    assert response.status_code == 200
    plans = response.json()["plans"]
    assert [plan["code"] for plan in plans] == ["experience", "creator", "professional"]
    assert [plan["price_month_cents"] for plan in plans] == [990, 2990, 6990]
    assert [plan["price_year_cents"] for plan in plans] == [9900, 29900, 69900]
    assert all(plan["currency"] == "CNY" for plan in plans)
    matrix = {
        plan["code"]: {item["key"]: item["limit"] for item in plan["entitlements"]}
        for plan in plans
    }
    assert matrix["experience"]["books_month"] == 1
    assert matrix["experience"]["adapt_chapters"] == 20
    assert matrix["experience"]["managed_chars"] == 50000
    assert matrix["creator"]["books_month"] == 5
    assert matrix["creator"]["adapt_chapters"] == 120
    assert matrix["creator"]["managed_chars"] == 500000
    assert matrix["professional"]["books_month"] == 15
    assert matrix["professional"]["adapt_chapters"] == 400
    assert matrix["professional"]["managed_chars"] == 2000000
    assert [matrix[code]["concurrency"] for code in ("experience", "creator", "professional")] == [1, 2, 4]


def test_inactive_plan_cannot_be_ordered(app, client, headers):
    with db_session(app) as session:
        _seed_legacy_plan(session, active=False)
    response = client.post(
        "/v1/subscriptions",
        headers={**headers, "Idempotency-Key": "inactive-plan"},
        json={"plan_code": "studio_managed", "cycle": "month", "provider": "mock"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "plan_unavailable"


def test_admin_plan_list_marks_inactive(app, client, headers, account):
    with db_session(app) as session:
        _seed_legacy_plan(session, active=False)
        row = session.get(Account, account["account"]["id"])
        row.role = "admin"
        session.commit()
    response = client.get("/v1/admin/plans", headers=headers)
    assert response.status_code == 200
    items = {item["code"]: item for item in response.json()["plans"]}
    for code in ("experience", "creator", "professional"):
        assert items[code]["active"] is True
        assert items[code]["status"] == "上架"
    assert items["studio_managed"]["active"] is False
    assert items["studio_managed"]["status"] == "已下架"


def test_ensure_plans_is_idempotent(app, client):
    from app.seed import ensure_plans

    with db_session(app) as session:
        ensure_plans(session)
        ensure_plans(session)
        plans = session.scalars(select(Plan).order_by(Plan.code)).all()
        by_code = {plan.code: plan for plan in plans}
        rows = {
            row.key: row
            for row in session.scalars(
                select(Entitlement).where(Entitlement.plan_id == by_code["creator"].id)
            ).all()
        }
        assert len({plan.code for plan in plans}) == len(plans)
        assert by_code["creator"].price_month_cents == 2990
        assert by_code["creator"].price_year_cents == 29900
        assert by_code["creator"].active is True
        assert {key: row.limit_value for key, row in rows.items()}["books_month"] == 5
        assert len(rows) == 7


def test_legacy_subscription_survives_plan_delisting(app, client, headers):
    from app.seed import ensure_plans

    with db_session(app) as session:
        _seed_legacy_plan(session, active=True)
    result = subscribe(client, headers, plan_code="studio_managed")
    subscription_id = result["subscription"]["id"]

    with db_session(app) as session:
        ensure_plans(session)
        old = session.scalar(select(Plan).where(Plan.code == "studio_managed"))
        assert old.active is False
        assert session.get(Subscription, subscription_id).status == "active"

    current = client.get("/v1/subscriptions/current", headers=headers).json()
    assert current["status"] == "active"
    assert current["plan"]["code"] == "studio_managed"


def test_mock_payment_activates_subscription(client, headers):
    result = subscribe(client, headers)
    assert result["subscription"]["status"] == "trialing"
    # 下单响应里的订单状态是支付前的快照
    assert result["order"]["status"] == "pending"

    current = client.get("/v1/subscriptions/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["status"] == "active"
    assert current.json()["plan"]["code"] == "creator"


def test_duplicate_webhook_is_idempotent(client, headers):
    result = subscribe(client, headers, pay=False)
    params = result["response"]["payment"]["params"]

    first = client.post(
        params["webhook_path"],
        headers={"x-mock-signature": params["signature"]},
        json=params["body"],
    )
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    second = client.post(
        params["webhook_path"],
        headers={"x-mock-signature": params["signature"]},
        json=params["body"],
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    with db_session(client.app) as session:
        order_count = session.scalar(select(func.count()).select_from(Order))
        webhook_count = session.scalar(select(func.count()).select_from(WebhookEvent))
        paid = session.scalar(select(func.count()).select_from(Order).where(Order.status == "paid"))
    assert order_count == 1
    assert webhook_count == 1
    assert paid == 1


def test_bad_webhook_signature_is_rejected(client, headers):
    result = subscribe(client, headers)
    params = result["response"]["payment"]["params"]
    response = client.post(
        params["webhook_path"],
        headers={"x-mock-signature": "forged"},
        json=params["body"],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signature"


def test_cancel_at_period_end_and_resume(client, headers):
    result = subscribe(client, headers)
    subscription_id = result["subscription"]["id"]

    cancelled = client.post(
        f"/v1/subscriptions/{subscription_id}/cancel", headers=headers, json={"immediate": False}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["subscription"]["status"] == "active"
    assert cancelled.json()["subscription"]["cancel_at_period_end"] is True

    resumed = client.post(f"/v1/subscriptions/{subscription_id}/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["subscription"]["cancel_at_period_end"] is False


def test_immediate_cancel_is_terminal_for_resume(client, headers):
    result = subscribe(client, headers)
    subscription_id = result["subscription"]["id"]

    cancelled = client.post(
        f"/v1/subscriptions/{subscription_id}/cancel", headers=headers, json={"immediate": True}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["subscription"]["status"] == "canceled"

    resumed = client.post(f"/v1/subscriptions/{subscription_id}/resume", headers=headers)
    assert resumed.status_code == 409
    assert resumed.json()["error"]["code"] == "invalid_transition"


def test_renew_extends_period(client, headers, app):
    result = subscribe(client, headers)
    subscription_id = result["subscription"]["id"]

    before = client.get("/v1/subscriptions/current", headers=headers).json()["current_end_at"]

    renewed = client.post(
        f"/v1/subscriptions/{subscription_id}/renew",
        headers={**headers, "Idempotency-Key": "renew-1"},
        json={"cycle": "month", "provider": "mock"},
    )
    assert renewed.status_code == 200, renewed.text
    order = renewed.json()["order"]
    assert order["kind"] == "renewal"
    assert order["status"] == "pending"

    params = renewed.json()["payment"]["params"]
    callback = client.post(
        params["webhook_path"],
        headers={"x-mock-signature": params["signature"]},
        json=params["body"],
    )
    assert callback.status_code == 200

    after = client.get("/v1/subscriptions/current", headers=headers).json()["current_end_at"]
    assert after > before


def test_expire_due_marks_subscription_expired(client, headers, app):
    result = subscribe(client, headers)
    subscription_id = result["subscription"]["id"]

    with db_session(app) as session:
        sub = session.get(Subscription, subscription_id)
        sub.current_end_at = utcnow() - timedelta(days=1)
        session.commit()
        count = subsvc.expire_due(session)
        session.commit()
    assert count == 1

    current = client.get("/v1/subscriptions/current", headers=headers)
    assert current.status_code == 404


def test_invalid_state_transition_rejected(app, client, headers):
    result = subscribe(client, headers)
    with db_session(app) as session:
        sub = session.get(Subscription, result["subscription"]["id"])
        with pytest.raises(ApiError) as exc:
            subsvc.transition(sub, "trialing")
        assert exc.value.code == "invalid_transition"
