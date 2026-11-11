# -*- coding: utf-8 -*-
"""支付回调统一处理：幂等入库 → 订单/退款状态机 → 审计。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import Order, Refund, WebhookEvent
from ..payments.base import PaymentEvent
from . import orders as ordersvc
from . import subscription as subsvc


def _notify_payment(session: Session, settings, order: Order, category: str, extra: dict) -> None:
    """支付成功/失败通知；通知故障不影响回调主流程。"""
    try:
        from . import notifications

        notifications.emit(
            session,
            account_id=order.account_id,
            category=category,
            dedupe_key=f"payment:{order.id}:{category}",
            context={
                "order_no": order.external_order_no or str(order.id),
                "amount": f"{order.amount_cents / 100:.2f}",
                "reason": extra.get("reason", ""),
            },
            settings=settings,
        )
    except Exception:  # noqa: BLE001
        pass


def _find_order(session: Session, provider: str, event: PaymentEvent) -> Order:
    order: Order | None = None
    if event.order_id is not None:
        order = session.get(Order, event.order_id)
    if order is None and event.external_order_no:
        order = session.scalar(
            select(Order).where(
                Order.provider == provider,
                Order.external_order_no == event.external_order_no,
            )
        )
    if order is None:
        raise ApiError(404, "order_not_found", "回调对应的订单不存在")
    if order.provider != provider:
        raise ApiError(400, "provider_mismatch", "回调渠道与订单渠道不一致")
    return order


def _find_refund(session: Session, provider: str, event: PaymentEvent, order: Order | None) -> Refund:
    refund: Refund | None = None
    if event.refund_ref:
        refund = session.scalar(
            select(Refund).where(
                Refund.provider == provider, Refund.provider_refund_id == event.refund_ref
            )
        )
    if refund is None and order is not None:
        refund = session.scalar(
            select(Refund)
            .where(Refund.order_id == order.id, Refund.status.in_({"pending", "succeeded"}))
            .order_by(Refund.id.desc())
        )
    if refund is None:
        raise ApiError(404, "refund_not_found", "回调对应的退款单不存在")
    return refund


def handle_event(
    session: Session,
    *,
    provider: str,
    event: PaymentEvent,
    raw_body: bytes = b"",
    request=None,
    settings=None,
) -> dict:
    digest = ordersvc.payload_digest(raw_body) if raw_body else None
    row = session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.provider == provider, WebhookEvent.event_id == event.event_id
        )
    )
    if row is not None:
        if not (row.process_status == "failed" and row.retryable):
            from ..metrics import increment

            increment("moxie_webhook_duplicates_total", provider=provider)
            return {"ok": True, "duplicate": True, "order_status": None}
        row.process_status = "received"
        row.error_code = None
    else:
        row = WebhookEvent(
            provider=provider,
            event_id=event.event_id,
            payload=ordersvc.redact_payload(event.raw or {}),
            event_type=event.event_type,
            signature_valid=True,
            process_status="received",
            raw_digest=digest,
        )
        session.add(row)
        session.flush()

    try:
        result_status = "ignored"
        if event.event_type == "payment":
            order = _find_order(session, provider, event)
            ordersvc._validate_order_amount(order, event.amount_cents, event.currency)
            if event.status == "paid":
                if order.status not in ("paid", "refunded", "closed"):
                    subsvc.activate_paid_order(
                        session, order, provider_txn_id=event.provider_txn_id or event.event_id
                    )
                result_status = "paid"
                _notify_payment(session, settings, order, "payment_succeeded", {})
            elif event.status == "failed":
                if order.status in ("created", "pending"):
                    ordersvc.transition_order(order, "failed")
                    order.failure_reason = (event.raw.get("type") if event.raw else None) or "payment_failed"
                result_status = "failed"
                _notify_payment(
                    session, settings, order, "payment_failed",
                    {"reason": order.failure_reason or "payment_failed"},
                )
            else:
                result_status = "pending"
        elif event.event_type == "refund":
            order = None
            try:
                order = _find_order(session, provider, event)
            except ApiError:
                order = None
            refund = _find_refund(session, provider, event, order)
            if event.amount_cents is not None and int(event.amount_cents) != refund.amount_cents:
                raise ApiError(400, "amount_mismatch", "退款回调金额与退款单不一致")
            ordersvc.apply_refund_result(session, refund, session.get(Order, refund.order_id), event.status)
            result_status = refund.status
        else:
            raise ApiError(400, "unsupported_event", "未知回调类型")

        row.process_status = "done"
        row.processed_at = utcnow()
        session.commit()
        return {"ok": True, "duplicate": False, "order_status": result_status}
    except ApiError as exc:
        row.process_status = "failed"
        row.error_code = exc.code
        row.retryable = exc.status_code >= 500 or exc.code in {"order_not_found", "refund_not_found"}
        session.commit()
        raise
    except Exception:
        row.process_status = "failed"
        row.error_code = "internal_error"
        row.retryable = True
        session.commit()
        raise
