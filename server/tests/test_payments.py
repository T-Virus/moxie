# -*- coding: utf-8 -*-
"""真实支付接入：微信/支付宝/Stripe 验签、退款、升级、对账、发票。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models import Account, AuditLog, Order, Plan, Refund, UsageEvent
from app.payments.alipay import build_sign_content, rsa2_sign
from app.services.reconcile import reconcile

from .helpers import db_session, subscribe


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return priv, pub


def _promote_admin(app, account_id: int) -> None:
    with db_session(app) as session:
        row = session.get(Account, account_id)
        row.role = "admin"
        session.commit()


def _make_order(client, headers, app, provider: str, plan_code="creator"):
    """用 mock 建订阅订单，再把渠道切到目标 provider（避免真实网络）。"""
    data = subscribe(client, headers)
    order_id = data["order"]["id"]
    with db_session(app) as session:
        order = session.get(Order, order_id)
        order.provider = provider
        order.external_order_no = f"MX{order.id:012d}"
        sub = session.get(Order, order_id)
        from app.models import Subscription

        subscription = session.get(Subscription, order.subscription_id)
        subscription.provider = provider
        session.commit()
        return order.id, order.amount_cents, order.subscription_id


def _wechat_event(settings, platform_private_pem: str, order_id: int, amount_cents: int, event_id="evt-wx-1"):
    plain = {
        "mchid": settings.wechat_mch_id,
        "appid": settings.wechat_app_id,
        "out_trade_no": f"MX{order_id:012d}",
        "transaction_id": "wx-txn-0001",
        "trade_state": "SUCCESS",
        "amount": {"total": amount_cents, "currency": "CNY"},
    }
    nonce = "nonce123456"
    aad = "transaction"
    ciphertext = base64.b64encode(
        AESGCM(settings.wechat_api_v3_key.encode()).encrypt(
            nonce.encode(), json.dumps(plain).encode(), aad.encode()
        )
    ).decode()
    body = {
        "id": event_id,
        "event_type": "TRANSACTION.SUCCESS",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": ciphertext,
            "nonce": nonce,
            "associated_data": aad,
        },
    }
    raw = json.dumps(body).encode()
    ts = str(int(time.time()))
    header_nonce = "hdrnonce"
    message = f"{ts}\n{header_nonce}\n".encode() + raw + b"\n"
    platform_key = serialization.load_pem_private_key(
        platform_private_pem.encode(), password=None
    )
    signature = base64.b64encode(
        platform_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    return raw, {
        "wechatpay-timestamp": ts,
        "wechatpay-nonce": header_nonce,
        "wechatpay-signature": signature,
        "wechatpay-serial": settings.wechat_platform_serial_no,
    }


def test_wechat_webhook_signature_and_duplicate(client, headers, app, settings):
    platform_priv, platform_pub = _keypair()
    merchant_priv, _ = _keypair()
    settings.wechat_mch_id = "1900000001"
    settings.wechat_app_id = "wx-app-0001"
    settings.wechat_api_v3_key = "k" * 32
    settings.wechat_private_key_pem = merchant_priv
    settings.wechat_platform_cert_pem = platform_pub
    settings.wechat_platform_serial_no = "SERIAL-1"
    settings.wechat_notify_url = "https://example.com/v1/webhooks/wechat"

    order_id, amount, subscription_id = _make_order(client, headers, app, "wechat")
    raw, headers_ok = _wechat_event(settings, platform_priv, order_id, amount)

    response = client.post("/v1/webhooks/wechat", content=raw, headers=headers_ok)
    assert response.status_code == 200, response.text
    assert response.json()["order_status"] == "paid"

    current = client.get("/v1/subscriptions/current", headers=headers).json()
    assert current["status"] == "active"
    assert current["provider"] == "wechat"

    duplicate = client.post("/v1/webhooks/wechat", content=raw, headers=headers_ok)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    tampered = client.post(
        "/v1/webhooks/wechat", content=raw + b" ", headers=headers_ok
    )
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] in ("invalid_signature", "invalid_webhook")
    with db_session(app) as session:
        rejected = session.query(AuditLog).filter(AuditLog.action == "payment.webhook_rejected").count()
        assert rejected >= 1


def _alipay_params(settings, order_id: int, amount_cents: int, notify_id="ali-notify-1", amount=None):
    params = {
        "app_id": settings.alipay_app_id,
        "seller_id": settings.alipay_seller_id,
        "out_trade_no": f"MX{order_id:012d}",
        "trade_no": "2026010122001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": amount or f"{amount_cents / 100:.2f}",
        "notify_id": notify_id,
        "notify_time": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
    }
    content = build_sign_content(params)
    return {**params, "sign": rsa2_sign(content, settings.alipay_private_key_pem), "sign_type": "RSA2"}


def test_alipay_notify_signature_amount_and_duplicate(client, headers, app, settings):
    alipay_priv, alipay_pub = _keypair()
    settings.alipay_app_id = "2021000000000001"
    settings.alipay_seller_id = "2088000000000001"
    settings.alipay_private_key_pem = alipay_priv
    settings.alipay_public_key_pem = alipay_pub
    settings.alipay_notify_url = "https://example.com/v1/webhooks/alipay"

    order_id, amount, _ = _make_order(client, headers, app, "alipay")
    payload = _alipay_params(settings, order_id, amount)

    response = client.post("/v1/webhooks/alipay", data=payload)
    assert response.status_code == 200, response.text
    assert response.json()["order_status"] == "paid"

    duplicate = client.post("/v1/webhooks/alipay", data=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    bad_sign = dict(payload)
    bad_sign["sign"] = base64.b64encode(b"bad-signature").decode()
    rejected = client.post("/v1/webhooks/alipay", data=bad_sign)
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "invalid_signature"

    # 金额与订单不符：签名正确也拒绝
    wrong = _alipay_params(settings, order_id, amount, notify_id="ali-notify-2", amount="0.01")
    mismatch = client.post("/v1/webhooks/alipay", data=wrong)
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "amount_mismatch"


def test_stripe_webhook_signature_and_duplicate(client, headers, app, settings):
    settings.stripe_secret_key = "sk_test_123"
    settings.stripe_webhook_secret = "whsec_test_secret"
    settings.stripe_success_url = "https://example.com/success"
    order_id, amount, _ = _make_order(client, headers, app, "stripe")

    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "client_reference_id": str(order_id),
                "amount_total": amount,
                "currency": "cny",
                "payment_intent": "pi_test_1",
                "metadata": {"order_id": str(order_id), "external_order_no": f"MX{order_id:012d}"},
            }
        },
    }
    raw = json.dumps(event).encode()
    ts = str(int(time.time()))
    signature = hmac.new(
        settings.stripe_webhook_secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    headers_ok = {"stripe-signature": f"t={ts},v1={signature}"}

    response = client.post("/v1/webhooks/stripe", content=raw, headers=headers_ok)
    assert response.status_code == 200, response.text
    assert response.json()["order_status"] == "paid"

    duplicate = client.post("/v1/webhooks/stripe", content=raw, headers=headers_ok)
    assert duplicate.json()["duplicate"] is True

    tampered = client.post(
        "/v1/webhooks/stripe", content=raw.replace(b"evt_1", b"evt_2"), headers=headers_ok
    )
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "invalid_signature"

    stale_ts = str(int(time.time()) - 3600)
    stale_sig = hmac.new(
        settings.stripe_webhook_secret.encode(), f"{stale_ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    expired = client.post(
        "/v1/webhooks/stripe", content=raw, headers={"stripe-signature": f"t={stale_ts},v1={stale_sig}"}
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "webhook_expired"


def test_fake_full_flow_pay_renew_refund(client, headers, app, account):
    created = client.post(
        "/v1/subscriptions",
        headers={**headers, "Idempotency-Key": "fake-1"},
        json={"plan_code": "creator", "cycle": "month", "provider": "fake"},
    )
    assert created.status_code == 201, created.text
    params = created.json()["payment"]["params"]
    paid = client.post(params["webhook_path"], headers={"x-mock-signature": params["signature"]}, json=params["body"])
    assert paid.status_code == 200, paid.text
    assert client.get("/v1/subscriptions/current", headers=headers).json()["status"] == "active"
    order_id = created.json()["order"]["id"]

    # 续费
    renewed = client.post(
        f"/v1/subscriptions/{created.json()['subscription']['id']}/renew",
        headers={**headers, "Idempotency-Key": "fake-renew-1"},
        json={"cycle": "month", "provider": "fake"},
    )
    assert renewed.status_code == 200, renewed.text
    renew_params = renewed.json()["payment"]["params"]
    client.post(
        renew_params["webhook_path"],
        headers={"x-mock-signature": renew_params["signature"]},
        json=renew_params["body"],
    )
    assert client.get("/v1/subscriptions/current", headers=headers).json()["status"] == "active"

    # 退款（管理端）+ 幂等 + 权益回收
    _promote_admin(app, account["account"]["id"])
    first = client.post(
        f"/v1/admin/orders/{order_id}/refund",
        headers={**headers, "Idempotency-Key": "refund-key-1"},
        json={"reason": "测试退款"},
    )
    assert first.status_code == 200, first.text
    refund_id = first.json()["refund"]["id"]
    assert first.json()["refund"]["status"] == "succeeded"
    assert first.json()["order"]["status"] == "refunded"

    second = client.post(
        f"/v1/admin/orders/{order_id}/refund",
        headers={**headers, "Idempotency-Key": "refund-key-1"},
        json={"reason": "测试退款"},
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["refund"]["id"] == refund_id

    with db_session(app) as session:
        refund_rows = session.query(Refund).filter(Refund.order_id == order_id).count()
        assert refund_rows == 1
        audit = session.query(AuditLog).filter(AuditLog.action == "order.refund").count()
        assert audit >= 1


def test_upgrade_proration_and_activation(client, headers, app, settings):
    data = subscribe(client, headers)
    sub_id = data["subscription"]["id"]
    upgraded = client.post(
        f"/v1/subscriptions/{sub_id}/upgrade",
        headers={**headers, "Idempotency-Key": "upgrade-1"},
        json={"plan_code": "professional", "provider": "mock"},
    )
    assert upgraded.status_code == 200, upgraded.text
    order = upgraded.json()["order"]
    assert order["kind"] == "upgrade"
    assert order["status"] == "pending"
    assert 3800 <= order["amount_cents"] <= 4000
    assert order["meta"]["previous_plan_code"] == "creator"

    params = upgraded.json()["payment"]["params"]
    paid = client.post(params["webhook_path"], headers={"x-mock-signature": params["signature"]}, json=params["body"])
    assert paid.status_code == 200, paid.text
    current = client.get("/v1/subscriptions/current", headers=headers).json()
    assert current["plan"]["code"] == "professional"

    duplicate = client.post(
        f"/v1/subscriptions/{sub_id}/upgrade",
        headers={**headers, "Idempotency-Key": "upgrade-1"},
        json={"plan_code": "professional", "provider": "mock"},
    )
    assert duplicate.json()["order"]["id"] == order["id"]

    downgrade = client.post(
        f"/v1/subscriptions/{sub_id}/upgrade",
        headers={**headers, "Idempotency-Key": "upgrade-down"},
        json={"plan_code": "creator", "provider": "mock"},
    )
    assert downgrade.status_code == 409
    assert downgrade.json()["error"]["code"] == "downgrade_not_supported"


def test_reconcile_classification_and_export(client, headers, app, account, settings):
    biz = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    plan = None
    with db_session(app) as session:
        plan = session.query(Plan).filter(Plan.code == "creator").one()
        for index, no in enumerate(["MX000000000101", "MX000000000102", "MX000000000103", "MX000000000104"]):
            session.add(
                Order(
                    account_id=account["account"]["id"],
                    plan_id=plan.id,
                    amount_cents=2900,
                    currency="CNY",
                    status="paid",
                    provider="wechat",
                    external_order_no=no,
                    paid_at=biz,
                )
            )
        session.commit()

    records = [
        {"external_order_no": "MX000000000101", "amount_cents": 2900, "provider_txn_id": "wx1", "status": "paid"},
        {"external_order_no": "MX000000000102", "amount_cents": 100, "provider_txn_id": "wx2", "status": "paid"},
        {"external_order_no": "MX000000000104", "amount_cents": 2900, "provider_txn_id": "wx4a", "status": "paid"},
        {"external_order_no": "MX000000000104", "amount_cents": 2900, "provider_txn_id": "wx4b", "status": "paid"},
        {"external_order_no": "MX000000000999", "amount_cents": 500, "provider_txn_id": "wx9", "status": "paid"},
    ]
    with db_session(app) as session:
        report = reconcile(
            session,
            provider="wechat",
            biz_date=biz.date(),
            settings=settings,
            records=records,
            source="upload",
        )
        session.commit()
        summary = report.summary
        assert summary["orders"] == 4
        assert summary["amount_mismatch"] == 1
        assert summary["local_only"] == 1
        assert summary["channel_only"] == 1
        assert summary["duplicate_payment"] == 1
        types = {item["type"] for item in report.items}
        assert types == {"amount_mismatch", "local_only", "channel_only", "duplicate_payment"}

    _promote_admin(app, account["account"]["id"])
    fetched = client.get(
        "/v1/admin/payments/reconcile", headers=headers, params={"provider": "wechat", "biz_date": "2026-01-01"}
    )
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["diff_count"] == 4
    export = client.get(
        "/v1/admin/payments/reconcile/export",
        headers=headers,
        params={"provider": "wechat", "biz_date": "2026-01-01"},
    )
    assert export.status_code == 200
    assert "duplicate_payment" in export.text


def test_invoice_request_and_admin_issue(client, headers, app, account):
    data = subscribe(client, headers)
    order_id = data["order"]["id"]
    created = client.post(
        f"/v1/orders/{order_id}/invoice",
        headers=headers,
        json={"title": "某某公司", "tax_no": "91310000TEST", "email": "billing@example.com"},
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["invoice"]["id"]
    assert created.json()["invoice"]["status"] == "requested"

    again = client.post(
        f"/v1/orders/{order_id}/invoice", headers=headers, json={"title": "某某公司"}
    )
    assert again.json()["invoice"]["id"] == invoice_id  # 一单一票

    _promote_admin(app, account["account"]["id"])
    issued = client.post(
        f"/v1/admin/invoices/{invoice_id}",
        headers=headers,
        json={"status": "issued", "note": "已开具"},
    )
    assert issued.status_code == 200
    assert issued.json()["invoice"]["status"] == "issued"
    assert issued.json()["invoice"]["issued_at"] is not None


def test_provider_not_configured_returns_501(client, headers, app, settings):
    settings.wechat_mch_id = ""
    settings.wechat_private_key_pem = ""
    settings.wechat_platform_cert_pem = ""
    response = client.post(
        "/v1/subscriptions",
        headers={**headers, "Idempotency-Key": "wx-unconfigured"},
        json={"plan_code": "creator", "cycle": "month", "provider": "wechat"},
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "provider_not_configured"


@pytest.mark.live
def test_stripe_live_sandbox_smoke():
    """真实沙箱：需要 STRIPE_SECRET_KEY；缺凭据自动 skip。"""
    if not os.getenv("STRIPE_SECRET_KEY"):
        pytest.skip("缺少 STRIPE_SECRET_KEY，跳过 Stripe 沙箱冒烟")
    pytest.skip("已配置 key 时请手动运行沙箱下单冒烟（CI 不自动扣款）")


@pytest.mark.live
def test_wechat_live_sandbox_smoke():
    if not all(os.getenv(k) for k in ("WECHAT_MCH_ID", "WECHAT_API_V3_KEY", "WECHAT_PRIVATE_KEY_PEM")):
        pytest.skip("缺少微信商户凭据，跳过沙箱冒烟")
    pytest.skip("已配置凭据时请手动运行沙箱下单冒烟")


@pytest.mark.live
def test_alipay_live_sandbox_smoke():
    if not all(os.getenv(k) for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY_PEM", "ALIPAY_PUBLIC_KEY_PEM")):
        pytest.skip("缺少支付宝沙箱凭据，跳过沙箱冒烟")
    pytest.skip("已配置凭据时请手动运行沙箱下单冒烟")
