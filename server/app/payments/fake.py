# -*- coding: utf-8 -*-
"""fake 渠道：与 mock 同构，但只在非生产 / 显式开启时可用。

用途：无商户凭据时跑通「下单 → 回调 → 开通 → 续费 → 退款 → 对账」全流程。
"""

from __future__ import annotations

from ..models import Order
from .base import PaymentIntent, RefundResult, external_order_no
from .mock import MockProvider, mock_signature


class FakeProvider(MockProvider):
    name = "fake"
    needs_credentials = False

    def configured(self) -> bool:
        return self.settings.payments_fake_enabled or self.settings.env != "production"

    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        self.require_configured()
        event_id = f"fake:{order.id}"
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
                "webhook_path": "/v1/webhooks/fake",
                "body": {
                    "event_id": event_id,
                    "event_type": "payment",
                    "order_id": order.id,
                    "external_order_no": external_order_no(order),
                    "amount_cents": order.amount_cents,
                    "status": "paid",
                },
                "refund": {
                    "webhook_path": "/v1/webhooks/fake",
                    "body": {
                        "event_id": f"fake-refund:{order.id}",
                        "event_type": "refund",
                        "order_id": order.id,
                        "refund_ref": f"fake-refund-{order.id}",
                        "amount_cents": order.amount_cents,
                        "status": "refunded",
                    },
                },
            },
        )

    def create_refund(self, refund, order: Order) -> RefundResult:
        self.require_configured()
        ref = f"fake-refund-{order.id}"
        return RefundResult(
            provider_refund_id=ref,
            status="succeeded",
            amount_cents=refund.amount_cents,
            raw={"refund_id": ref, "status": "succeeded"},
        )
