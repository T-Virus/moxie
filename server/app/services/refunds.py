# -*- coding: utf-8 -*-
"""退款报价：按「已用量」折算可退金额（升级补差/部分退款）。

口径（写进 docs/billing-admin.md）：
  · 订阅类订单（purchase/renewal）：可退比例 = 1 - 当前周期已用额度占比；
  · 升级订单：可退比例 = 当前周期剩余时间占比（补差对应剩余时长）；
  · 额度包订单：可退比例 = 包内剩余额度占比；
  · 报价只做建议值，最终退款金额仍由管理端确认并落审计。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import CreditGrant, Order, Subscription, UsageAggregate
from . import subscription as subsvc
from .quota import period_of


def quote(session: Session, order: Order, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if order.status not in ("paid", "refunded"):
        raise ApiError(409, "order_not_refundable", f"订单状态不可退款：{order.status}")
    remaining = max(order.amount_cents - order.refunded_cents, 0)
    result = {
        "order_id": order.id,
        "kind": order.kind,
        "amount_cents": order.amount_cents,
        "refunded_cents": order.refunded_cents,
        "refundable_cents": 0,
        "ratio": 0.0,
        "method": "none",
        "used_ratio": None,
        "time_ratio": None,
    }
    if remaining <= 0:
        return result

    if order.kind == "credit_pack":
        grant = session.scalar(select(CreditGrant).where(CreditGrant.order_id == order.id))
        if grant is None:
            result.update(refundable_cents=remaining, ratio=1.0, method="ungranted")
            return result
        total = max(grant.quantity_granted, 1)
        unused = max(grant.quantity_granted - grant.quantity_used, 0)
        ratio = unused / total
        result.update(
            refundable_cents=int(round(remaining * ratio)),
            ratio=round(ratio, 4),
            method="credit_pack_unused",
            used_ratio=round(1 - ratio, 4),
        )
        return result

    sub = session.get(Subscription, order.subscription_id) if order.subscription_id else None
    if sub is None:
        result.update(refundable_cents=remaining, ratio=1.0, method="no_subscription")
        return result

    total_seconds = max((sub.current_end_at - sub.current_start_at).total_seconds(), 1)
    remaining_seconds = max((sub.current_end_at - now).total_seconds(), 0)
    time_ratio = min(remaining_seconds / total_seconds, 1.0)
    result["time_ratio"] = round(time_ratio, 4)

    if order.kind == "upgrade":
        result.update(
            refundable_cents=int(round(remaining * time_ratio)),
            ratio=round(time_ratio, 4),
            method="upgrade_remaining_time",
        )
        return result

    # purchase / renewal：按当前周期已用额度占比
    start, _ = period_of(now)
    used_ratio = 0.0
    plan_id = sub.plan_id
    for key, ent in subsvc.get_entitlements(session, plan_id).items():
        if int(ent.limit_value or 0) <= 0:
            continue
        agg = session.scalar(
            select(UsageAggregate).where(
                UsageAggregate.account_id == order.account_id,
                UsageAggregate.metric == key,
                UsageAggregate.period_start == start,
            )
        )
        if agg is not None:
            used_ratio = max(used_ratio, min(agg.used / int(ent.limit_value), 1.0))
    ratio = max(1.0 - used_ratio, 0.0)
    result.update(
        refundable_cents=int(round(remaining * ratio)),
        ratio=round(ratio, 4),
        method="subscription_usage",
        used_ratio=round(used_ratio, 4),
    )
    return result
