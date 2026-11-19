# -*- coding: utf-8 -*-
"""用户自助退款申请：折算报价、pending 申请、防重复、归属隔离、管理端审核闭环。"""

from __future__ import annotations

from app.models import AuditLog, Refund
from app.services.audit import write_audit  # noqa: F401 - 确保审计表已注册（防御性导入）

from .helpers import db_session, subscribe


def test_user_refund_quote_pending_and_admin_flow(client, headers, app, account):
    # 下单并支付
    data = subscribe(client, headers)
    order_id = data["order"]["id"]

    # 报价：新订阅未用额度，可退 > 0
    quote_resp = client.get(f"/v1/orders/{order_id}/refund-quote", headers=headers)
    assert quote_resp.status_code == 200, quote_resp.text
    quote = quote_resp.json()["quote"]
    assert quote["order_id"] == order_id
    assert quote["refundable_cents"] > 0

    # 用户提交申请：只创建 pending，不真正退款
    req = client.post(
        f"/v1/orders/{order_id}/refund-request",
        headers=headers,
        json={"reason": "不需要了"},
    )
    assert req.status_code == 201, req.text
    body = req.json()
    assert body["duplicate"] is False
    refund = body["refund"]
    assert refund["status"] == "pending"
    assert refund["amount_cents"] == quote["refundable_cents"]
    assert refund["reason"] == "不需要了"
    refund_id = refund["id"]

    # 订单仍为 paid（用户申请不改变支付状态）
    order_resp = client.get(f"/v1/orders/{order_id}", headers=headers)
    assert order_resp.json()["order"]["status"] == "paid"

    # 重复提交被拒（已有 pending）
    dup = client.post(
        f"/v1/orders/{order_id}/refund-request",
        headers=headers,
        json={"reason": "再申请一次"},
    )
    assert dup.status_code == 409, dup.text
    assert dup.json()["error"]["code"] == "refund_already_pending"

    # 审计留痕
    with db_session(app) as session:
        assert session.query(AuditLog).filter(
            AuditLog.action == "order.refund.request"
        ).count() >= 1

    # 管理端审核通过：pending 退款真正走渠道，订单变 refunded
    from .test_payments import _promote_admin
    _promote_admin(app, account["account"]["id"])
    approve = client.post(
        f"/v1/admin/refunds/{refund_id}/approve",
        headers=headers,
        json={"note": "同意"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["refund"]["status"] == "succeeded"

    # 用户能看到退款记录
    listed = client.get("/v1/refunds", headers=headers)
    assert listed.status_code == 200
    statuses = [r["status"] for r in listed.json()["items"]]
    assert "succeeded" in statuses


def test_user_refund_rejects_other_account_order(client, headers, app, account):
    """用户不能对自己不拥有的订单申请退款。"""
    from .helpers import subscribe as _subscribe
    data = _subscribe(client, headers)
    order_id = data["order"]["id"]

    # 新建第二个账号
    reg = client.post(
        "/v1/auth/register",
        json={"email": "refund-other@example.com", "password": "StrongPass123!", "legal_version": "2026-11-18"},
    )
    assert reg.status_code in (200, 201), reg.text
    login = client.post(
        "/v1/auth/login",
        json={"email": "refund-other@example.com", "password": "StrongPass123!"},
    )
    assert login.status_code == 200, login.text
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    quote = client.get(f"/v1/orders/{order_id}/refund-quote", headers=other_headers)
    assert quote.status_code == 404

    req = client.post(
        f"/v1/orders/{order_id}/refund-request",
        headers=other_headers,
        json={"reason": "替别人申请"},
    )
    assert req.status_code == 404

    with db_session(app) as session:
        assert session.query(Refund).filter(Refund.order_id == order_id).count() == 0
