# -*- coding: utf-8 -*-
"""Stripe（Checkout Session + Webhook + Portal + Refund + 对账）。

Webhook 签名：`Stripe-Signature: t=<ts>,v1=<hex>`；签名串 `t.raw_body`，
HMAC-SHA256(webhook_secret)，容差默认 300s。安装官方 `stripe` 库时优先用官方实现。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from ..errors import ApiError
from ..models import Order
from .base import PaymentEvent, PaymentIntent, RefundResult, external_order_no


class StripeProvider:
    name = "stripe"
    needs_credentials = True

    def __init__(self, settings, http_client=None):
        self.settings = settings
        self.http = http_client

    def configured(self) -> bool:
        return bool(self.settings.stripe_secret_key and self.settings.stripe_webhook_secret)

    def require_configured(self) -> None:
        if not self.configured():
            raise ApiError(
                501,
                "provider_not_configured",
                "Stripe 未配置：需要 STRIPE_SECRET_KEY 与 STRIPE_WEBHOOK_SECRET",
            )

    # ---- REST --------------------------------------------------------------
    def _request(self, method: str, path: str, data: dict | None = None, idempotency: str | None = None) -> dict[str, Any]:
        self.require_configured()
        headers = {"Authorization": f"Bearer {self.settings.stripe_secret_key}"}
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        body = None
        if data:
            body = urlencode(data, doseq=True).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        client = self.http or httpx.Client(timeout=self.settings.payment_timeout_seconds)
        try:
            response = client.request(
                method, self.settings.stripe_api_base + path, content=body, headers=headers
            )
        except httpx.HTTPError as exc:
            raise ApiError(502, "provider_unreachable", f"Stripe 网络异常：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(502, "provider_error", "Stripe 返回非 JSON") from exc
        if response.status_code >= 300:
            message = (payload.get("error") or {}).get("message", "")
            raise ApiError(502, "provider_error", f"Stripe 返回 {response.status_code}：{message}"[:200])
        return payload

    def _checkout(self, order: Order) -> dict[str, Any]:
        out_no = external_order_no(order)
        data = {
            "mode": "payment",
            "success_url": self.settings.stripe_success_url + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": self.settings.stripe_cancel_url,
            "client_reference_id": str(order.id),
            "customer_creation": "always",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": order.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(order.amount_cents),
            "line_items[0][price_data][product_data][name]": f"墨写订阅#{order.id}",
            "metadata[order_id]": str(order.id),
            "metadata[external_order_no]": out_no,
            "payment_intent_data[metadata][order_id]": str(order.id),
            "payment_intent_data[metadata][external_order_no]": out_no,
        }
        return self._request("POST", "/v1/checkout/sessions", data, idempotency=f"checkout:{order.id}")

    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        self.require_configured()
        session = self._checkout(order)
        out_no = external_order_no(order)
        order.external_order_no = out_no
        return PaymentIntent(
            provider=self.name,
            order_id=order.id,
            amount_cents=order.amount_cents,
            currency=order.currency,
            external_order_no=out_no,
            action="redirect",
            params={"checkout_session_id": session.get("id"), "url": session.get("url")},
        )

    def query_payment(self, order: Order) -> dict[str, Any]:
        return self._request("GET", f"/v1/checkout/sessions?client_reference_id={order.id}")

    def close_payment(self, order: Order) -> dict[str, Any]:
        # Stripe Checkout Session 可过期；这里主动 expire 最近一个 session
        listing = self.query_payment(order)
        rows = listing.get("data") or []
        if not rows:
            return {"closed": False}
        return self._request("POST", f"/v1/checkout/sessions/{rows[0]['id']}/expire")

    # ---- Webhook -----------------------------------------------------------
    def verify_webhook(self, headers: dict[str, str], raw_body: bytes) -> dict[str, Any]:
        self.require_configured()
        header = headers.get("stripe-signature", "")
        try:
            stripe = __import__("stripe")
        except ImportError:
            stripe = None
        if stripe is not None:
            try:
                return stripe.Webhook.construct_event(
                    raw_body, header, self.settings.stripe_webhook_secret
                )
            except Exception as exc:  # noqa: BLE001
                raise ApiError(400, "invalid_signature", "Stripe webhook 验签失败") from exc
        items = {}
        for part in header.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                items.setdefault(key, []).append(value)
        timestamp = (items.get("t") or [""])[0]
        signatures = items.get("v1") or []
        if not timestamp.isdigit() or not signatures:
            raise ApiError(400, "invalid_signature", "Stripe 签名头格式错误")
        if abs(int(time.time()) - int(timestamp)) > self.settings.webhook_tolerance_seconds:
            raise ApiError(400, "webhook_expired", "Stripe 回调时间戳超出容差")
        signed = f"{timestamp}.".encode() + raw_body
        expected = hmac.new(
            self.settings.stripe_webhook_secret.encode(), signed, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in signatures):
            raise ApiError(400, "invalid_signature", "Stripe webhook 验签失败")
        try:
            return json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            raise ApiError(400, "invalid_webhook", "Stripe 回调体必须是 JSON")

    def parse_webhook(self, headers: dict[str, str], raw_body: bytes) -> PaymentEvent:
        event = self.verify_webhook(headers, raw_body)
        event_id = str(event.get("id") or "")
        if not event_id:
            raise ApiError(400, "invalid_webhook", "Stripe 事件缺少 id")
        event_type = str(event.get("type") or "")
        obj = (event.get("data") or {}).get("object") or {}
        metadata = obj.get("metadata") or {}
        order_id = None
        raw_order = obj.get("client_reference_id") or metadata.get("order_id")
        if raw_order and str(raw_order).isdigit():
            order_id = int(raw_order)
        external_no = metadata.get("external_order_no")

        if event_type in ("checkout.session.completed", "payment_intent.succeeded", "invoice.paid"):
            amount = obj.get("amount_total")
            if amount is None:
                amount = obj.get("amount_received")
            if amount is None:
                amount = obj.get("amount_paid")
            return PaymentEvent(
                event_id=event_id,
                event_type="payment",
                status="paid",
                amount_cents=int(amount or 0),
                currency=str(obj.get("currency") or "CNY").upper(),
                order_id=order_id,
                external_order_no=external_no,
                provider_txn_id=str(obj.get("payment_intent") or obj.get("id") or ""),
                raw={"type": event_type},
            )
        if event_type == "payment_intent.payment_failed":
            return PaymentEvent(
                event_id=event_id,
                event_type="payment",
                status="failed",
                amount_cents=int(obj.get("amount") or 0),
                currency=str(obj.get("currency") or "CNY").upper(),
                order_id=order_id,
                external_order_no=external_no,
                provider_txn_id=str(obj.get("id") or ""),
                raw={"type": event_type},
            )
        if event_type in ("charge.refunded", "refund.updated", "refund.created"):
            refund_obj = obj if obj.get("object") == "refund" else obj
            amount = obj.get("amount_refunded")
            if amount is None:
                amount = obj.get("amount")
            status = "refunded" if str(obj.get("status") or "") == "succeeded" else "pending"
            if event_type == "charge.refunded" or str(obj.get("status")) == "succeeded":
                status = "refunded"
            if str(obj.get("status") or "") in ("failed", "canceled"):
                status = "refund_failed"
            return PaymentEvent(
                event_id=event_id,
                event_type="refund",
                status=status,
                amount_cents=int(amount or 0),
                currency=str(obj.get("currency") or "CNY").upper(),
                order_id=order_id,
                external_order_no=external_no,
                provider_txn_id=str(obj.get("payment_intent") or ""),
                refund_ref=str(obj.get("id") or ""),
                raw={"type": event_type},
            )
        raise ApiError(400, "unsupported_event", f"未处理的 Stripe 事件：{event_type}")

    # ---- 退款 / 门户 -------------------------------------------------------
    def create_refund(self, refund, order: Order) -> RefundResult:
        data = {
            "payment_intent": order.provider_txn_id,
            "amount": str(refund.amount_cents),
            "reason": "requested_by_customer",
            "metadata[order_id]": str(order.id),
            "metadata[refund_id]": str(refund.id),
        }
        result = self._request(
            "POST", "/v1/refunds", data, idempotency=f"refund:{refund.id}"
        )
        status = {"succeeded": "succeeded", "pending": "pending"}.get(
            str(result.get("status") or ""), "failed"
        )
        return RefundResult(
            provider_refund_id=str(result.get("id") or ""),
            status=status,
            amount_cents=refund.amount_cents,
            raw={"status": result.get("status")},
        )

    def query_refund(self, refund, order: Order) -> dict[str, Any]:
        return self._request("GET", f"/v1/refunds/{refund.provider_refund_id}")

    def portal(self, subscription) -> dict[str, Any] | None:
        customer = subscription.provider_sub_id or ""
        if not customer.startswith("cus_"):
            return None
        session = self._request(
            "POST",
            "/v1/billing_portal/sessions",
            {"customer": customer, "return_url": self.settings.stripe_portal_return_url},
        )
        return {"url": session.get("url")}

    # ---- 对账 --------------------------------------------------------------
    def download_bill(self, biz_date: str) -> list[dict[str, Any]]:
        start = int(datetime.strptime(biz_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        end = start + 86400
        data = self._request(
            "GET",
            f"/v1/payment_intents?created[gte]={start}&created[lt]={end}&limit=100",
        )
        result = []
        for item in data.get("data") or []:
            metadata = item.get("metadata") or {}
            if str(item.get("status")) != "succeeded":
                continue
            result.append(
                {
                    "external_order_no": metadata.get("external_order_no")
                    or f"MX{int(metadata.get('order_id', 0)):012d}",
                    "amount_cents": int(item.get("amount_received") or item.get("amount") or 0),
                    "provider_txn_id": str(item.get("id") or ""),
                    "status": "paid",
                }
            )
        return result
