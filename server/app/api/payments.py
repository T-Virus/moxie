# -*- coding: utf-8 -*-
"""支付配套：升级门户、退款、对账、发票、渠道回跳页。"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth, require_admin, require_staff
from ..errors import ApiError
from ..models import InvoiceRequest, Order, Refund, ReconcileReport, Subscription
from ..schemas import (
    AdminRefundDecisionRequest,
    AdminRefundRequest,
    InvoiceApplyRequest,
    InvoiceCreateRequest,
    InvoiceUpdateRequest,
    InvoiceVoidRequest,
    ReconcileRequest,
)
from ..payments import get_provider
from ..services import invoicing as invoicesvc
from ..services import orders as ordersvc
from ..services import reconcile as reconcilesvc
from ..services.audit import write_audit

router = APIRouter(tags=["payments"])


def _refund_view(refund: Refund) -> dict:
    return {
        "id": refund.id,
        "order_id": refund.order_id,
        "amount_cents": refund.amount_cents,
        "currency": refund.currency,
        "status": refund.status,
        "provider": refund.provider,
        "provider_refund_id": refund.provider_refund_id,
        "reason": refund.reason,
        "requested_at": refund.requested_at.isoformat(),
        "succeeded_at": refund.succeeded_at.isoformat() if refund.succeeded_at else None,
    }


def _invoice_view(row: InvoiceRequest) -> dict:
    # 兼容旧前端：历史/旧叫法 rejected 统一展示为 voided，同时保留 legacy_status
    normalized = "voided" if row.status in {"voided", "rejected"} else row.status
    meta = row.meta or {}
    return {
        "id": row.id,
        "order_id": row.order_id,
        "title": row.title,
        "tax_no": row.tax_no,
        "email": row.email,
        "amount_cents": row.amount_cents,
        "status": normalized,
        "legacy_status": "rejected" if normalized == "voided" else None,
        "note": row.note,
        "provider": meta.get("provider"),
        "provider_invoice_id": meta.get("provider_invoice_id"),
        "invoice_url": meta.get("invoice_url"),
        "failure_reason": meta.get("failure_reason"),
        "created_at": row.created_at.isoformat(),
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
    }


@router.post("/subscriptions/{subscription_id}/portal")
def portal(
    subscription_id: int,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """Stripe Customer Portal 入口；其它渠道返回 501。"""
    settings = request.app.state.settings
    sub = db.scalar(
        select(Subscription).where(
            Subscription.id == subscription_id, Subscription.account_id == auth.account.id
        )
    )
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    data = get_provider(sub.provider, settings).portal(sub)
    if not data:
        raise ApiError(501, "portal_not_supported", "当前渠道不支持自助门户")
    write_audit(db, actor_id=auth.account.id, action="subscription.portal", request=request,
                target_type="subscription", target_id=sub.id)
    db.commit()
    return data


# ---- 用户：退款记录 / 发票 -------------------------------------------------
@router.get("/refunds")
def list_refunds(
    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(Refund).where(Refund.account_id == auth.account.id).order_by(Refund.id.desc()).limit(100)
    ).all()
    items = [_refund_view(r) for r in rows]
    return {"items": items, "refunds": items}


@router.get("/invoices")
def list_invoices(
    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)
):
    rows = db.scalars(
        select(InvoiceRequest)
        .where(InvoiceRequest.account_id == auth.account.id)
        .order_by(InvoiceRequest.id.desc())
    ).all()
    return {"invoices": [_invoice_view(r) for r in rows]}


def _own_invoice(db: Session, invoice_id: int, account_id: int) -> InvoiceRequest:
    row = db.scalar(
        select(InvoiceRequest).where(
            InvoiceRequest.id == invoice_id, InvoiceRequest.account_id == account_id
        )
    )
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")
    return row


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    return {"invoice": _invoice_view(_own_invoice(db, invoice_id, auth.account.id))}


@router.post("/invoices/{invoice_id}/apply")
def apply_own_invoice(
    invoice_id: int,
    request: Request,
    payload: InvoiceApplyRequest | None = None,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    row = _own_invoice(db, invoice_id, auth.account.id)
    _, extra = invoicesvc.apply_invoice(
        db, row, request.app.state.settings, actor_id=auth.account.id, request=request,
        provider_name=payload.provider if payload else None,
    )
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row), "provider": extra["provider"]}


@router.post("/invoices/{invoice_id}/void")
def void_own_invoice(
    invoice_id: int,
    request: Request,
    payload: InvoiceVoidRequest | None = None,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    row = _own_invoice(db, invoice_id, auth.account.id)
    reason = (payload.reason if payload else None) or "用户申请作废"
    invoicesvc.void_invoice(
        db, row, request.app.state.settings, actor_id=auth.account.id,
        reason=reason, request=request,
    )
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row)}


@router.post("/orders/{order_id}/invoice", status_code=201)
def create_invoice(
    order_id: int,
    payload: InvoiceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """订单开发票记录（人工开票，不做自动化）。"""
    order = db.scalar(
        select(Order).where(Order.id == order_id, Order.account_id == auth.account.id)
    )
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    if order.status != "paid" or order.refunded_cents >= order.amount_cents:
        raise ApiError(409, "order_not_invoiceable", "只有已支付且未全额退款的订单可开票")
    existing = db.scalar(select(InvoiceRequest).where(InvoiceRequest.order_id == order.id))
    if existing is not None:
        return {"invoice": _invoice_view(existing)}
    row = InvoiceRequest(
        order_id=order.id,
        account_id=auth.account.id,
        title=payload.title,
        tax_no=payload.tax_no,
        email=payload.email,
        amount_cents=order.amount_cents - order.refunded_cents,
        note=payload.note,
        meta={
            "provider": request.app.state.settings.invoice_provider,
            "payment_provider": order.provider,
            "order_no": order.external_order_no,
        },
    )
    db.add(row)
    write_audit(db, actor_id=auth.account.id, action="invoice.request", request=request,
                target_type="invoice", target_id=order.id, meta={"order_id": order.id})
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row)}


# ---- 管理端：退款 / 对账 / 发票 --------------------------------------------
@router.post("/admin/orders/{order_id}/invoice", status_code=201)
def admin_create_invoice(
    order_id: int,
    payload: InvoiceCreateRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理端代客创建开票申请（requested），随后可调 /issue 提交渠道。"""
    order = db.get(Order, order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    if order.status != "paid" or order.refunded_cents >= order.amount_cents:
        raise ApiError(409, "order_not_invoiceable", "只有已支付且未全额退款的订单可开票")
    existing = db.scalar(select(InvoiceRequest).where(InvoiceRequest.order_id == order.id))
    if existing is not None:
        return {"invoice": _invoice_view(existing), "duplicate": True}
    row = InvoiceRequest(
        order_id=order.id,
        account_id=order.account_id,
        title=payload.title,
        tax_no=payload.tax_no,
        email=payload.email,
        amount_cents=order.amount_cents - order.refunded_cents,
        note=payload.note,
        meta={
            "provider": request.app.state.settings.invoice_provider,
            "payment_provider": order.provider,
            "order_no": order.external_order_no,
            "created_by_admin": admin.id,
        },
    )
    db.add(row)
    write_audit(db, actor_id=admin.id, action="invoice.request", request=request,
                target_type="invoice", target_id=order.id,
                meta={"order_id": order.id, "by": "admin"})
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row), "duplicate": False}


