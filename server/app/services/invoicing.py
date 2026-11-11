# -*- coding: utf-8 -*-
"""开票业务：渠道调用、状态机、回调幂等与审计。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import utcnow
from ..errors import ApiError
from ..models import InvoiceRequest
from ..payments.invoice import NuonuoInvoiceProvider, StubInvoiceProvider
from .audit import write_audit

INVOICE_PROVIDERS = {
    "stub": StubInvoiceProvider,
    "nuonuo": NuonuoInvoiceProvider,
}

# 状态机：requested → issuing → issued → voided / failed
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "requested": {"issuing", "issued", "voided", "failed"},  # issued 为管理端人工开票兼容
    "issuing": {"issued", "failed", "voided"},
    "issued": {"voided"},
    "failed": {"issuing", "voided"},
    "voided": set(),
}


def get_invoice_provider(settings, name: str | None = None, http_client=None) -> InvoiceProvider:
    provider_name = (name or settings.invoice_provider or "stub").strip().lower()
    cls = INVOICE_PROVIDERS.get(provider_name)
    if cls is None:
        raise ApiError(404, "unknown_invoice_provider", f"未知开票渠道：{provider_name}")
    return cls(settings, http_client=http_client)


def transition(row: InvoiceRequest, target: str) -> None:
    if target not in {"requested", "issuing", "issued", "voided", "failed"}:
        raise ApiError(422, "invalid_invoice_status", f"非法发票状态：{target}")
    if target == row.status:
        return
    if target not in ALLOWED_TRANSITIONS.get(row.status, set()):
        raise ApiError(
            409,
            "illegal_invoice_transition",
            f"发票状态不允许从 {row.status} 变更为 {target}",
        )
    row.status = target
    if target == "issued" and row.issued_at is None:
        row.issued_at = utcnow()


def _merge_meta(row: InvoiceRequest, **values: Any) -> dict:
    meta = dict(row.meta or {})
    meta.update(values)
    row.meta = meta
    return meta


def apply_invoice(
    db: Session,
    row: InvoiceRequest,
    settings,
    *,
    actor_id: int | None,
    request=None,
    provider_name: str | None = None,
) -> tuple[InvoiceRequest, dict]:
    """申请开票：requested/failed → issuing →（渠道返回）issued/failed。"""
    provider = get_invoice_provider(
        settings,
        name=provider_name or (row.meta or {}).get("provider"),
        http_client=getattr(request.app.state, "http_client", None) if request else None,
    )
    provider.require_configured()
    if row.status not in ("requested", "failed"):
        raise ApiError(
            409,
            "illegal_invoice_transition",
            f"只有 requested/failed 状态可申请开票，当前为 {row.status}",
        )
    transition(row, "issuing")
    _merge_meta(
        row,
        provider=provider.name,
        apply_attempts=int((row.meta or {}).get("apply_attempts") or 0) + 1,
        applied_at=utcnow().isoformat(),
    )
    db.flush()
    result = provider.apply(row)
    transition(row, result.status)
    if result.status == "failed":
        _merge_meta(row, failure_reason=result.message or "渠道开票失败")
    if result.provider_invoice_id:
        _merge_meta(row, provider_invoice_id=result.provider_invoice_id)
    if result.invoice_url:
        _merge_meta(row, invoice_url=result.invoice_url)
    audit = write_audit(
        db,
        actor_id=actor_id,
        action="invoice.apply",
        request=request,
        target_type="invoice",
        target_id=str(row.id),
        meta={
            "provider": provider.name,
            "status": row.status,
            "provider_invoice_id": result.provider_invoice_id or None,
        },
    )
    return row, {"audit": audit, "provider": provider.name, "result": result}


def void_invoice(
    db: Session,
    row: InvoiceRequest,
    settings,
    *,
    actor_id: int | None,
    reason: str,
    request=None,
) -> tuple[InvoiceRequest, dict]:
    """作废：requested/issuing/issued/failed → voided；issued 会先调用渠道作废。"""
    if row.status == "voided":
        raise ApiError(409, "illegal_invoice_transition", "发票已作废，不能重复作废")
    if row.status not in ("requested", "issuing", "issued", "failed"):
        raise ApiError(
            409,
            "illegal_invoice_transition",
            f"发票状态不允许作废：{row.status}",
        )
    _merge_meta(row, void_reason=reason)
    if row.status in ("issued", "issuing"):
        provider = get_invoice_provider(
            settings,
            name=(row.meta or {}).get("provider"),
            http_client=getattr(request.app.state, "http_client", None) if request else None,
        )
        provider.require_configured()
        result = provider.void(row)
        if result.status == "failed":
            _merge_meta(row, failure_reason=result.message or "渠道作废失败")
            raise ApiError(502, "invoice_void_failed", "渠道作废失败，请稍后重试")
    transition(row, "voided")
    audit = write_audit(
        db,
        actor_id=actor_id,
        action="invoice.void",
        request=request,
        target_type="invoice",
        target_id=str(row.id),
        meta={"reason": reason, "status": "voided"},
    )
    return row, {"audit": audit}


def handle_callback(
    db: Session,
    payload: dict[str, Any],
    raw_body: bytes,
    headers: dict[str, str],
    settings,
    *,
    request=None,
) -> tuple[InvoiceRequest, bool]:
    """处理渠道异步通知。返回 (invoice, duplicate)；验签失败抛 403。"""
    provider = get_invoice_provider(
        settings,
        name=payload.get("provider"),
        http_client=getattr(request.app.state, "http_client", None) if request else None,
    )
    provider.verify_callback(headers, raw_body)

    invoice_id = payload.get("invoice_id")
    try:
        invoice_id_int = int(invoice_id)
    except (TypeError, ValueError):
        raise ApiError(422, "invalid_callback_body", "回调缺少有效的 invoice_id")
    row = db.get(InvoiceRequest, invoice_id_int)
    if row is None:
        raise ApiError(404, "invoice_not_found", "发票申请不存在")

    event_id = str(payload.get("event_id") or payload.get("id") or "").strip()
    if not event_id:
        raise ApiError(422, "invalid_callback_body", "回调缺少 event_id（幂等键）")

    meta = dict(row.meta or {})
    seen = list(meta.get("callback_ids") or [])
    if event_id in seen:
        return row, True

    status = str(payload.get("status") or "").strip()
    if status not in {"issuing", "issued", "voided", "failed"}:
        raise ApiError(422, "invalid_callback_body", f"回调状态非法：{status}")
    transition(row, status)
    if status == "failed":
        _merge_meta(row, failure_reason=payload.get("message") or "渠道回调失败")
    provider_invoice_id = payload.get("provider_invoice_id") or payload.get("invoice_no")
    if provider_invoice_id:
        _merge_meta(row, provider_invoice_id=str(provider_invoice_id))
    _merge_meta(
        row,
        provider=provider.name,
        callback_ids=(seen + [event_id])[-20:],
        last_callback_at=utcnow().isoformat(),
    )
    write_audit(
        db,
        actor_id=None,
        action="invoice.callback",
        request=request,
        target_type="invoice",
        target_id=str(row.id),
        meta={"event_id": event_id, "status": status, "provider": provider.name},
    )
    return row, False
