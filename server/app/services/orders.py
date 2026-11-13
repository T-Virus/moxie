# -*- coding: utf-8 -*-
"""订单状态机、退款、升级补差、权益回收。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import Order, Plan, Refund, Subscription
from . import subscription as subsvc
from .audit import write_audit

ORDER_TRANSITIONS: dict[str, set[str]] = {
    "created": {"pending", "closed", "failed"},
    "pending": {"paid", "closed", "failed", "refunded"},
    "paid": {"refunded"},
    "closed": set(),
    "refunded": set(),
    "failed": set(),
}


def transition_order(order: Order, target: str, now: datetime | None = None) -> Order:
    if target not in ORDER_TRANSITIONS:
        raise ApiError(422, "invalid_order_status", f"未知订单状态：{target}")
    if order.status == target:
        return order
    if target not in ORDER_TRANSITIONS.get(order.status, set()):
        raise ApiError(409, "invalid_transition", f"订单状态不允许从 {order.status} 变为 {target}")
    order.status = target
    order.updated_at = now or utcnow()
    if target == "closed":
        order.closed_at = now or utcnow()
    return order


SENSITIVE_KEYS = (
    "key", "secret", "token", "sign", "password", "cert", "authorization",
    "id_card", "bank", "card", "openid", "payer",
)


def redact_payload(payload: Any, depth: int = 0) -> Any:
    """回调原文脱敏：砍掉签名/密钥类字段，长文本截断，最大 3 层。"""
    if depth > 3:
        return "..."
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(word in lowered for word in SENSITIVE_KEYS):
                out[key] = "[redacted]"
            else:
                out[key] = redact_payload(value, depth + 1)
        return out
    if isinstance(payload, (list, tuple)):
        return [redact_payload(item, depth + 1) for item in payload[:30]]
    if isinstance(payload, str):
        return payload[:200]
    return payload


def payload_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_order_amount(order: Order, amount_cents: int | None, currency: str | None) -> None:
    if amount_cents is None:
        raise ApiError(400, "invalid_webhook", "回调缺少金额")
    if int(amount_cents) != int(order.amount_cents):
        raise ApiError(400, "amount_mismatch", "回调金额与订单不一致")
    if currency and currency.upper() != order.currency.upper():
        raise ApiError(400, "currency_mismatch", "回调币种与订单不一致")


def create_refund(
    session: Session,
    *,
    order: Order,
    amount_cents: int,
    reason: str | None,
    idempotency_key: str,
    settings: Settings,
    actor_id: int | None = None,
    request=None,
    http_client=None,
) -> tuple[Refund, bool]:
    from ..payments import get_provider

    existing = session.scalar(
        select(Refund).where(
            Refund.account_id == order.account_id, Refund.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing, True

    if order.status not in ("paid", "refunded"):
        raise ApiError(409, "order_not_refundable", f"订单状态不可退款：{order.status}")
    remaining = order.amount_cents - order.refunded_cents
    if amount_cents <= 0:
        raise ApiError(422, "invalid_amount", "退款金额必须大于 0")
    if amount_cents > remaining:
        raise ApiError(422, "refund_amount_exceeded", f"退款金额超过可退余额（{remaining} 分）")

    refund = Refund(
        order_id=order.id,
        account_id=order.account_id,
        amount_cents=amount_cents,
        currency=order.currency,
        status="pending",
        provider=order.provider,
        reason=(reason or "")[:200] or None,
        idempotency_key=idempotency_key,
        meta={},
    )
    session.add(refund)
    session.flush()

    provider = get_provider(order.provider, settings, http_client=http_client)
    try:
        result = provider.create_refund(refund, order)
    except ApiError:
        refund.status = "failed"
        refund.meta = {"error": "provider_error"}
        session.flush()
        raise
    refund.provider_refund_id = result.provider_refund_id
    refund.meta = {"provider_status": result.status, "raw": redact_payload(result.raw)}
    if result.status == "succeeded":
        apply_refund_result(session, refund, order, "succeeded")
    elif result.status == "failed":
        refund.status = "failed"
    write_audit(
        session,
        actor_id=actor_id,
        action="order.refund",
        request=request,
        target_type="order",
        target_id=order.id,
        meta={
            "refund_id": refund.id,
            "amount_cents": amount_cents,
            "provider": order.provider,
            "provider_refund_id": refund.provider_refund_id,
            "status": refund.status,
        },
    )
    return refund, False


def apply_refund_result(
    session: Session,
    refund: Refund,
    order: Order,
    status: str,
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    if refund.status == "succeeded":
        return
    # 渠道异步退款通知用 "refunded"/"refund_failed"，服务端主动退款用
    # "succeeded"/"failed"。曾因未归一导致成功回调被当作 pending 丢弃：
    # 不累加 refunded_cents、不回收权益、订单状态不推进。
    status = {"refunded": "succeeded", "refund_failed": "failed"}.get(status, status)
    if status != "succeeded":
        refund.status = "failed" if status == "failed" else "pending"
        refund.meta = {**(refund.meta or {}), "callback_status": status}
        return
    if order.refunded_cents + refund.amount_cents > order.amount_cents:
        raise ApiError(409, "refund_amount_exceeded", "累计退款超过订单金额")
    refund.status = "succeeded"
    refund.succeeded_at = now
    order.refunded_cents += refund.amount_cents
    # 无论全额还是部分退款，都按比例回收权益；全额时回收更彻底
    _recover_entitlements(session, order, now)
    if order.refunded_cents >= order.amount_cents:
        transition_order(order, "refunded", now)


def _recover_entitlements(session: Session, order: Order, now: datetime) -> None:
    """退款回收权益。

    全额退款：额度包作废；订阅购卡/续费立即失效；升级回退到原套餐。
    部分退款：额度包按退款比例扣减剩余；订阅按剩余金额比例缩短剩余时长。
    """
    from . import credits

    if order.kind == "credit_pack":
        credits.revoke_for_refund(session, order, order.refunded_cents, now)
        return
    if not order.subscription_id:
        return
    subscription = session.get(Subscription, order.subscription_id)
    if subscription is None:
        return

    fully_refunded = order.refunded_cents >= order.amount_cents
    if order.kind == "upgrade":
        previous = (order.meta or {}).get("previous_plan_id")
        if previous and fully_refunded:
            subscription.plan_id = int(previous)
            subscription.version += 1
            subscription.updated_at = now
        return

    if fully_refunded:
        subscription.status = "canceled"
        subscription.current_end_at = now
        subscription.cancel_at_period_end = False
        subscription.version += 1
        subscription.updated_at = now
        return

    # 部分退款：只缩短剩余时长，不直接取消
    ratio = max(0.0, 1.0 - order.refunded_cents / max(order.amount_cents, 1))
    remaining = max((subscription.current_end_at - now).total_seconds(), 0)
    subscription.current_end_at = now + timedelta(seconds=remaining * ratio)
    subscription.version += 1
    subscription.updated_at = now


def create_upgrade_order(
    session: Session,
    *,
    sub: Subscription,
    plan: Plan,
    provider: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> Order:
    """手动升级补差：按剩余天数占当月比例，补「新套餐 - 旧套餐」的差额。"""
    now = now or utcnow()
    existing = session.scalar(
        select(Order).where(Order.account_id == sub.account_id, Order.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    current = subsvc.get_plan(session, sub.plan_id)
    if plan.id == current.id:
        raise ApiError(409, "already_on_plan", "当前已是该套餐")
    if plan.price_month_cents <= current.price_month_cents:
        raise ApiError(409, "downgrade_not_supported", "暂不支持降级，请先取消后重新购买")
    if plan.currency != current.currency:
        raise ApiError(422, "currency_mismatch", "套餐币种不一致")
    # 已过期订阅 remaining=0 → 补差也为 0，曾被直接置为 paid 并免费升级到更贵套餐。
    # 升级必须以「仍在有效期内的订阅」为前提。
    if sub.current_end_at <= now or sub.status not in subsvc.SERVICE_STATUSES:
        raise ApiError(409, "subscription_not_active", "当前订阅不在有效期内，无法升级，请先续费")

    total = max((sub.current_end_at - sub.current_start_at).total_seconds(), 1)
    remaining = max((sub.current_end_at - now).total_seconds(), 0)
    ratio = min(remaining / total, 1.0)
    credit = int(round(current.price_month_cents * ratio))
    target = int(round(plan.price_month_cents * ratio))
    amount = max(target - credit, 0)
    order = Order(
        account_id=sub.account_id,
        subscription_id=sub.id,
        plan_id=plan.id,
        amount_cents=amount,
        currency=plan.currency,
        status="paid" if amount == 0 else "pending",
        provider=provider,
        kind="upgrade",
        cycle="month",
        idempotency_key=idempotency_key,
        paid_at=now if amount == 0 else None,
        meta={
            "previous_plan_id": current.id,
            "previous_plan_code": current.code,
            "target_plan_code": plan.code,
            "credit_cents": credit,
            "target_cents": target,
            "ratio": round(ratio, 6),
        },
    )
    session.add(order)
    session.flush()
    if amount == 0:
        apply_upgrade(session, order, sub, now)
    return order


def apply_upgrade(session: Session, order: Order, sub: Subscription, now: datetime | None = None) -> None:
    now = now or utcnow()
    if order.kind != "upgrade":
        return
    sub.plan_id = order.plan_id
    sub.status = "active"
    sub.version += 1
    sub.updated_at = now
    order.status = "paid"
    order.paid_at = order.paid_at or now
