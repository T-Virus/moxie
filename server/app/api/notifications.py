# -*- coding: utf-8 -*-
"""站内信与通知投递查询（用户侧）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import Notification
from ..schemas import (
    NotificationListResponse,
    NotificationReadResponse,
    WebPushSubscriptionInput,
    WebPushSubscriptionResponse,
)
from ..services import notifications as nsvc

router = APIRouter(tags=["notifications"])


def _view(row: Notification) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "body": row.body,
        "level": row.level,
        "status": row.status,
        "meta": row.meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = False,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    rows = nsvc.list_for_account(db, auth.account.id, limit=limit, unread_only=unread_only)
    unread = sum(
        1
        for row in nsvc.list_for_account(db, auth.account.id, limit=500)
        if row.status == "unread"
    )
    return {"items": [_view(row) for row in rows], "unread_count": unread}


@router.post("/notifications/{notification_id}/read", response_model=NotificationReadResponse)
def read_notification(
    notification_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    row = db.get(Notification, notification_id)
    if row is None or row.account_id != auth.account.id:
        raise ApiError(404, "notification_not_found", "通知不存在")
    nsvc.mark_read(db, row)
    db.commit()
    return {"notification": _view(row)}


@router.post("/notifications/read-all")
def read_all(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    count = nsvc.mark_all_read(db, auth.account.id)
    db.commit()
    return {"ok": True, "marked": count}


def _subscription_view(row) -> dict:
    return {
        "id": row.id,
        "endpoint": row.endpoint,
        "device_label": row.device_label,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/notifications/push-subscriptions", response_model=WebPushSubscriptionResponse)
def list_push_subscriptions(
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    rows = nsvc.list_subscriptions(db, auth.account.id)
    return {"items": [_subscription_view(row) for row in rows]}


@router.post("/notifications/push-subscriptions", response_model=WebPushSubscriptionResponse)
def upsert_push_subscription(
    payload: WebPushSubscriptionInput,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """浏览器订阅建立/刷新后上报：endpoint 唯一，重复上报覆盖密钥并复活为 active。"""
    nsvc.upsert_subscription(
        db,
        account_id=auth.account.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        device_label=payload.device_label,
    )
    db.commit()
    rows = nsvc.list_subscriptions(db, auth.account.id)
    return {"items": [_subscription_view(row) for row in rows]}


@router.delete("/notifications/push-subscriptions", response_model=WebPushSubscriptionResponse)
def delete_push_subscription(
    endpoint: str = Query(min_length=1, max_length=500),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    nsvc.delete_subscription(db, account_id=auth.account.id, endpoint=endpoint)
    db.commit()
    rows = nsvc.list_subscriptions(db, auth.account.id)
    return {"items": [_subscription_view(row) for row in rows]}
