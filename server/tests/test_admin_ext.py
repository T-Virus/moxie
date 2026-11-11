# -*- coding: utf-8 -*-
"""管理端扩展：用户封禁、订阅调整、额度手工调整、退款审批、发票状态、看板。"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db import utcnow
from app.models import Account, AuditLog, InvoiceRequest, Order, Subscription
from app.services.quota import QuotaService

from .helpers import subscribe


def _promote(app, account_id: int, role: str) -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = role
        session.commit()


def _new_account(client) -> dict:
    response = client.post(
        "/v1/auth/register",
        json={"email": f"other-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd!234"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ban_user_and_reject_token(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    other = _new_account(client)
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/v1/auth/me", headers=other_headers).status_code == 200

    response = client.post(
        f"/v1/admin/users/{other['account']['id']}/status",
        headers=headers,
        json={"status": "banned", "reason": "异常登录"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["status"] == "banned"
    assert client.get("/v1/auth/me", headers=other_headers).status_code == 401

    with app.state.db.session() as session:
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action.in_(("user.ban", "user.status")))
        )
        assert audit is not None and audit.meta["reason"] == "异常登录"


def test_subscription_adjust_extend_and_quota_adjust(client, headers, app, account):
    subscriber = _new_account(client)
    sub_headers = {"Authorization": f"Bearer {subscriber['access_token']}"}
    subscribe(client, sub_headers)
    _promote(app, account["account"]["id"], "admin")
    account_id = subscriber["account"]["id"]

    with app.state.db.session() as session:
        sub = session.scalar(select(Subscription).where(Subscription.account_id == account_id))
        sub_id = sub.id
        before_end = sub.current_end_at

    response = client.patch(
        f"/v1/admin/subscriptions/{sub_id}",
        headers=headers,
        json={"extend_days": 10, "note": "补偿"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["subscription"]["current_end_at"] > before_end.isoformat()

    key = f"adj-{uuid.uuid4()}"
    body = {"metric": "books_month", "quantity": 2, "reason": "客服补偿", "idempotency_key": key}
    response = client.post(
        f"/v1/admin/accounts/{account_id}/quota-adjustments", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    assert response.json()["after"] == response.json()["before"] + 2
    duplicate = client.post(
        f"/v1/admin/accounts/{account_id}/quota-adjustments", headers=headers, json=body
    )
    assert duplicate.json()["duplicate"] is True

    history = client.get(
        f"/v1/admin/accounts/{account_id}/quota-adjustments", headers=headers
    )
    assert history.status_code == 200 and history.json()["items"]

    with app.state.db.session() as session:
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "quota.adjust"))
        assert audit.meta["reason"] == "客服补偿"


def test_refund_quote_partial_and_prorate(client, headers, app, account):
    subscriber = _new_account(client)
    sub_headers = {"Authorization": f"Bearer {subscriber['access_token']}"}
    subscribe(client, sub_headers)
    _promote(app, account["account"]["id"], "admin")

    with app.state.db.session() as session:
        order = session.scalar(
            select(Order).where(
                Order.account_id == subscriber["account"]["id"], Order.status == "paid"
            )
        )
        order_id = order.id
        order_amount = order.amount_cents
        # 创作版 books_month=5；用掉 2 本 → 已用 40%，可退 60%
        quota = QuotaService(session)
        res = quota.reserve(subscriber["account"]["id"], "books_month", 2)
        quota.commit(res, idempotency_key="refund-used")
        session.commit()

    expected_refund = int(round(order_amount * 0.6))
    quote = client.get(f"/v1/admin/orders/{order_id}/refund-quote", headers=headers)
    assert quote.status_code == 200, quote.text
    assert quote.json()["quote"]["used_ratio"] == 0.4
    assert quote.json()["quote"]["refundable_cents"] == expected_refund

    response = client.post(
        f"/v1/admin/orders/{order_id}/refund",
        headers=headers,
        json={"prorate": True, "reason": "部分退款"},
    )
    assert response.status_code == 200, response.text
    refund = response.json()["refund"]
    assert refund["amount_cents"] == expected_refund

    with app.state.db.session() as session:
        order = session.get(Order, order_id)
        assert order.refunded_cents == expected_refund
        assert order.status == "refunded" or order.status == "paid"


def test_invoice_voided_state(client, headers, app, account):
    subscriber = _new_account(client)
    sub_headers = {"Authorization": f"Bearer {subscriber['access_token']}"}
    subscribe(client, sub_headers)
    _promote(app, account["account"]["id"], "admin")

    with app.state.db.session() as session:
        order = session.scalar(
            select(Order).where(
                Order.account_id == subscriber["account"]["id"], Order.status == "paid"
            )
        )
        order_id = order.id

    created = client.post(
        f"/v1/orders/{order_id}/invoice",
        headers=sub_headers,
        json={"title": "测试公司", "tax_no": "91310000MA1FL0000X"},
    )
    assert created.status_code in (200, 201), created.text
    invoice_id = created.json()["invoice"]["id"]

    issued = client.post(
        f"/v1/admin/invoices/{invoice_id}", headers=headers, json={"status": "issued"}
    )
    assert issued.status_code == 200, issued.text
    voided = client.post(
        f"/v1/admin/invoices/{invoice_id}", headers=headers, json={"status": "voided"}
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["invoice"]["status"] == "voided"


def test_ban_unban_login_and_task_gate(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    other = _new_account(client)
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}

    banned = client.post(
        f"/v1/admin/users/{other['account']['id']}/ban",
        headers=headers,
        json={"reason": "风控封禁"},
    )
    assert banned.status_code == 200, banned.text
    assert client.get("/v1/auth/me", headers=other_headers).status_code == 401
    login = client.post(
        "/v1/auth/login",
        json={"email": other["account"]["email"], "password": "Passw0rd!234"},
    )
    assert login.status_code == 403 and login.json()["error"]["code"] == "account_disabled"
    task = client.post(
        "/v1/tasks",
        headers=other_headers,
        json={"type": "decompose", "params": {"book": "封禁测试", "source_text": "内容"},
              "idempotency_key": f"banned-{uuid.uuid4()}"},
    )
    assert task.status_code == 401

    unbanned = client.post(
        f"/v1/admin/users/{other['account']['id']}/unban",
        headers=headers,
        json={"reason": "申诉通过"},
    )
    assert unbanned.status_code == 200
    # 封禁时刷新会话已被吊销，解封后需重新登录
    relogin = client.post(
        "/v1/auth/login",
        json={"email": other["account"]["email"], "password": "Passw0rd!234"},
    )
    assert relogin.status_code == 200
    fresh_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    assert client.get("/v1/auth/me", headers=fresh_headers).status_code == 200


def test_refund_approve_is_idempotent_and_reject_requires_note(client, headers, app, account):
    subscriber = _new_account(client)
    sub_headers = {"Authorization": f"Bearer {subscriber['access_token']}"}
    subscribe(client, sub_headers)
    _promote(app, account["account"]["id"], "admin")

    with app.state.db.session() as session:
        order = session.scalar(
            select(Order).where(
                Order.account_id == subscriber["account"]["id"], Order.status == "paid"
            )
        )
        order_id = order.id

    created = client.post(
        f"/v1/admin/orders/{order_id}/refund",
        headers=headers,
        json={"reason": "测试退款"},
    )
    assert created.status_code == 200, created.text
    refund_id = created.json()["refund"]["id"]
    approve = client.post(f"/v1/admin/refunds/{refund_id}/approve", headers=headers)
    assert approve.status_code == 200 and approve.json()["duplicate"] is True

    # 驳回备注必填
    with app.state.db.session() as session:
        from app.models import Refund

        pending = Refund(
            order_id=order_id,
            account_id=subscriber["account"]["id"],
            amount_cents=1,
            status="pending",
            provider="mock",
            reason="待驳回",
            idempotency_key=f"reject-{uuid.uuid4()}",
        )
        session.add(pending)
        session.commit()
        pending_id = pending.id

    rejected = client.post(
        f"/v1/admin/refunds/{pending_id}/reject", headers=headers, json={"note": ""}
    )
    assert rejected.status_code == 422
    ok = client.post(
        f"/v1/admin/refunds/{pending_id}/reject", headers=headers, json={"note": "用户申请有误"}
    )
    assert ok.status_code == 200 and ok.json()["refund"]["status"] == "failed"


def test_support_can_read_but_not_write(client, headers, app, account):
    support = _new_account(client)
    support_headers = {"Authorization": f"Bearer {support['access_token']}"}
    _promote(app, support["account"]["id"], "support")

    assert client.get("/v1/admin/users", headers=support_headers).status_code == 200
    assert client.get("/v1/admin/orders", headers=support_headers).status_code == 200
    write = client.post(
        f"/v1/admin/users/{account['account']['id']}/ban",
        headers=support_headers,
        json={"reason": "support 不应能封禁"},
    )
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "admin_required"

    normal = _new_account(client)
    normal_headers = {"Authorization": f"Bearer {normal['access_token']}"}
    read = client.get("/v1/admin/users", headers=normal_headers)
    assert read.status_code == 403
    assert read.json()["error"]["code"] == "staff_required"


def test_audit_logs_pagination_and_filters(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    body = {
        "metric": "books_month",
        "quantity": 1,
        "reason": "审计过滤",
        "idempotency_key": f"audit-{uuid.uuid4()}",
    }
    created = client.post(
        f"/v1/admin/accounts/{account['account']['id']}/quota-adjustments",
        headers=headers,
        json=body,
    )
    assert created.status_code == 200, created.text
    audit_id = created.json()["audit"]["id"]

    page = client.get(
        "/v1/admin/audit-logs",
        headers=headers,
        params={
            "page": 1,
            "page_size": 1,
            "action": "quota.adjust",
            "actor_id": account["account"]["id"],
            "target_type": "account",
            "target_id": account["account"]["id"],
        },
    )
    assert page.status_code == 200, page.text
    data = page.json()
    assert data["total"] == 1
    assert data["page"] == 1 and data["page_size"] == 1
    assert len(data["items"]) == 1 and data["items"][0]["id"] == audit_id
    assert data["items"][0]["meta"]["reason"] == "审计过滤"

    # 前端旧参数 limit 兼容
    limited = client.get("/v1/admin/audit-logs?limit=5", headers=headers)
    assert limited.status_code == 200 and limited.json()["page_size"] == 5


def test_invoice_legacy_status_and_refund_aliases(client, headers, app, account):
    subscriber = _new_account(client)
    sub_headers = {"Authorization": f"Bearer {subscriber['access_token']}"}
    subscribe(client, sub_headers)
    _promote(app, account["account"]["id"], "admin")

    with app.state.db.session() as session:
        order = session.scalar(
            select(Order).where(
                Order.account_id == subscriber["account"]["id"], Order.status == "paid"
            )
        )
        order_id = order.id

    created = client.post(
        f"/v1/orders/{order_id}/invoice",
        headers=sub_headers,
        json={"title": "测试公司", "tax_no": "91310000MA1FL0000X"},
    )
    invoice_id = created.json()["invoice"]["id"]
    assert created.json()["invoice"]["legacy_status"] is None
    updated = client.post(
        f"/v1/admin/invoices/{invoice_id}", headers=headers, json={"status": "rejected"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["invoice"]["status"] == "voided"
    assert updated.json()["invoice"]["legacy_status"] == "rejected"

    # 查询参数 rejected 映射到 voided，历史 rejected 数据也能查到
    for query in ("rejected", "voided"):
        listed = client.get(f"/v1/admin/invoices?status={query}", headers=headers)
        assert listed.status_code == 200, listed.text
        ids = [item["id"] for item in listed.json()["items"]]
        assert invoice_id in ids
        item = next(i for i in listed.json()["items"] if i["id"] == invoice_id)
        assert item["status"] == "voided" and item["legacy_status"] == "rejected"

    refund = client.post(
        f"/v1/admin/orders/{order_id}/refund",
        headers=headers,
        json={"reason": "别名兼容"},
    )
    assert refund.status_code == 200, refund.text
    listed_refunds = client.get(
        f"/v1/admin/refunds?order_id={order_id}", headers=headers
    )
    assert listed_refunds.status_code == 200
    assert listed_refunds.json()["items"] == listed_refunds.json()["refunds"]


def test_admin_dashboard_and_tasks(client, headers, app, account):
    _promote(app, account["account"]["id"], "admin")
    response = client.get("/v1/admin/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "tasks" in data and "alerts" in data
    assert data["tasks"]["queued"] >= 0

    tasks = client.get("/v1/admin/tasks", headers=headers)
    assert tasks.status_code == 200

    account_list = client.get("/v1/admin/users", headers=headers)
    assert account_list.status_code == 200
