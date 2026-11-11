# -*- coding: utf-8 -*-
"""额度包：目录、购买下单、合并权益视图（/entitlements 在 billing 中）。

购买只创建订单并返回支付参数；权益在支付回调成功后发放（见 subscription._activate_credit_pack）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..schemas import CreditPackPurchaseRequest
from ..payments import get_provider
from ..services import credits as creditsvc
from ..services.audit import write_audit

router = APIRouter(tags=["credits"])


def _order_view(order) -> dict:
    return {
        "id": order.id,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "status": order.status,
        "provider": order.provider,
        "kind": order.kind,
        "pack_id": order.pack_id,
        "meta": order.meta or {},
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.get("/credit-packs")
def list_credit_packs(db: Session = Depends(get_db)):
    return {"packs": [creditsvc.pack_view(p) for p in creditsvc.list_packs(db)]}


@router.post("/credit-packs/{code}/purchase", status_code=201)
def purchase_credit_pack(
    code: str,
    payload: CreditPackPurchaseRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    pack = creditsvc.find_pack(db, code)
    idempotency_key = (
        request.headers.get("idempotency-key")
        or payload.idempotency_key
        or f"pack:{pack.code}:{uuid.uuid4()}"
    )
    order = creditsvc.create_pack_order(
        db,
        account_id=auth.account.id,
        pack=pack,
        provider=payload.provider,
        idempotency_key=idempotency_key,
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
        action="credit_pack.purchase",
        request=request,
        target_type="order",
        target_id=order.id,
        meta={"pack": pack.code, "quantity": pack.quantity, "provider": payload.provider},
    )
    db.commit()
    db.refresh(order)
    return {
        "pack": creditsvc.pack_view(pack),
        "order": _order_view(order),
        "payment": payment,
    }
