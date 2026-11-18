# -*- coding: utf-8 -*-
"""四账对账：以订单为枢纽连接支付、额度、发票与退款账本。

只读聚合，不修改数据；所有规则都可由现有字段推出，历史快照仍走 ReconcileReport。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CreditGrant, CreditPack, InvoiceRequest, Order, Refund, Subscription

ANOMALY_LEVELS = {
    "payment_status_mismatch": "critical",
    "quota_missing": "critical",
    "quota_amount_mismatch": "warn",
    "invoice_missing": "warn",
    "invoice_amount_mismatch": "warn",
    "invoice_voided": "warn",
    "refund_ledger_missing": "critical",
    "refund_mismatch": "warn",
    "refund_amount_mismatch": "warn",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def reconcile(
    session: Session,
    *,
    order_no: str | None = None,
    external_order_no: str | None = None,
    account_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    query = select(Order)
    count_query = select(func.count()).select_from(Order)
    conditions = []
    if order_no:
        if order_no.isdigit():
            conditions.append(Order.id == int(order_no))
        else:
            conditions.append(Order.external_order_no.contains(order_no))
    if external_order_no:
        conditions.append(Order.external_order_no.contains(external_order_no))
    if account_id is not None:
        conditions.append(Order.account_id == account_id)
    if start_at:
        conditions.append(Order.created_at >= start_at)
    if end_at:
        conditions.append(Order.created_at <= end_at)
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = int(session.scalar(count_query) or 0)
    orders = list(
        session.scalars(
            query.order_by(Order.created_at.desc()).limit(limit).offset(offset)
        ).all()
    )
    order_ids = [row.id for row in orders]
    if not order_ids:
        return {
            "total": total,
            "window": {"start_at": _iso(start_at), "end_at": _iso(end_at)},
            "summary": {
                "orders": 0,
                "anomaly_total": 0,
                "by_code": {},
            },
            "groups": [],
            "anomalies": [],
        }

    grants = {
        row.order_id: row
        for row in session.scalars(
            select(CreditGrant).where(CreditGrant.order_id.in_(order_ids))
        ).all()
        if row.order_id is not None
    }
    packs = {
        row.id: row
        for row in session.scalars(
            select(CreditPack).where(CreditPack.id.in_([g.pack_id for g in grants.values() if g.pack_id]))
        ).all()
    }
    invoices = {
        row.order_id: row
        for row in session.scalars(
            select(InvoiceRequest).where(InvoiceRequest.order_id.in_(order_ids))
        ).all()
    }
    refunds: dict[int, list[Refund]] = {}
    for row in session.scalars(
        select(Refund).where(Refund.order_id.in_(order_ids))
    ).all():
        refunds.setdefault(row.order_id, []).append(row)
    subscriptions = {
        row.id: row
        for row in session.scalars(
            select(Subscription).where(
                Subscription.id.in_([o.subscription_id for o in orders if o.subscription_id])
            )
        ).all()
    }

    groups: list[dict] = []
    anomalies: list[dict] = []
    by_code: dict[str, int] = {}

    def add_anomaly(order: Order, code: str, detail: str) -> None:
        by_code[code] = by_code.get(code, 0) + 1
        anomalies.append(
            {
                "order_id": order.id,
                "order_no": str(order.id),
                "account_id": order.account_id,
                "code": code,
                "severity": ANOMALY_LEVELS[code],
                "detail": detail,
            }
        )

    for order in orders:
        order_anomalies: list[str] = []
        paid = order.status == "paid"

        if paid and not order.paid_at:
            order_anomalies.append("payment_status_mismatch")
            add_anomaly(order, "payment_status_mismatch", "订单已支付但缺少 paid_at")
        elif not paid and order.paid_at:
            order_anomalies.append("payment_status_mismatch")
            add_anomaly(order, "payment_status_mismatch", "订单未标记支付但存在 paid_at")

        grant = grants.get(order.id)
        if paid and order.kind == "credit_pack" and order.pack_id and not grant:
            order_anomalies.append("quota_missing")
            add_anomaly(order, "quota_missing", "额度包订单已支付但未生成 CreditGrant")
        elif grant and order.kind == "credit_pack" and order.pack_id:
            pack = packs.get(order.pack_id)
            if pack and grant.quantity_granted != pack.quantity:
                order_anomalies.append("quota_amount_mismatch")
                add_anomaly(
                    order,
                    "quota_amount_mismatch",
                    f"发放 {grant.quantity_granted} 与额度包 {pack.quantity} 不一致",
                )
        elif paid and order.subscription_id and order.subscription_id not in subscriptions:
            order_anomalies.append("quota_missing")
            add_anomaly(order, "quota_missing", "订阅订单已支付但订阅记录不存在")

        invoice = invoices.get(order.id)
        invoice_required = bool((order.meta or {}).get("invoice_requested"))
        if paid and invoice_required and not invoice:
            order_anomalies.append("invoice_missing")
            add_anomaly(order, "invoice_missing", "订单标记需要发票但无发票申请")
        elif invoice and paid and invoice.amount_cents != order.amount_cents:
            order_anomalies.append("invoice_amount_mismatch")
            add_anomaly(
                order,
                "invoice_amount_mismatch",
                f"发票 {invoice.amount_cents} 与订单 {order.amount_cents} 不一致",
            )
        elif invoice and paid and invoice.status in {"voided", "rejected"}:
            order_anomalies.append("invoice_voided")
            add_anomaly(order, "invoice_voided", "订单已支付但发票已作废/驳回")

        order_refunds = refunds.get(order.id, [])
        if order.refunded_cents > 0 and not order_refunds:
            order_anomalies.append("refund_ledger_missing")
            add_anomaly(order, "refund_ledger_missing", "订单已有退款金额但无 Refund 记录")
        elif order_refunds:
            succeeded = sum(r.amount_cents for r in order_refunds if r.status == "succeeded")
            if succeeded != order.refunded_cents:
                order_anomalies.append("refund_amount_mismatch")
                add_anomaly(
                    order,
                    "refund_amount_mismatch",
                    f"退款台账 {succeeded} 与订单 {order.refunded_cents} 不一致",
                )
            if any(r.status == "succeeded" for r in order_refunds) and order.status != "refunded":
                order_anomalies.append("refund_mismatch")
                add_anomaly(order, "refund_mismatch", "退款台账已成功但订单状态未更新")

        groups.append(
            {
                "order_id": order.id,
                "order_no": str(order.id),
                "external_order_no": order.external_order_no,
                "account_id": order.account_id,
                "kind": order.kind,
                "provider": order.provider,
                "amount_cents": order.amount_cents,
                "created_at": _iso(order.created_at),
                "paid_at": _iso(order.paid_at),
                "payment": {
                    "status": order.status,
                    "provider_txn_id": order.provider_txn_id,
                    "amount_cents": order.amount_cents,
                },
                "quota": {
                    "grant_id": grant.id if grant else None,
                    "metric": grant.metric if grant else None,
                    "quantity_granted": grant.quantity_granted if grant else None,
                    "expires_at": _iso(grant.expires_at) if grant else None,
                },
                "invoice": {
                    "id": invoice.id if invoice else None,
                    "status": invoice.status if invoice else None,
                    "amount_cents": invoice.amount_cents if invoice else None,
                    "issued_at": _iso(invoice.issued_at) if invoice else None,
                },
                "refund": {
                    "count": len(order_refunds),
                    "amount_cents": sum(r.amount_cents for r in order_refunds),
                    "succeeded_at": _iso(
                        next((r.succeeded_at for r in order_refunds if r.succeeded_at), None)
                    ),
                },
                "anomalies": order_anomalies,
            }
        )

    return {
        "total": total,
        "window": {"start_at": _iso(start_at), "end_at": _iso(end_at)},
        "summary": {
            "orders": len(groups),
            "anomaly_total": len(anomalies),
            "by_code": by_code,
        },
        "groups": groups,
        "anomalies": anomalies,
    }
