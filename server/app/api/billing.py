# -*- coding: utf-8 -*-
"""订阅、订单、权益、用量、支付回调。"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import AuthContext, get_auth, require_admin
from ..errors import ApiError
from ..metrics import increment
from ..models import Order, Plan, Subscription, UsageEvent
from ..schemas import (
    CancelSubscriptionRequest,
    RenewRequest,
    SubscribeRequest,
    UpgradeRequest,
)
from ..services import orders as ordersvc
from ..services import payment_flow
from ..services import subscription as subsvc
from ..services.audit import write_audit
from ..payments import get_provider
from ..services.quota import QuotaService

router = APIRouter(tags=["billing"])


def _plan_view(db: Session, plan: Plan) -> dict:
    entitlements = subsvc.get_entitlements(db, plan.id)
    return {
        "code": plan.code,
        "name": plan.name,
        "price_month_cents": plan.price_month_cents,
        "price_year_cents": plan.price_year_cents,
        "currency": plan.currency,
        "features": plan.features,
        "entitlements": [
            {
                "key": e.key,
                "limit": e.limit_value,
                "unit": e.unit,
                "reset_period": e.reset_period,
            }
            for e in entitlements.values()
        ],
    }


def _subscription_view(db: Session, sub: Subscription, now: datetime | None = None) -> dict:
    now = now or utcnow()
    plan = subsvc.get_plan(db, sub.plan_id)
    days_left = max((sub.current_end_at - now).total_seconds() / 86400, 0)
    return {
        "id": sub.id,
        "status": sub.status,
        "plan": {"code": plan.code, "name": plan.name},
        "seats": sub.seats,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "current_start_at": sub.current_start_at.isoformat(),
        "current_end_at": sub.current_end_at.isoformat(),
        "days_left": round(days_left, 1),
        "provider": sub.provider,
        "version": sub.version,
    }


def _order_view(order: Order) -> dict:
    # 用户侧订单只返回展示字段；渠道流水号属于内部信息，不下发
    return {
        "id": order.id,
        "subscription_id": order.subscription_id,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "status": order.status,
        "provider": order.provider,
        "kind": order.kind,
        "cycle": order.cycle,
        "refunded_cents": order.refunded_cents,
        "meta": order.meta or {},
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    plans = db.scalars(
        select(Plan)
        .where(Plan.active.is_(True))
        .order_by(Plan.price_month_cents.asc(), Plan.id.asc())
    ).all()
    return {"plans": [_plan_view(db, plan) for plan in plans]}


@router.get("/payments/providers")
def list_payment_providers(request: Request):
    """当前可下单的支付渠道；mock/fake 仅在测试环境且显式开启时出现。"""
    from ..payments import available_providers

    return {"items": available_providers(request.app.state.settings)}


@router.post("/subscriptions", status_code=201)
def create_subscription(
    payload: SubscribeRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    idempotency_key = request.headers.get("idempotency-key") or payload.idempotency_key or f"sub:{uuid.uuid4()}"
    plan = subsvc.find_plan_by_code(db, payload.plan_code)
    subscription, order = subsvc.create_subscription_order(
        db,
        account_id=auth.account.id,
        plan=plan,
        cycle=payload.cycle,
        provider=payload.provider,
        idempotency_key=idempotency_key,
    )
    intent = get_provider(payload.provider, settings).create_payment(
        order, {"openid": payload.openid, "scene": payload.scene}
    )
    write_audit(db, actor_id=auth.account.id, action="subscription.create", request=request,
                target_type="subscription", target_id=subscription.id,
                meta={"plan": plan.code, "cycle": payload.cycle, "provider": payload.provider})
    db.commit()
    db.refresh(subscription)
    db.refresh(order)
    return {
        "subscription": _subscription_view(db, subscription),
        "order": _order_view(order),
        "payment": {
            "provider": intent.provider,
            "amount_cents": intent.amount_cents,
            "currency": intent.currency,
            "params": intent.params,
        },
    }


@router.get("/subscriptions/current")
def current_subscription(
    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)
):
    sub = subsvc.get_active_subscription(db, auth.account.id)
    if sub is None:
        raise ApiError(404, "no_subscription", "当前没有生效中的订阅")
    view = _subscription_view(db, sub)
    view["renewal_reminder"] = view["days_left"] <= 7
    return view


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel(
    subscription_id: int,
    payload: CancelSubscriptionRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id, Subscription.account_id == auth.account.id
        )
    )
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    subsvc.cancel_subscription(db, sub, immediate=payload.immediate)
    write_audit(db, actor_id=auth.account.id, action="subscription.cancel", request=request,
                target_type="subscription", target_id=sub.id,
                meta={"immediate": payload.immediate})
    db.commit()
    return {"subscription": _subscription_view(db, sub)}


@router.post("/subscriptions/{subscription_id}/resume")
def resume(
    subscription_id: int,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id, Subscription.account_id == auth.account.id
        )
    )
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    subsvc.resume_subscription(db, sub)
    write_audit(db, actor_id=auth.account.id, action="subscription.resume", request=request,
                target_type="subscription", target_id=sub.id)
    db.commit()
    return {"subscription": _subscription_view(db, sub)}


@router.post("/subscriptions/{subscription_id}/renew")
def renew(
    subscription_id: int,
    payload: RenewRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id, Subscription.account_id == auth.account.id
        )
    )
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    idempotency_key = request.headers.get("idempotency-key") or payload.idempotency_key or f"renew:{uuid.uuid4()}"
    order = subsvc.create_renewal_order(
        db, sub=sub, cycle=payload.cycle, provider=payload.provider,
        idempotency_key=idempotency_key,
    )
    intent = get_provider(payload.provider, settings).create_payment(
        order, {"openid": payload.openid, "scene": payload.scene}
    )
    write_audit(db, actor_id=auth.account.id, action="subscription.renew", request=request,
                target_type="subscription", target_id=sub.id,
                meta={"order_id": order.id, "cycle": payload.cycle})
    db.commit()
    return {
        "order": _order_view(order),
        "payment": {
            "provider": intent.provider,
            "amount_cents": intent.amount_cents,
            "currency": intent.currency,
            "params": intent.params,
        },
    }


@router.post("/subscriptions/{subscription_id}/upgrade")
def upgrade(
    subscription_id: int,
    payload: UpgradeRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """手动升级：按剩余天数比例补差（先下单，支付成功后切换套餐）。"""
    settings = request.app.state.settings
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id, Subscription.account_id == auth.account.id
        )
    )
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    plan = subsvc.find_plan_by_code(db, payload.plan_code)
    idempotency_key = (
        request.headers.get("idempotency-key")
        or payload.idempotency_key
        or f"upgrade:{sub.id}:{payload.plan_code}"
    )
    order = ordersvc.create_upgrade_order(
        db, sub=sub, plan=plan, provider=payload.provider, idempotency_key=idempotency_key
    )
    payment = None
    if order.status != "paid":
        intent = get_provider(payload.provider, settings).create_payment(
            order, {"openid": payload.openid, "scene": payload.scene}
        )
        payment = {
            "provider": intent.provider,
            "amount_cents": intent.amount_cents,
            "currency": intent.currency,
            "params": intent.params,
        }
    write_audit(
        db,
        actor_id=auth.account.id,
        action="subscription.upgrade",
        request=request,
        target_type="order",
        target_id=order.id,
        meta={"from": (order.meta or {}).get("previous_plan_code"), "to": plan.code,
              "amount_cents": order.amount_cents},
    )
    db.commit()
    db.refresh(order)
    db.refresh(sub)
    return {"order": _order_view(order), "payment": payment, "subscription": _subscription_view(db, sub)}


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    order = db.scalar(
        select(Order).where(Order.id == order_id, Order.account_id == auth.account.id)
    )
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    return {"order": _order_view(order)}


@router.get("/orders")
def list_orders(
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Order).where(Order.account_id == auth.account.id).order_by(Order.id.desc()).limit(limit)
    ).all()
    return {"orders": [_order_view(o) for o in rows]}


@router.get("/entitlements")
def entitlements(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return QuotaService(db).summary(auth.account.id)


@router.get("/usage")
def usage(
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    query = select(UsageEvent).where(UsageEvent.account_id == auth.account.id)
    if before_id is not None:
        query = query.where(UsageEvent.id < before_id)
    rows = db.scalars(query.order_by(UsageEvent.id.desc()).limit(limit)).all()
    return {
        "items": [
            {
                "id": row.id,
                "task_id": row.task_id,
                "metric": row.metric,
                "quantity": row.quantity,
                "unit": row.unit,
                "occurred_at": row.occurred_at.isoformat(),
                "meta": row.meta,
            }
            for row in rows
        ],
        "next_before_id": rows[-1].id if rows else None,
    }


@router.get("/usage/summary")
def usage_summary(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    return QuotaService(db).summary(auth.account.id)


@router.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)):
    """统一回调入口。

    必须先读原始字节再交给渠道验签：任何 JSON 重新序列化都会破坏签名。
    失败记录脱敏摘要 + 可重试标记，绝不落密钥/证件/银行卡。
    """
    settings = request.app.state.settings
    raw_body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    allowlist = [ip.strip() for ip in settings.payment_webhook_ip_allowlist.split(",") if ip.strip()]
    client_ip = request.client.host if request.client else ""
    if allowlist and client_ip not in allowlist:
        write_audit(
            db,
            actor_id=None,
            action="payment.webhook_rejected",
            request=request,
            target_type="payment",
            meta={
                "provider": provider,
                "code": "webhook_source_rejected",
                "retryable": False,
                "digest": ordersvc.payload_digest(raw_body),
            },
        )
        db.commit()
        increment("moxie_webhook_failures_total", provider=provider, code="webhook_source_rejected")
        raise ApiError(403, "webhook_source_rejected", "回调来源不在白名单内")
    adapter = get_provider(provider, settings)
    try:
        event = adapter.parse_webhook(headers, raw_body)
    except ApiError as exc:
        write_audit(
            db,
            actor_id=None,
            action="payment.webhook_rejected",
            request=request,
            target_type="payment",
            meta={
                "provider": provider,
                "code": exc.code,
                "retryable": exc.status_code >= 500,
                "digest": ordersvc.payload_digest(raw_body),
            },
        )
        db.commit()
        increment("moxie_webhook_failures_total", provider=provider, code=exc.code)
        raise
    except Exception as exc:  # noqa: BLE001
        write_audit(
            db,
            actor_id=None,
            action="payment.webhook_rejected",
            request=request,
            target_type="payment",
            meta={
                "provider": provider,
                "code": "internal_error",
                "retryable": True,
                "digest": ordersvc.payload_digest(raw_body),
            },
        )
        db.commit()
        increment("moxie_webhook_failures_total", provider=provider, code="internal_error")
        raise ApiError(500, "webhook_failed", "回调处理失败") from exc
    return payment_flow.handle_event(
        db, provider=provider, event=event, raw_body=raw_body, request=request,
        settings=request.app.state.settings,
    )


@router.get("/admin/renewal-reminders")
def renewal_reminders(
    request: Request,
    _admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {"reminders": subsvc.reminders(db, request.app.state.settings)}
