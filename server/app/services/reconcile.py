# -*- coding: utf-8 -*-
"""日对账：渠道账单 vs 本地订单差异分类。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Order, ReconcileReport
from .audit import write_audit


DEFAULT_ITEM_TYPES = ("amount_mismatch", "channel_only", "local_only", "duplicate_payment")


def reconcile(
    session: Session,
    *,
    provider: str,
    biz_date: date,
    settings: Settings,
    records: list[dict[str, Any]] | None = None,
    source: str = "api",
    actor_id: int | None = None,
    request=None,
    http_client=None,
) -> ReconcileReport:
    if records is None:
        from ..payments import get_provider

        client = get_provider(provider, settings, http_client=http_client)
        records = client.download_bill(biz_date.isoformat())
        source = "download"

    start = datetime(biz_date.year, biz_date.month, biz_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    local_orders = session.scalars(
        select(Order).where(
            Order.provider == provider,
            Order.status.in_({"paid", "refunded"}),
            Order.paid_at >= start,
            Order.paid_at < end,
        )
    ).all()
    local_by_no: dict[str, Order] = {}
    for order in local_orders:
        if order.external_order_no:
            local_by_no[order.external_order_no] = order

    channel_by_no: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        no = str(record.get("external_order_no") or "")
        if no:
            channel_by_no.setdefault(no, []).append(record)

    items: list[dict[str, Any]] = []

    def add(kind: str, **payload: Any) -> None:
        items.append({"type": kind, **payload})

    for no, rows in channel_by_no.items():
        if len(rows) > 1:
            add(
                "duplicate_payment",
                external_order_no=no,
                count=len(rows),
                provider_txn_ids=[row.get("provider_txn_id") for row in rows],
                amount_cents=[row.get("amount_cents") for row in rows],
            )
            local_by_no.pop(no, None)
            continue
        record = rows[0]
        order = local_by_no.get(no)
        if order is None:
            add(
                "channel_only",
                external_order_no=no,
                amount_cents=record.get("amount_cents"),
                provider_txn_id=record.get("provider_txn_id"),
            )
            continue
        if int(record.get("amount_cents") or 0) != order.amount_cents:
            add(
                "amount_mismatch",
                external_order_no=no,
                order_id=order.id,
                local_amount_cents=order.amount_cents,
                channel_amount_cents=record.get("amount_cents"),
            )
        local_by_no.pop(no, None)

    for no, order in local_by_no.items():
        add("local_only", external_order_no=no, order_id=order.id, amount_cents=order.amount_cents)

    summary = {
        "orders": len(local_orders),
        "channel_records": len(records),
        "diff_count": len(items),
        "amount_mismatch": sum(1 for i in items if i["type"] == "amount_mismatch"),
        "channel_only": sum(1 for i in items if i["type"] == "channel_only"),
        "local_only": sum(1 for i in items if i["type"] == "local_only"),
        "duplicate_payment": sum(1 for i in items if i["type"] == "duplicate_payment"),
    }
    report = session.scalar(
        select(ReconcileReport).where(
            ReconcileReport.provider == provider, ReconcileReport.biz_date == biz_date
        )
    )
    if report is None:
        report = ReconcileReport(provider=provider, biz_date=biz_date)
        session.add(report)
    report.status = "done"
    report.summary = summary
    report.items = items
    report.channel_source = source
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="payment.reconcile",
        request=request,
        target_type="reconcile",
        target_id=report.id,
        meta={"provider": provider, "biz_date": biz_date.isoformat(), **summary},
    )
    return report
