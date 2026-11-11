# -*- coding: utf-8 -*-
"""开票渠道：stub 全流程、回调幂等、验签失败、缺凭据、状态机非法流转。"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from sqlalchemy import func, select

from app.models import Account, AuditLog, InvoiceRequest

from .helpers import subscribe


def _promote(app, account_id: int, role: str = "admin") -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = role
        session.commit()


def _subscriber(client) -> tuple[dict, dict]:
    response = client.post(
        "/v1/auth/register",
        json={"email": f"inv-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd!234"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    subscribe(client, headers)
    return data, headers


def _paid_order_id(client, account_id: int) -> int:
    from app.models import Order

    with client.app.state.db.session() as session:
        order = session.scalar(
            select(Order)
            .where(Order.account_id == account_id, Order.status == "paid")
            .order_by(Order.id.desc())
        )
        assert order is not None
        return order.id


def _new_invoice(client, sub_headers: dict, account_id: int) -> tuple[int, int]:
    order_id = _paid_order_id(client, account_id)
    response = client.post(
        f"/v1/orders/{order_id}/invoice",
        headers=sub_headers,
        json={"title": "测试公司", "tax_no": "91310000MA1FL0000X", "email": "fin@example.com"},
    )
    assert response.status_code in (200, 201), response.text
    return order_id, response.json()["invoice"]["id"]


def _sign(raw: bytes, secret: str = "test-invoice-secret") -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def test_stub_full_flow_and_audit(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _promote(app, account["account"]["id"])

    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])
    detail = client.get(f"/v1/invoices/{invoice_id}", headers=sub_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["invoice"]["status"] == "requested"

    issued = client.post(f"/v1/admin/invoices/{invoice_id}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["provider"] == "stub"
    assert body["invoice"]["status"] == "issued"
    assert body["invoice"]["provider_invoice_id"] == f"STUB-{invoice_id:08d}"
    assert body["invoice"]["issued_at"]

    admin_detail = client.get(f"/v1/admin/invoices/{invoice_id}", headers=headers)
    assert admin_detail.status_code == 200
    assert admin_detail.json()["invoice"]["status"] == "issued"

    with app.state.db.session() as session:
        apply_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "invoice.apply", AuditLog.target_id == str(invoice_id)
            )
        )
        assert apply_audit is not None and apply_audit.meta["provider"] == "stub"

    voided = client.post(
        f"/v1/admin/invoices/{invoice_id}/void", headers=headers, json={"reason": "开票信息有误"}
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["invoice"]["status"] == "voided"
    with app.state.db.session() as session:
        void_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "invoice.void", AuditLog.target_id == str(invoice_id)
            )
        )
        assert void_audit is not None and void_audit.meta["reason"] == "开票信息有误"

    again = client.post(
        f"/v1/admin/invoices/{invoice_id}/void", headers=headers, json={"reason": "重复作废"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "illegal_invoice_transition"

    # 客户端可查询自己的作废结果
    assert client.get(f"/v1/invoices/{invoice_id}", headers=sub_headers).json()["invoice"][
        "status"
    ] == "voided"


def test_callback_idempotent_and_state_machine(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _promote(app, account["account"]["id"])
    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])

    # 模拟渠道已受理、等待异步开票结果
    with app.state.db.session() as session:
        row = session.get(InvoiceRequest, invoice_id)
        row.status = "issuing"
        session.commit()

    payload = {
        "event_id": f"evt-{uuid.uuid4()}",
        "invoice_id": invoice_id,
        "status": "issued",
        "provider": "stub",
        "provider_invoice_id": "STUB-CALLBACK-1",
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response = client.post(
        "/v1/payments/invoices/callback",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Invoice-Signature": _sign(raw),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["duplicate"] is False
    assert response.json()["invoice"]["status"] == "issued"

    duplicate = client.post(
        "/v1/payments/invoices/callback",
        content=raw,
        headers={"Content-Type": "application/json", "X-Invoice-Signature": _sign(raw)},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["invoice"]["status"] == "issued"

    with app.state.db.session() as session:
        count = session.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.action == "invoice.callback", AuditLog.target_id == str(invoice_id)
            )
        )
        assert count == 1

    # 已开具后再次通知 requested / issuing 属于非法流转
    illegal_payload = {**payload, "event_id": f"evt-{uuid.uuid4()}", "status": "issuing"}
    illegal_raw = json.dumps(illegal_payload, separators=(",", ":")).encode("utf-8")
    illegal = client.post(
        "/v1/payments/invoices/callback",
        content=illegal_raw,
        headers={"X-Invoice-Signature": _sign(illegal_raw)},
    )
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "illegal_invoice_transition"


def test_callback_bad_signature_403(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])
    raw = json.dumps({"event_id": "evt-1", "invoice_id": invoice_id, "status": "issued"}).encode()
    response = client.post(
        "/v1/payments/invoices/callback",
        content=raw,
        headers={"X-Invoice-Signature": "deadbeef"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invoice_callback_signature_invalid"


def test_real_provider_missing_credentials_501(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _promote(app, account["account"]["id"])
    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])

    response = client.post(
        f"/v1/admin/invoices/{invoice_id}/issue",
        headers=headers,
        json={"provider": "nuonuo"},
    )
    assert response.status_code == 501, response.text
    assert response.json()["error"]["code"] == "invoice_provider_not_configured"

    with app.state.db.session() as session:
        assert session.get(InvoiceRequest, invoice_id).status == "requested"


def test_illegal_transition_409(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _promote(app, account["account"]["id"])
    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])

    assert client.post(f"/v1/admin/invoices/{invoice_id}/issue", headers=headers).status_code == 200
    repeat = client.post(f"/v1/admin/invoices/{invoice_id}/issue", headers=headers)
    assert repeat.status_code == 409
    assert repeat.json()["error"]["code"] == "illegal_invoice_transition"

    assert (
        client.post(
            f"/v1/admin/invoices/{invoice_id}/void", headers=headers, json={"reason": "作废"}
        ).status_code
        == 200
    )
    reopen = client.post(f"/v1/admin/invoices/{invoice_id}/issue", headers=headers)
    assert reopen.status_code == 409


def test_admin_create_invoice_for_order(client, headers, app, account):
    subscriber, _ = _subscriber(client)
    _promote(app, account["account"]["id"])
    order_id = _paid_order_id(client, subscriber["account"]["id"])
    created = client.post(
        f"/v1/admin/orders/{order_id}/invoice",
        headers=headers,
        json={"title": "管理端代开", "tax_no": "91310000MA1FL0000X", "email": "fin@example.com"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["duplicate"] is False
    assert created.json()["invoice"]["status"] == "requested"
    again = client.post(
        f"/v1/admin/orders/{order_id}/invoice",
        headers=headers,
        json={"title": "管理端代开", "tax_no": "91310000MA1FL0000X", "email": "fin@example.com"},
    )
    assert again.status_code == 201 and again.json()["duplicate"] is True


def test_client_void_requires_ownership(client, headers, app, account):
    subscriber, sub_headers = _subscriber(client)
    _, invoice_id = _new_invoice(client, sub_headers, subscriber["account"]["id"])
    other = client.post(
        "/v1/auth/register",
        json={"email": f"other-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd!234"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/v1/invoices/{invoice_id}", headers=other_headers).status_code == 404
    ok = client.post(
        f"/v1/invoices/{invoice_id}/void",
        headers=sub_headers,
        json={"reason": "不需要发票了"},
    )
    assert ok.status_code == 200 and ok.json()["invoice"]["status"] == "voided"
