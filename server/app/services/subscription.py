# -*- coding: utf-8 -*-
"""订阅状态机、套餐权益读取、订单开通与续费。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import CreditPack, Entitlement, Order, Plan, Subscription

ACTIVE_STATUSES = {"trialing", "active", "past_due"}
SERVICE_STATUSES = {"trialing", "active", "past_due", "paused"}
TERMINAL_STATUSES = {"canceled", "expired"}
ALL_STATUSES = SERVICE_STATUSES | TERMINAL_STATUSES

# 服务端强校验的状态迁移表
TRANSITIONS: dict[str, set[str]] = {
    "trialing": {"active", "past_due", "canceled", "expired"},
    "active": {"past_due", "paused", "canceled", "expired"},
    "past_due": {"active", "paused", "canceled", "expired"},
    "paused": {"active", "canceled", "expired"},
    "canceled": {"expired", "active"},
    "expired": {"active"},
}


def cycle_delta(cycle: str) -> timedelta:
    # 第一期用固定天数，避免引入日历月边界复杂度；上线前换成 relativedelta。
    return timedelta(days=365 if cycle == "year" else 30)


def plan_price(plan: Plan, cycle: str) -> int:
    return plan.price_year_cents if cycle == "year" else plan.price_month_cents


def get_active_subscription(session: Session, account_id: int) -> Subscription | None:
    return session.scalar(
        select(Subscription)
        .where(Subscription.account_id == account_id, Subscription.status.in_(ACTIVE_STATUSES))
        .order_by(Subscription.id.desc())
    )


def get_plan(session: Session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise ApiError(500, "plan_missing", "套餐数据缺失")
    return plan


def get_entitlements(session: Session, plan_id: int) -> dict[str, Entitlement]:
    rows = session.scalars(select(Entitlement).where(Entitlement.plan_id == plan_id)).all()
    return {row.key: row for row in rows}


def transition(sub: Subscription, target: str, now: datetime | None = None) -> Subscription:
    if target not in ALL_STATUSES:
        raise ApiError(422, "invalid_status", f"未知订阅状态：{target}")
    current = sub.status
    if current == target:
        return sub
    if target not in TRANSITIONS.get(current, set()):
        raise ApiError(409, "invalid_transition", f"订阅状态不允许从 {current} 变为 {target}")
    sub.status = target
    sub.version += 1
    if target == "expired":
        sub.current_end_at = min(sub.current_end_at, now or utcnow()) if sub.current_end_at else now or utcnow()
    sub.updated_at = now or utcnow()
    return sub


def find_plan_by_code(session: Session, code: str) -> Plan:
    plan = session.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise ApiError(404, "plan_not_found", f"套餐不存在：{code}")
    if not plan.active:
        raise ApiError(409, "plan_unavailable", f"套餐已下架，不可再下单：{code}")
    return plan


def create_subscription_order(
    session: Session,
    *,
    account_id: int,
    plan: Plan,
    cycle: str,
    provider: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> tuple[Subscription, Order]:
    now = now or utcnow()
    existing_active = get_active_subscription(session, account_id)
    if existing_active is not None:
        raise ApiError(409, "already_subscribed", "已有生效中的订阅，请先取消或到期后再购买")

    existing_order = session.scalar(
        select(Order).where(Order.account_id == account_id, Order.idempotency_key == idempotency_key)
    )
    if existing_order is not None:
        subscription = session.get(Subscription, existing_order.subscription_id) if existing_order.subscription_id else None
        if subscription is None:
            raise ApiError(409, "idempotency_conflict", "幂等键已被其他订单占用")
        return subscription, existing_order

    subscription = Subscription(
        account_id=account_id,
        plan_id=plan.id,
        status="trialing",
        seats=1,
        current_start_at=now,
        current_end_at=now + cycle_delta(cycle),
        trial_end_at=now + timedelta(days=7),
        provider=provider,
        version=1,
    )
    session.add(subscription)
    session.flush()

    order = Order(
        account_id=account_id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        amount_cents=plan_price(plan, cycle),
        currency=plan.currency,
        status="pending",
        provider=provider,
        kind="purchase",
        cycle=cycle,
        idempotency_key=idempotency_key,
    )
    session.add(order)
    session.flush()
    return subscription, order


def activate_paid_order(
    session: Session,
    order: Order,
    *,
    provider_txn_id: str,
    now: datetime | None = None,
) -> Subscription | None:
    now = now or utcnow()
    if order.kind == "credit_pack":
        return _activate_credit_pack(session, order, provider_txn_id=provider_txn_id, now=now)

    if order.status == "paid":
        subscription = session.get(Subscription, order.subscription_id) if order.subscription_id else None
        if subscription is None:
            raise ApiError(500, "order_subscription_missing", "订单缺少关联订阅")
        return subscription

    subscription = session.get(Subscription, order.subscription_id) if order.subscription_id else None
    if subscription is None:
        raise ApiError(500, "order_subscription_missing", "订单缺少关联订阅")

    order.status = "paid"
    order.paid_at = now
    order.provider_txn_id = provider_txn_id

    if order.kind == "upgrade":
        from .orders import apply_upgrade

        apply_upgrade(session, order, subscription, now)
        return subscription

    # 续费：从当前周期末尾顺延；首购：从支付时刻起算
    if order.kind == "renewal":
        base = max(subscription.current_end_at, now)
        subscription.current_end_at = base + cycle_delta(order.cycle)
        transition(subscription, "active", now)
    else:
        subscription.current_start_at = now
        subscription.current_end_at = now + cycle_delta(order.cycle)
        subscription.trial_end_at = None
        subscription.status = "active"
        subscription.version += 1
        subscription.updated_at = now
    subscription.provider = order.provider
    subscription.provider_sub_id = provider_txn_id
    return subscription


def _activate_credit_pack(
    session: Session, order: Order, *, provider_txn_id: str, now: datetime
) -> None:
    """额度包支付成功：标记订单 + 发放（order_id 幂等）。"""
    from . import credits

    if order.pack_id is None:
        raise ApiError(500, "order_pack_missing", "额度包订单缺少 pack_id")
    pack = session.get(CreditPack, order.pack_id)
    if pack is None:
        raise ApiError(500, "credit_pack_missing", "额度包数据缺失")
    order.status = "paid"
    order.paid_at = now
    order.provider_txn_id = provider_txn_id
    credits.grant_for_order(session, order, pack, now)
    session.flush()
    return None


def cancel_subscription(
    session: Session, sub: Subscription, *, immediate: bool, now: datetime | None = None
) -> Subscription:
    now = now or utcnow()
    if sub.status in ("canceled", "expired"):
        return sub
    if immediate:
        transition(sub, "canceled", now)
        sub.cancel_at_period_end = False
        sub.current_end_at = now
    else:
        if sub.status not in SERVICE_STATUSES:
            raise ApiError(409, "invalid_status", f"当前状态不可取消：{sub.status}")
        sub.cancel_at_period_end = True
        sub.version += 1
        sub.updated_at = now
    return sub


def resume_subscription(session: Session, sub: Subscription, now: datetime | None = None) -> Subscription:
    now = now or utcnow()
    if sub.status == "paused":
        transition(sub, "active", now)
        return sub
    if sub.cancel_at_period_end and sub.status in SERVICE_STATUSES:
        # 取消排期但尚未到期：撤销取消排期
        sub.cancel_at_period_end = False
        sub.version += 1
        sub.updated_at = now
        return sub
    if sub.status == "canceled" and sub.current_end_at > now:
        transition(sub, "active", now)
        sub.cancel_at_period_end = False
        return sub
    raise ApiError(409, "invalid_transition", "当前订阅不可恢复")


def create_renewal_order(
    session: Session,
    *,
    sub: Subscription,
    cycle: str,
    provider: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> Order:
    now = now or utcnow()
    if sub.status == "expired":
        raise ApiError(409, "subscription_expired", "订阅已过期，请重新购买")
    existing = session.scalar(
        select(Order).where(Order.account_id == sub.account_id, Order.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    plan = get_plan(session, sub.plan_id)
    order = Order(
        account_id=sub.account_id,
        subscription_id=sub.id,
        plan_id=plan.id,
        amount_cents=plan_price(plan, cycle),
        currency=plan.currency,
        status="pending",
        provider=provider,
        kind="renewal",
        cycle=cycle,
        idempotency_key=idempotency_key,
    )
    session.add(order)
    session.flush()
    return order


def expire_due(session: Session, now: datetime | None = None) -> int:
    """到期清扫：由定时任务调用（第一期只实现 active/trialing/canceled）。"""
    now = now or utcnow()
    rows = session.scalars(
        select(Subscription).where(
            Subscription.status.in_({"active", "trialing", "canceled"}),
            Subscription.current_end_at <= now,
        )
    ).all()
    for sub in rows:
        sub.status = "expired"
        sub.cancel_at_period_end = False
        sub.version += 1
        sub.updated_at = now
    return len(rows)


def reminders(
    session: Session, settings: Settings, now: datetime | None = None
) -> list[dict]:
    now = now or utcnow()
    rows = session.scalars(select(Subscription).where(Subscription.status.in_(ACTIVE_STATUSES))).all()
    result = []
    for sub in rows:
        days_left = (sub.current_end_at - now).total_seconds() / 86400
        if days_left <= settings.subscription_reminder_days:
            result.append(
                {
                    "subscription_id": sub.id,
                    "account_id": sub.account_id,
                    "status": sub.status,
                    "current_end_at": sub.current_end_at.isoformat(),
                    "days_left": round(max(days_left, 0), 1),
                    "renewal_required": True,
                }
            )
    return result
