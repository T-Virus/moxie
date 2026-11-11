# -*- coding: utf-8 -*-
"""支付渠道注册表。"""

from __future__ import annotations

from ..errors import ApiError
from .alipay import AlipayProvider
from .base import (
    PaymentEvent,
    PaymentIntent,
    PaymentProvider,
    RefundResult,
    cents_from,
    external_order_no,
    money,
)
from .fake import FakeProvider
from .mock import MockProvider, mock_signature
from .stripe import StripeProvider
from .wechat import WeChatPayProvider

PROVIDERS = {
    "mock": MockProvider,
    "fake": FakeProvider,
    "wechat": WeChatPayProvider,
    "alipay": AlipayProvider,
    "stripe": StripeProvider,
}

PROVIDER_LABELS = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "stripe": "银行卡 / Stripe",
    "mock": "模拟支付（仅测试）",
    "fake": "假支付（仅测试）",
}
_PROVIDER_ORDER = ("wechat", "alipay", "stripe", "mock", "fake")


def available_providers(settings) -> list[dict]:
    """当前环境下真正可下单的渠道（不返回任何凭据）。"""
    items: list[dict] = []
    for name in _PROVIDER_ORDER:
        try:
            provider = get_provider(name, settings)
        except ApiError:
            continue
        if not provider.configured():
            continue
        items.append(
            {
                "id": name,
                "name": PROVIDER_LABELS[name],
                "test_only": name in ("mock", "fake"),
            }
        )
    return items


def get_provider(name: str, settings, http_client=None) -> PaymentProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ApiError(404, "unknown_provider", f"未知支付渠道：{name}")
    # mock/fake 只能用于测试环境；生产/预发必须禁止注册与调用
    if name in ("mock", "fake"):
        if settings.env not in ("test", "dev"):
            raise ApiError(403, "provider_not_allowed_in_env", f"{name} 渠道仅限测试环境")
        if name == "mock" and not settings.payments_mock_enabled:
            raise ApiError(403, "mock_payment_disabled", "mock 支付渠道未启用")
        if name == "fake" and not settings.payments_fake_enabled:
            raise ApiError(403, "fake_payment_disabled", "fake 支付渠道未启用")
        if not (settings.mock_payment_secret or "").strip():
            raise ApiError(
                403,
                "mock_secret_missing",
                "mock/fake 渠道必须配置 MOCK_PAYMENT_SECRET，否则回调无法验签",
            )
    return cls(settings, http_client=http_client)


__all__ = [
    "PROVIDERS",
    "PROVIDER_LABELS",
    "available_providers",
    "get_provider",
    "PaymentEvent",
    "PaymentIntent",
    "PaymentProvider",
    "RefundResult",
    "cents_from",
    "external_order_no",
    "money",
    "MockProvider",
    "FakeProvider",
    "WeChatPayProvider",
    "AlipayProvider",
    "StripeProvider",
    "mock_signature",
]
