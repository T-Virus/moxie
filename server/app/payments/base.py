# -*- coding: utf-8 -*-
"""支付渠道统一抽象。

业务层只依赖 PaymentIntent / PaymentEvent / RefundResult，不感知渠道差异。
回调解析必须接收**原始字节**：JSON 重新序列化会破坏签名。
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..errors import ApiError
from ..models import Order, Refund, Subscription


def money(cents: int, currency: str = "CNY") -> str:
    """分 → 渠道要求的两位小数字符串（CNY）。"""
    if cents < 0:
        raise ApiError(422, "invalid_amount", "金额不能为负")
    return f"{cents / 100:.2f}"


def cents_from(amount: Any) -> int:
    try:
        return int(round(float(amount) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_amount", "回调金额格式错误")


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def external_order_no(order: Order) -> str:
    """统一商户订单号：MX + 12 位订单号；微信 ≤32 / 支付宝 ≤64。"""
    return order.external_order_no or f"MX{order.id:012d}"


@dataclass
class PaymentIntent:
    provider: str
    order_id: int
    amount_cents: int
    currency: str
    external_order_no: str = ""
    action: str = "redirect"  # redirect|qrcode|jsapi|client
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    provider_refund_id: str
    status: str  # succeeded|pending|failed
    amount_cents: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentEvent:
    event_id: str
    event_type: str  # payment|refund
    status: str  # paid|failed|refunded|refund_failed
    amount_cents: int | None = None
    currency: str | None = None
    order_id: int | None = None
    external_order_no: str | None = None
    provider_txn_id: str = ""
    refund_ref: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider:
    name = "base"
    # 真实渠道需要商户凭据；fake/mock 不需要
    needs_credentials = False

    def __init__(self, settings: Settings, http_client=None):
        self.settings = settings
        self.http = http_client

    # ---- 能力探测与配置校验 ------------------------------------------------
    def configured(self) -> bool:
        return True

    def require_configured(self) -> None:
        if not self.configured():
            raise ApiError(
                501,
                "provider_not_configured",
                f"{self.name} 支付未配置：请补齐商户凭据（见 docs/payments.md）",
            )

    # ---- 支付 --------------------------------------------------------------
    def create_payment(self, order: Order, context: dict | None = None) -> PaymentIntent:
        raise ApiError(501, "provider_not_configured", f"{self.name} 下单接口未接入")

    def query_payment(self, order: Order) -> dict[str, Any]:
        raise ApiError(501, "provider_not_configured", f"{self.name} 查单接口未接入")

    def close_payment(self, order: Order) -> dict[str, Any]:
        raise ApiError(501, "provider_not_configured", f"{self.name} 关单接口未接入")

    # ---- 退款 --------------------------------------------------------------
    def create_refund(self, refund: Refund, order: Order) -> RefundResult:
        raise ApiError(501, "provider_not_configured", f"{self.name} 退款接口未接入")

    def query_refund(self, refund: Refund, order: Order) -> dict[str, Any]:
        raise ApiError(501, "provider_not_configured", f"{self.name} 退款查询接口未接入")

    # ---- 回调与对账 --------------------------------------------------------
    def parse_webhook(self, headers: dict[str, str], raw_body: bytes) -> PaymentEvent:
        raise ApiError(501, "provider_not_configured", f"{self.name} 回调未接入")

    def download_bill(self, biz_date: str) -> list[dict[str, Any]]:
        """返回渠道账单记录：[{external_order_no, provider_txn_id, amount_cents, status}]."""
        raise ApiError(501, "bill_not_supported", f"{self.name} 账单下载未接入")

    # ---- 订阅门户（Stripe 等） --------------------------------------------
    def portal(self, subscription: Subscription) -> dict[str, Any] | None:
        return None
