# -*- coding: utf-8 -*-
"""额度包：购买幂等、发放、到期、优先级（套餐先扣再扣包）。"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import CreditGrant, Notification
from app.services import credits as creditsvc
from app.services.quota import QuotaService

from .helpers import subscribe


def _purchase(client, headers, code: str = "books_5", key: str | None = None) -> dict:
    response = client.post(
        f"/v1/credit-packs/{code}/purchase",
        headers={**headers, "Idempotency-Key": key or f"pack-{uuid.uuid4()}"},
        json={"provider": "mock"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _pay(client, data: dict) -> dict:
    params = data["payment"]["params"]
    response = client.post(
        params["webhook_path"],
        headers={"x-mock-signature": params["signature"]},
        json=params["body"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_credit_pack_purchase_grant_idempotent(client, headers, app, account):
    subscribe(client, headers)
    key = f"pack-{uuid.uuid4()}"
    first = _purchase(client, headers, key=key)
    again = _purchase(client, headers, key=key)
    assert first["order"]["id"] == again["order"]["id"]  # 幂等键复用同一订单

    paid = _pay(client, first)
    assert paid["order_status"] == "paid"
    duplicate = _pay(client, first)
    assert duplicate["duplicate"] is True

    with app.state.db.session() as session:
        grants = session.scalars(
            select(CreditGrant).where(CreditGrant.account_id == account["account"]["id"])
        ).all()
        assert len(grants) == 1
        assert grants[0].quantity_granted == 5
        assert grants[0].status == "active"

    data = client.get("/v1/entitlements", headers=headers).json()
    credits = {row["metric"]: row for row in data["credits"]}
    assert credits["books_month"]["remaining"] == 5


def test_plan_quota_consumed_before_pack(client, headers, app, account):
    subscribe(client, headers)
    data = _purchase(client, headers)
    _pay(client, data)

    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        quota = QuotaService(session)
        plan_res = quota.reserve(account_id, "books_month", 5)
        assert plan_res.plan_quantity == 5
        assert plan_res.pack_items == ()
        assert quota.commit(plan_res, idempotency_key="use-plan-1") is True

        pack_res = quota.reserve(account_id, "books_month", 2)
        assert pack_res.plan_quantity == 0
        assert pack_res.pack_items and pack_res.pack_items[0]["quantity"] == 2
        assert quota.commit(pack_res, idempotency_key="use-pack-1") is True

        grant = session.scalar(select(CreditGrant))
        assert grant.quantity_used == 2
        summary = quota.summary(account_id)
        row = {m["metric"]: m for m in summary["metrics"]}["books_month"]
        assert row["remaining"] == 0 and row["pack_remaining"] == 3
        assert row["total_remaining"] == 3
        assert {c["metric"]: c for c in summary["credits"]}["books_month"]["remaining"] == 3
        session.commit()


def test_pack_expiry_voids_remaining(client, headers, app):
    subscribe(client, headers)
    data = _purchase(client, headers)
    _pay(client, data)

    with app.state.db.session() as session:
        grant = session.scalar(select(CreditGrant))
        grant.expires_at = utcnow() - timedelta(days=1)
        session.flush()
        assert creditsvc.expire_grants(session) == 1
        assert grant.status == "expired"
        assert creditsvc.available(session, grant.account_id, "books_month") == 0
        session.commit()


def test_pack_purchase_rejects_insufficient_total(client, headers, app, account):
    """套餐 + 包都不够时返回 402，并落一条额度不足通知。"""
    subscribe(client, headers)
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        quota = QuotaService(session)
        with pytest.raises(Exception) as exc:
            quota.reserve(account_id, "books_month", 6)
        assert getattr(exc.value, "code", "") == "quota_exceeded"
        note = session.scalar(
            select(Notification).where(Notification.category == "quota_insufficient")
        )
        assert note is not None
        assert "books_month" in note.body
        session.commit()