@router.post("/admin/orders/{order_id}/refund")
def admin_refund(
    order_id: int,
    payload: AdminRefundRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    order = db.get(Order, order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    if payload.prorate:
        from ..services import refunds as refundsvc

        quote = refundsvc.quote(db, order)
        amount = int(quote["refundable_cents"])
        if amount <= 0:
            raise ApiError(409, "nothing_refundable", "按已用量折算后无可退金额")
    else:
        amount = payload.amount_cents or (order.amount_cents - order.refunded_cents)
    key = (
        request.headers.get("idempotency-key")
        or payload.idempotency_key
        or f"refund:{order.id}:{amount}"
    )
    refund, duplicate = ordersvc.create_refund(
        db,
        order=order,
        amount_cents=amount,
        reason=payload.reason,
        idempotency_key=key,
        settings=settings,
        actor_id=admin.id,
        request=request,
    )
    db.commit()
    db.refresh(refund)
    db.refresh(order)
    return {
        "refund": _refund_view(refund),
        "duplicate": duplicate,
        "order": {"id": order.id, "status": order.status, "refunded_cents": order.refunded_cents},
    }


@router.get("/admin/orders/{order_id}/refund-quote")
def admin_refund_quote(
    order_id: int,
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    from ..services import refunds as refundsvc

    order = db.get(Order, order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    return {"quote": refundsvc.quote(db, order)}


@router.post("/admin/refunds/{refund_id}/approve")
def approve_refund(
    refund_id: int,
    request: Request,
    payload: AdminRefundDecisionRequest | None = None,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审批通过：对 pending/failed 退款重试渠道退款；已成功幂等返回。"""
    note = (payload.note or payload.reason) if payload else None
    refund = db.get(Refund, refund_id)
    if refund is None:
        raise ApiError(404, "refund_not_found", "退款记录不存在")
    if refund.status == "succeeded":
        return {"refund": _refund_view(refund), "duplicate": True}
    order = db.get(Order, refund.order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    settings = request.app.state.settings
    provider = get_provider(order.provider, settings)
    result = provider.create_refund(refund, order)
    refund.provider_refund_id = result.provider_refund_id
    refund.meta = {"provider_status": result.status}
    if result.status == "succeeded":
        ordersvc.apply_refund_result(db, refund, order, "succeeded")
    elif result.status == "failed":
        refund.status = "failed"
    write_audit(db, actor_id=admin.id, action="order.refund.approve", request=request,
                target_type="refund", target_id=str(refund.id),
                meta={"order_id": order.id, "status": refund.status, "note": note})
    db.commit()
    db.refresh(refund)
    return {"refund": _refund_view(refund), "duplicate": False}


@router.post("/admin/refunds/{refund_id}/reject")
def reject_refund(
    refund_id: int,
    payload: AdminRefundDecisionRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    refund = db.get(Refund, refund_id)
    if refund is None:
        raise ApiError(404, "refund_not_found", "退款记录不存在")
    if refund.status == "succeeded":
        raise ApiError(409, "refund_already_succeeded", "已成功的退款不能驳回")
    note = payload.note or payload.reason
    if not note or len(note.strip()) < 2:
        raise ApiError(422, "refund_note_required", "驳回退款必须填写备注（至少 2 个字符）")
    refund.status = "failed"
    refund.meta = {**(refund.meta or {}), "rejected_reason": note, "rejected_by": admin.id}
    write_audit(db, actor_id=admin.id, action="order.refund.reject", request=request,
                target_type="refund", target_id=str(refund.id),
                meta={"order_id": refund.order_id, "reason": note})
    db.commit()
    return {"refund": _refund_view(refund)}


@router.get("/admin/refunds")
def admin_refunds(
    order_id: int | None = Query(default=None, ge=1),
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Refund).order_by(Refund.id.desc()).limit(200)
    if order_id is not None:
        query = query.where(Refund.order_id == order_id)
    rows = db.scalars(query).all()
    items = [_refund_view(r) for r in rows]
    # items 为新契约，refunds 为旧前端别名（保留一段时间）
    return {"items": items, "refunds": items}


@router.post("/admin/payments/reconcile")
def run_reconcile(
    payload: ReconcileRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    try:
        biz_date = datetime.strptime(payload.biz_date, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(422, "invalid_date", "biz_date 必须是 YYYY-MM-DD")
    report = reconcilesvc.reconcile(
        db,
        provider=payload.provider,
        biz_date=biz_date,
        settings=settings,
        records=payload.records,
        source="upload" if payload.records is not None else "download",
        actor_id=admin.id,
        request=request,
    )
    db.commit()
    db.refresh(report)
    return {
        "id": report.id,
        "provider": report.provider,
        "biz_date": report.biz_date.isoformat(),
        "status": report.status,
        "summary": report.summary,
        "items": report.items,
        "channel_source": report.channel_source,
    }


@router.get("/admin/payments/reconcile")
def get_reconcile(
    provider: str = Query(default="wechat"),
    biz_date: str = Query(...),
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    try:
        day = datetime.strptime(biz_date, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(422, "invalid_date", "biz_date 必须是 YYYY-MM-DD")
    row = db.scalar(
        select(ReconcileReport).where(
            ReconcileReport.provider == provider, ReconcileReport.biz_date == day
        )
    )
    if row is None:
        raise ApiError(404, "reconcile_not_found", "该日对账报告不存在")
    return {
        "id": row.id,
        "provider": row.provider,
        "biz_date": row.biz_date.isoformat(),
        "summary": row.summary,
        "items": row.items,
        "channel_source": row.channel_source,
    }


@router.get("/admin/payments/reconcile/export")
def export_reconcile(
    provider: str = Query(default="wechat"),
    biz_date: str = Query(...),
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    try:
        day = datetime.strptime(biz_date, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(422, "invalid_date", "biz_date 必须是 YYYY-MM-DD")
    row = db.scalar(
        select(ReconcileReport).where(
            ReconcileReport.provider == provider, ReconcileReport.biz_date == day
        )
    )
    if row is None:
        raise ApiError(404, "reconcile_not_found", "该日对账报告不存在")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["type", "external_order_no", "order_id", "amount_cents", "channel_amount_cents", "count"])
    for item in row.items:
        writer.writerow([
            item.get("type", ""),
            item.get("external_order_no", ""),
            item.get("order_id", ""),
            item.get("amount_cents", item.get("local_amount_cents", "")),
            item.get("channel_amount_cents", ""),
            item.get("count", ""),
        ])
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="reconcile-{provider}-{biz_date}.csv"'
        },
    )


@router.get("/admin/invoices")
def admin_invoices(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(InvoiceRequest)
    if status:
        # 旧前端传 rejected：映射到 voided，并同时匹配历史数据里的 rejected
        normalized = "voided" if status in {"voided", "rejected"} else status
        if normalized == "voided":
            query = query.where(InvoiceRequest.status.in_(("voided", "rejected")))
        else:
            query = query.where(InvoiceRequest.status == normalized)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(
        query.order_by(InvoiceRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_invoice_view(r) for r in rows]
    return {"items": items, "invoices": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/invoices/{invoice_id}")
def admin_invoice_detail(
    invoice_id: int,
    _staff=Depends(require_staff),
    db: Session = Depends(get_db),
):
    row = db.get(InvoiceRequest, invoice_id)
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")
    return {"invoice": _invoice_view(row)}


@router.post("/admin/invoices/{invoice_id}/issue")
def admin_issue_invoice(
    invoice_id: int,
    request: Request,
    payload: InvoiceApplyRequest | None = None,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理端提交渠道开票：requested/failed → issuing → issued/failed。"""
    row = db.get(InvoiceRequest, invoice_id)
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")
    _, extra = invoicesvc.apply_invoice(
        db, row, request.app.state.settings, actor_id=admin.id, request=request,
        provider_name=payload.provider if payload else None,
    )
    db.commit()
    db.refresh(row)
    return {
        "invoice": _invoice_view(row),
        "provider": extra["provider"],
        "provider_invoice_id": (row.meta or {}).get("provider_invoice_id"),
    }


@router.post("/admin/invoices/{invoice_id}/void")
def admin_void_invoice(
    invoice_id: int,
    payload: InvoiceVoidRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(InvoiceRequest, invoice_id)
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")
    reason = (payload.reason or "").strip()
    if len(reason) < 2:
        raise ApiError(422, "invoice_void_reason_required", "作废发票必须填写原因（至少 2 个字符）")
    invoicesvc.void_invoice(
        db, row, request.app.state.settings, actor_id=admin.id, reason=reason, request=request,
    )
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row)}


@router.post("/admin/invoices/{invoice_id}")
def update_invoice(
    invoice_id: int,
    payload: InvoiceUpdateRequest,
    request: Request,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(InvoiceRequest, invoice_id)
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")
    status = "voided" if payload.status == "rejected" else payload.status
    row.status = status
    row.note = payload.note or row.note
    row.admin_id = admin.id
    if status == "issued":
        row.issued_at = row.issued_at or row.created_at
    write_audit(db, actor_id=admin.id, action="invoice.update", request=request,
                target_type="invoice", target_id=row.id, meta={"status": status})
    db.commit()
    db.refresh(row)
    return {"invoice": _invoice_view(row)}


# ---- 开票渠道异步回调 -------------------------------------------------------
@router.post("/payments/invoices/callback")
async def invoice_callback(request: Request, db: Session = Depends(get_db)):
    """渠道回调：先验签，再按 event_id 幂等，最后走状态机。"""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body or b"{}")
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_callback_body", "回调体不是合法 JSON")
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_callback_body", "回调体必须是 JSON 对象")
    headers = {key.lower(): value for key, value in request.headers.items()}
    row, duplicate = invoicesvc.handle_callback(
        db, payload, raw_body, headers, request.app.state.settings, request=request
    )
    db.commit()
    db.refresh(row)
    return {"ok": True, "duplicate": duplicate, "invoice": _invoice_view(row)}


# ---- 渠道回跳页（Stripe Checkout） ----------------------------------------
@router.get("/payments/stripe/success")
def stripe_success(session_id: str | None = Query(default=None)):
    return {"ok": True, "session_id": session_id}


@router.get("/payments/stripe/cancel")
def stripe_cancel():
    return {"ok": False, "reason": "canceled"}


@router.get("/payments/stripe/portal-return")
def stripe_portal_return():
    return {"ok": True}
