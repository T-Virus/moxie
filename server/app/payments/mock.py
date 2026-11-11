# -*- coding: utf-8 -*-
"""mock 渠道：本地/测试用，同步返回可提交的签名回调。"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ..errors import ApiError
from ..models import Order
from .base import PaymentEvent, PaymentIntent, RefundResult, external_order_no


def mock_signature(secret: str, event_id: str, order_id: int, amount_cents: int) -> str:
    message = f"{event_id}:{order_id}:{amount_cents}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class MockProvider:
    name = "mock"
    needs_credentials = False

    def __init__(self, settings, http_client=None):
        self.settings = settings
        self.http = http_client

    def configured(self) -> bool:
        return True

    def require_configured(self) -> None:
        return None

    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        event_id = f"mock:{order.id}"
        signature = mock_signature(
            self.settings.mock_payment_secret, event_id, order.id, order.amount_cents
        )
        return PaymentIntent(
            provider=self.name,
            order_id=order.id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            external_order_no=external_order_no(order),
            action="client",
            params={
                "event_id": event_id,
                "signature": signature,
                "webhook_path": f"/v1/webhooks/{self.name}",
                "body": {
                    "event_id": event_id,
                    "event_type": "payment",
                    "order_id": order.id,
                    "external_order_no": external_order_no(order),
                    "amount_cents": order.amount_cents,
                    "status": "paid",
                },
            },
        )

    def parse_webhook(self, headers: dict[str, str], raw_body: bytes) -> PaymentEvent:
        if not (self.settings.mock_payment_secret or "").strip():
            raise ApiError(403, "mock_secret_missing", "mock 回调密钥未配置，拒绝验签与开通")
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "invalid_webhook", "回调体必须是 JSON")
        event_id = str(body.get("event_id") or "")
        try:
            order_id = int(body.get("order_id"))
            amount_cents = int(body.get("amount_cents"))
        except (TypeError, ValueError):
            raise ApiError(400, "invalid_webhook", "回调字段缺失或格式错误")
        signature = headers.get("x-mock-signature", "")
        expected = mock_signature(
            self.settings.mock_payment_secret, event_id, order_id, amount_cents
        )
        if not signature or not hmac.compare_digest(signature, expected):
            raise ApiError(400, "invalid_signature", "回调签名校验失败")
        status = str(body.get("status") or "paid")
        if status not in ("paid", "failed"):
            raise ApiError(400, "invalid_webhook", "未知支付状态")
        return PaymentEvent(
            event_id=event_id,
            event_type="payment",
            status=status,
            amount_cents=amount_cents,
            currency=str(body.get("currency") or "CNY"),
            order_id=order_id,
            external_order_no=str(body.get("external_order_no") or "") or None,
            provider_txn_id=str(body.get("provider_txn_id") or event_id),
            raw=body,
        )

    def _refund_event_id(self, order: Order) -> str:
        return f"mock-refund:{order.id}"

    def create_refund(self, refund, order: Order) -> RefundResult:
        ref = f"mock-refund-{refund.id}"
        return RefundResult(
            provider_refund_id=ref,
            status="succeeded",
            amount_cents=refund.amount_cents,
            raw={"refund_id": ref, "status": "succeeded"},
        )

    def query_refund(self, refund, order: Order) -> dict[str, Any]:
        return {"refund_id": refund.provider_refund_id, "status": refund.status}

    def query_payment(self, order: Order) -> dict[str, Any]:
        return {"out_trade_no": external_order_no(order), "trade_state": order.status}

    def close_payment(self, order: Order) -> dict[str, Any]:
        return {"out_trade_no": external_order_no(order), "closed": True}

    def download_bill(self, biz_date: str) -> list[dict[str, Any]]:
        return []
