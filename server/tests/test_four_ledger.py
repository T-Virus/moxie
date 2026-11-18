# -*- coding: utf-8 -*-
"""四账对账聚合回归。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Account, Order

from .helpers import subscribe


def test_four_ledger_reconcile_detects_payment_mismatch(client, headers, app, account):
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        session.get(Account, account_id).role = "admin"
        session.commit()

    subscribe(client, headers)

    with app.state.db.session() as session:
        order = session.scalar(select(Order).where(Order.account_id == account_id))
        assert order is not None
        order_id = order.id
        order.paid_at = None
        session.commit()

    response = client.get(
        f"/v1/admin/payments/four-ledger-reconcile?order_no={order_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert data["summary"]["orders"] == 1
    assert data["summary"]["anomaly_total"] >= 1
    assert any(item["code"] == "payment_status_mismatch" for item in data["anomalies"])
    group = data["groups"][0]
    assert group["order_id"] == order_id
    assert "payment" in group and "quota" in group and "invoice" in group and "refund" in group
