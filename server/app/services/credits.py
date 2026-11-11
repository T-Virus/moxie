# -*- coding: utf-8 -*-
"""一次性额度包（credit packs）。

口径：
  · 额度包与套餐额度互不影响：套餐先扣，超出部分才扣包；
  · 包按「先到期先扣」（FIFO by expires_at）消耗；
  · 有效期默认 12 个月，到期后剩余作废，不结转、不清零已用；
  · 一份订单只发一次包（order_id 唯一 + idempotency_key 唯一），回调重放不重复发放。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import CreditGrant, CreditPack, Order


def list_packs(session: Session) -> list[CreditPack]:
    return session.scalars(
        select(CreditPack).where(CreditPack.active.is_(True)).order_by(CreditPack.id.asc())
    ).all()


def find_pack(session: Session, code: str) -> CreditPack:
    pack = session.scalar(select(CreditPack).where(CreditPack.code == code, CreditPack.active.is_(True)))
    if pack is None:
        raise ApiError(404, "credit_pack_not_found", "额度包不存在或已下架")
    return pack


def pack_view(pack: CreditPack) -> dict:
    return {
        "code": pack.code,
        "name": pack.name,
        "metric": pack.metric,
        "quantity": pack.quantity,
        "price_cents": pack.price_cents,
        "currency": pack.currency,
        "validity_days": pack.validity_days,
    }


def create_pack_order(
    session: Session,
    *,
    account_id: int,
    pack: CreditPack,
    provider: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> Order:
    existing = session.scalar(
        select(Order).where(Order.account_id == account_id, Order.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.kind != "credit_pack":
            raise ApiError(409, "idempotency_conflict", "幂等键已被其他订单占用")
        return existing
    order = Order(
        account_id=account_id,
        subscription_id=None,
        plan_id=None,
        pack_id=pack.id,
        amount_cents=pack.price_cents,
        currency=pack.currency,
        status="pending",
        provider=provider,
        kind="credit_pack",
        cycle="once",
        idempotency_key=idempotency_key,
        meta={"pack_code": pack.code, "metric": pack.metric, "quantity": pack.quantity},
    )
    session.add(order)
    session.flush()
    return order


def grant_for_order(
    session: Session, order: Order, pack: CreditPack, now: datetime | None = None
) -> CreditGrant:
    """支付成功后发放；按 order_id 幂等，重复回调返回同一条 grant。"""
    now = now or utcnow()
    existing = session.scalar(select(CreditGrant).where(CreditGrant.order_id == order.id))
    if existing is not None:
        return existing
    expires_at = now + timedelta(days=int(pack.validity_days or 365))
    grant = CreditGrant(
        account_id=order.account_id,
        pack_id=pack.id,
        order_id=order.id,
        metric=pack.metric,
        quantity_granted=pack.quantity,
        quantity_used=0,
        quantity_reserved=0,
        status="active",
        valid_from=now,
        expires_at=expires_at,
        idempotency_key=f"grant:order:{order.id}",
        meta={"pack_code": pack.code, "validity_days": pack.validity_days},
    )
    session.add(grant)
    session.flush()
    return grant


def active_grants(
    session: Session, account_id: int, metric: str, now: datetime | None = None
) -> list[CreditGrant]:
    now = now or utcnow()
    return list(
        session.scalars(
            select(CreditGrant)
            .where(
                CreditGrant.account_id == account_id,
                CreditGrant.metric == metric,
                CreditGrant.status == "active",
                CreditGrant.expires_at > now,
            )
            .order_by(CreditGrant.expires_at.asc(), CreditGrant.id.asc())
        ).all()
    )


def available(session: Session, account_id: int, metric: str, now: datetime | None = None) -> int:
    return sum(
        max(g.quantity_granted - g.quantity_used - g.quantity_reserved, 0)
        for g in active_grants(session, account_id, metric, now)
    )


def reserve_pack(
    session: Session,
    account_id: int,
    metric: str,
    quantity: int,
    now: datetime | None = None,
) -> tuple[dict, ...]:
    """按先到期先扣预占；不足时抛 402。返回 [{'grant_id','quantity'}]。"""
    now = now or utcnow()
    remaining = quantity
    items: list[dict] = []
    for grant in active_grants(session, account_id, metric, now):
        free = max(grant.quantity_granted - grant.quantity_used - grant.quantity_reserved, 0)
        if free <= 0:
            continue
        take = min(free, remaining)
        grant.quantity_reserved += take
        grant.status = "active"
        items.append({"grant_id": grant.id, "quantity": take})
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        # 回滚本次预占，避免半途占用
        release_pack(session, tuple(items))
        raise ApiError(402, "credit_pack_insufficient", "套餐额度已用尽，且额度包余额不足")
    session.flush()
    return tuple(items)


def commit_pack(session: Session, items: tuple[dict, ...] | list[dict], now: datetime | None = None) -> None:
    """把预占转成已用；已用完的包标记 depleted。"""
    now = now or utcnow()
    for item in items or ():
        grant = session.get(CreditGrant, int(item["grant_id"]))
        if grant is None:
            continue
        qty = int(item["quantity"])
        grant.quantity_reserved = max(grant.quantity_reserved - qty, 0)
        grant.quantity_used += qty
        if grant.quantity_used + grant.quantity_reserved >= grant.quantity_granted:
            grant.status = "depleted"
        session.flush()


def release_pack(session: Session, items: tuple[dict, ...] | list[dict]) -> None:
    for item in items or ():
        grant = session.get(CreditGrant, int(item["grant_id"]))
        if grant is None:
            continue
        grant.quantity_reserved = max(grant.quantity_reserved - int(item["quantity"]), 0)
        if grant.status in ("depleted", "expired") and grant.quantity_used < grant.quantity_granted:
            grant.status = "expired" if grant.expires_at <= utcnow() else "active"
    session.flush()


def summary(session: Session, account_id: int, now: datetime | None = None) -> list[dict]:
    """合并视图：按 metric 汇总可用/已用/最近到期时间。"""
    now = now or utcnow()
    rows = session.scalars(
        select(CreditGrant)
        .where(CreditGrant.account_id == account_id, CreditGrant.status.in_({"active", "depleted"}))
        .order_by(CreditGrant.expires_at.asc())
    ).all()
    metrics: dict[str, dict] = {}
    for grant in rows:
        item = metrics.setdefault(
            grant.metric,
            {
                "metric": grant.metric,
                "granted": 0,
                "used": 0,
                "reserved": 0,
                "remaining": 0,
                "active_grants": 0,
                "next_expires_at": None,
            },
        )
        item["granted"] += grant.quantity_granted
        item["used"] += grant.quantity_used
        item["reserved"] += grant.quantity_reserved
        free = max(grant.quantity_granted - grant.quantity_used - grant.quantity_reserved, 0)
        if free > 0 and grant.expires_at > now:
            item["remaining"] += free
            item["active_grants"] += 1
            if item["next_expires_at"] is None:
                item["next_expires_at"] = grant.expires_at.isoformat()
    return list(metrics.values())


def expire_grants(session: Session, now: datetime | None = None) -> int:
    """把到期未用完的包标记 expired（剩余不结转）；幂等。"""
    now = now or utcnow()
    rows = session.scalars(
        select(CreditGrant).where(CreditGrant.status == "active", CreditGrant.expires_at <= now)
    ).all()
    for grant in rows:
        grant.status = "expired"
    if rows:
        session.flush()
    return len(rows)


def revoke_for_refund(
    session: Session, order: Order, refunded_cents: int, now: datetime | None = None
) -> None:
    """额度包退款：按退款比例回收剩余额度（全额退款即整包作废）。"""
    now = now or utcnow()
    grant = session.scalar(select(CreditGrant).where(CreditGrant.order_id == order.id))
    if grant is None:
        return
    if refunded_cents >= order.amount_cents:
        grant.status = "revoked"
        return
    ratio = min(max(refunded_cents / max(order.amount_cents, 1), 0), 1)
    remaining = max(grant.quantity_granted - grant.quantity_used - grant.quantity_reserved, 0)
    grant.quantity_granted = max(
        grant.quantity_used + grant.quantity_reserved + int(round(remaining * (1 - ratio)), 0),
        grant.quantity_used + grant.quantity_reserved,
    )
    grant.meta = {**(grant.meta or {}), "refund_revoked_cents": refunded_cents, "refund_ratio": round(ratio, 4)}
    if grant.quantity_granted <= grant.quantity_used:
        grant.status = "depleted"
