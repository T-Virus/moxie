# -*- coding: utf-8 -*-
"""健康检查、就绪检查、审计查询与运营管理接口（对齐 admin/README.md 契约）。

权限：
  · 只读接口 require_staff（admin / support）；
  · 写接口 require_admin，且全部写 audit_logs。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete as sa_delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from ..db import Base, get_db, utcnow
from ..deps import require_admin, require_staff
from ..errors import ApiError
from ..models import (
    Account,
    AuditLog,
    Device,
    ModelProviderConfig,
    Notification,
    NotificationDelivery,
    OfflinePackage,
    Order,
    Plan,
    ReconcileReport,
    RefreshSession,
    Refund,
    Subscription,
    Task,
    TaskStep,
    UsageAggregate,
    UsageEvent,
)
from ..schemas import (
    AdminDeleteByEmailRequest,
    AdminModelConfigUpsert,
    AdminModelConfigView,
    AdminNotificationRequest,
    AdminQuotaAdjustRequest,
    AdminReasonRequest,
    AdminSubscriptionPatchRequest,
    AdminUserStatusRequest,
)
from ..services import model_config as model_config_svc
from ..services import notifications as nsvc
from ..services import subscription as subsvc
from ..services.audit import write_audit
from ..services.model_config import describe_configs, encrypt_key, resolve_step_model
from ..services.model_gateway import complete_sync
from ..services.uploads import safe_filename as safe_upload_name
from ..services.quota import QuotaService, period_of

health_router = APIRouter(tags=["ops"])

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@health_router.get("/healthz")
def healthz(request: Request):
    return {
        "status": "ok",
        "env": request.app.state.settings.env,
        "app": request.app.state.settings.app_name,
    }


@health_router.get("/readyz")
def readyz(request: Request, db: Session = Depends(get_db)):
    checks = {"database": False, "redis": False, "redis_backend": request.app.state.redis_backend}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        request.app.state.redis.ping()
        checks["redis"] = True
    except Exception:  # noqa: BLE001
        pass
    ok = checks["database"] and checks["redis"]
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", **checks},
    )


def _total(db: Session, query) -> int:
    return int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)


def _offset(page: int, page_size: int) -> int:
    return (max(page, 1) - 1) * page_size


def _audit_view(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "ip": row.ip,
        "meta": row.meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@admin_router.get("/audit-logs")
def audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=200, description="兼容前端 limit，等价于 page_size"),
    account_id: int | None = Query(default=None, ge=1),
    actor_id: int | None = Query(default=None, ge=1),
    action: str | None = Query(default=None, max_length=64),
    target_type: str | None = Query(default=None, max_length=32),
    target_id: str | None = Query(default=None, max_length=64),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if limit:
        page_size = limit
    query = select(AuditLog)
    if account_id is not None:
        query = query.where(AuditLog.actor_id == account_id)
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if action:
        query = query.where(AuditLog.action == action)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    if start_at:
        query = query.where(AuditLog.created_at >= start_at)
    if end_at:
        query = query.where(AuditLog.created_at <= end_at)
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(AuditLog.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    return {
        "items": [_audit_view(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@admin_router.post("/subscriptions/expire-due")
def expire_due(
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    count = subsvc.expire_due(db)
    write_audit(db, actor_id=admin.id, action="subscription.expire_due", request=request,
                target_type="subscription", meta={"count": count})
    db.commit()
    return {"ok": True, "expired": count, "checked_at": utcnow().isoformat()}


# ---- 套餐管理 ---------------------------------------------------------------
@admin_router.get("/plans")
def admin_list_plans(
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """管理端套餐列表：包含已下架项，并标注状态；公开列表只返回上架项。"""
    plans = db.scalars(
        select(Plan).order_by(Plan.active.desc(), Plan.price_month_cents.asc(), Plan.id.asc())
    ).all()
    items = []
    for plan in plans:
        entitlements = subsvc.get_entitlements(db, plan.id)
        items.append(
            {
                "code": plan.code,
                "name": plan.name,
                "price_month_cents": plan.price_month_cents,
                "price_year_cents": plan.price_year_cents,
                "currency": plan.currency,
                "features": plan.features,
                "active": plan.active,
                "status": "上架" if plan.active else "已下架",
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
        )
    return {"plans": items}


# ---- 用户管理 ---------------------------------------------------------------
def _account_view(db: Session, account: Account) -> dict:
    sub = subsvc.get_active_subscription(db, account.id)
    return {
        "id": account.id,
        "email": account.email,
        "phone": account.phone,
        "status": account.status,
        "role": account.role,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "subscription": _sub_view(db, sub) if sub else None,
        "devices_count": int(
            db.scalar(select(func.count()).select_from(Device).where(Device.account_id == account.id)) or 0
        ),
    }


def _plan_of(db: Session, plan_id: int | None) -> Plan | None:
    return db.get(Plan, plan_id) if plan_id else None


def _sub_view(db: Session, sub: Subscription) -> dict:
    plan = _plan_of(db, sub.plan_id)
    now = utcnow()
    days_left = max(int((sub.current_end_at - now).total_seconds() // 86400), 0)
    return {
        "id": sub.id,
        "account_id": sub.account_id,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.name if plan else None,
        "status": sub.status,
        "current_start_at": sub.current_start_at.isoformat(),
        "current_end_at": sub.current_end_at.isoformat(),
        "days_left": days_left,
        "seats": sub.seats,
        "provider": sub.provider,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }


def _user_not_found() -> ApiError:
    return ApiError(404, "user_not_found", "用户不存在")


@admin_router.get("/users")
def list_users(
    q: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    role: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Account)
    if q:
        like = f"%{q}%"
        query = query.where((Account.email.ilike(like)) | (Account.phone.ilike(like)))
    if status:
        query = query.where(Account.status == status)
    if role:
        query = query.where(Account.role == role)
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(Account.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    return {
        "items": [_account_view(db, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@admin_router.get("/users/{account_id}")
def get_user(
    account_id: int,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    sub = subsvc.get_active_subscription(db, account_id)
    devices = db.scalars(
        select(Device).where(Device.account_id == account_id).order_by(Device.id.desc()).limit(20)
    ).all()
    recent_tasks = db.scalars(
        select(Task).where(Task.account_id == account_id).order_by(Task.created_at.desc()).limit(10)
    ).all()
    usage = QuotaService(db).summary(account_id)["metrics"] if sub else []
    return {
        "account": {
            "id": account.id,
            "email": account.email,
            "phone": account.phone,
            "status": account.status,
            "role": account.role,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        },
        "devices": [
            {
                "id": d.id,
                "platform": d.platform,
                "name": d.name,
                "status": d.status,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ],
        "subscription": _sub_view(db, sub) if sub else None,
        "recent_tasks": [
            {
                "id": t.id,
                "type": t.type,
                "status": t.status,
                "progress": t.progress,
                "created_at": t.created_at.isoformat(),
            }
            for t in recent_tasks
        ],
        "usage": usage,
    }


def _set_user_status(db: Session, account: Account, status: str, reason: str, request: Request, admin: Account) -> None:
    if account.role == "admin" and status == "banned":
        raise ApiError(409, "cannot_ban_admin", "不允许封禁管理员账号")
    before = account.status
    account.status = status
    if status == "banned":
        for session in db.scalars(
            select(RefreshSession).where(
                RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None)
            )
        ).all():
            session.revoked_at = utcnow()
    action = "user.ban" if status == "banned" else "user.unban"
    write_audit(
        db, actor_id=admin.id, action=action, request=request,
        target_type="account", target_id=str(account.id),
        meta={"status": status, "reason": reason, "before": before},
    )


@admin_router.post("/users/{account_id}/ban")
def ban_user(
    account_id: int,
    payload: AdminReasonRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    _set_user_status(db, account, "banned", payload.reason, request, admin)
    db.commit()
    return {"ok": True}


@admin_router.post("/users/{account_id}/unban")
def unban_user(
    account_id: int,
    payload: AdminReasonRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    _set_user_status(db, account, "active", payload.reason, request, admin)
    db.commit()
    return {"ok": True}


@admin_router.post("/users/{account_id}/status")
def set_user_status(
    account_id: int,
    payload: AdminUserStatusRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    _set_user_status(db, account, payload.status, payload.reason, request, admin)
    db.commit()
    return {"user": _account_view(db, account)}


def _delete_account(db: Session, account: Account, request: Request, admin: Account) -> None:
    """硬删除账号并级联清理其子表。

    PostgreSQL 外键约束生效且无 ON DELETE CASCADE，因此需按依赖拓扑序
    （引用者先删、被引用者后删）手动清理所有可达子表。
    """
    if account.role == "admin":
        raise ApiError(409, "cannot_delete_admin", "不允许删除管理员账号")
    if account.id == admin.id:
        raise ApiError(409, "cannot_delete_self", "不能删除当前登录的账号")
    account_id = account.id
    email = account.email

    tables = Base.metadata.tables

    # 1) 收集需清理的表：从 accounts 出发沿「被引用」方向可达的所有表（含传递表）
    relevant = {}
    frontier = ["accounts"]
    while frontier:
        current = frontier.pop()
        for table in tables.values():
            if table.name == "accounts" or table.name in relevant:
                continue
            if any(fk.column.table.name == current for fk in table.foreign_keys):
                relevant[table.name] = table
                frontier.append(table.name)

    def account_fk(table):
        return next(
            (
                f for f in table.foreign_keys
                if f.column.table.name == "accounts" and f.column.name == "id"
            ),
            None,
        )

    def scope_of(table):
        """该表中属于此账号的行：直接子表按 account_id；传递表按父表范围 in_ 子查询。"""
        fk = account_fk(table)
        if fk is not None:
            return fk.parent == account_id
        conds = []
        for f in table.foreign_keys:
            parent = f.column.table
            if parent.name == "accounts" or parent.name not in relevant:
                continue
            # 父表尚未删除（拓扑序保证），可用子查询圈定账号范围内的父行
            conds.append(f.parent.in_(select(f.column).where(scope_of(parent))))
        return or_(*conds) if conds else None

    # 2) 拓扑排序：A 引用 B ⇒ A 先删。如 orders(subscription_id) 先于 subscriptions
    indegree = {name: 0 for name in relevant}
    dependents = {name: [] for name in relevant}
    for name, table in relevant.items():
        for fk in table.foreign_keys:
            ref = fk.column.table.name
            if ref != name and ref in relevant:
                dependents[name].append(ref)
                indegree[ref] += 1
    queue = [name for name, deg in indegree.items() if deg == 0]
    order = []
    while queue:
        name = queue.pop()
        order.append(name)
        for ref in dependents[name]:
            indegree[ref] -= 1
            if indegree[ref] == 0:
                queue.append(ref)
    order.extend(name for name in relevant if name not in order)  # 兜底：异常成环不遗漏

    # 3) 按拓扑序清理子表，最后删除账号本体
    for name in order:
        condition = scope_of(relevant[name])
        if condition is not None:
            db.execute(sa_delete(relevant[name]).where(condition))

    db.delete(account)
    write_audit(
        db, actor_id=admin.id, action="user.delete", request=request,
        target_type="account", target_id=str(account_id),
        meta={"email": email, "role": account.role},
    )


@admin_router.delete("/users/{account_id}")
def delete_user(
    account_id: int,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """硬删除指定账号（含其全部子数据），仅管理员可用。"""
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    _delete_account(db, account, request, admin)
    db.commit()
    return {"deleted": True, "id": account_id}


@admin_router.delete("/users/by-email")
def delete_user_by_email(
    payload: AdminDeleteByEmailRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """按邮箱删除账号，便于调试邮箱注册产生的测试账号。"""
    email = payload.email.strip()
    account = db.scalars(select(Account).where(Account.email.ilike(email))).first()
    if account is None:
        raise _user_not_found()
    _delete_account(db, account, request, admin)
    db.commit()
    return {"deleted": True, "id": account.id, "email": account.email}


# ---- 订阅与额度 -------------------------------------------------------------
@admin_router.get("/subscriptions")
def list_subscriptions(
    q: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Subscription)
    if status:
        query = query.where(Subscription.status == status)
    if q:
        account_ids = db.scalars(
            select(Account.id).where(Account.email.ilike(f"%{q}%"))
        ).all()
        query = query.where(Subscription.account_id.in_(account_ids or [-1]))
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(Subscription.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    return {
        "items": [_sub_view(db, row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@admin_router.patch("/subscriptions/{subscription_id}")
@admin_router.post("/subscriptions/{subscription_id}/adjust")
def patch_subscription(
    subscription_id: int,
    payload: AdminSubscriptionPatchRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise ApiError(404, "subscription_not_found", "订阅不存在")
    before = _sub_view(db, sub)
    if payload.plan_code:
        sub.plan_id = subsvc.find_plan_by_code(db, payload.plan_code).id
    if payload.current_end_at is not None:
        sub.current_end_at = payload.current_end_at
    if payload.extend_days:
        sub.current_end_at = sub.current_end_at + timedelta(days=payload.extend_days)
    if payload.status and payload.status != sub.status:
        sub.status = payload.status
    sub.version += 1
    sub.updated_at = utcnow()
    audit = write_audit(
        db, actor_id=admin.id, action="subscription.adjust", request=request,
        target_type="subscription", target_id=str(sub.id),
        meta={"before": before, "after": {
            "plan_id": sub.plan_id,
            "status": sub.status,
            "current_end_at": sub.current_end_at.isoformat(),
        }, "note": payload.note},
    )
    db.commit()
    db.refresh(sub)
    db.refresh(audit)
    return {"subscription": _sub_view(db, sub), "audit": _audit_view(audit)}


def _adjustment_view(event: UsageEvent, before: int, after: int) -> dict:
    return {
        "id": event.id,
        "account_id": event.account_id,
        "metric": event.metric,
        "quantity": event.quantity,
        "reason": (event.meta or {}).get("reason"),
        "actor_id": (event.meta or {}).get("actor_id"),
        "before": before,
        "after": after,
        "created_at": event.occurred_at.isoformat() if event.occurred_at else None,
    }


@admin_router.post("/accounts/{account_id}/quota-adjustments")
def adjust_quota(
    account_id: int,
    payload: AdminQuotaAdjustRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    now = utcnow()
    start, end = period_of(now)
    key = request.headers.get("idempotency-key") or payload.idempotency_key or (
        f"admin-adjust:{account_id}:{payload.metric}:{uuid.uuid4()}"
    )
    existing = db.scalar(
        select(UsageEvent).where(
            UsageEvent.account_id == account_id, UsageEvent.idempotency_key == key
        )
    )
    if existing is not None:
        return {"duplicate": True, "event_id": existing.id}
    agg = db.scalar(
        select(UsageAggregate)
        .where(
            UsageAggregate.account_id == account_id,
            UsageAggregate.metric == payload.metric,
            UsageAggregate.period_start == start,
        )
        .with_for_update()
    )
    if agg is None:
        agg = UsageAggregate(
            account_id=account_id, metric=payload.metric,
            period_start=start, period_end=end, used=0, reserved=0,
        )
        db.add(agg)
        db.flush()
    before = agg.used
    agg.used = max(agg.used + payload.quantity, 0)
    agg.updated_at = now
    event = UsageEvent(
        account_id=account_id,
        task_id=None,
        metric=payload.metric,
        quantity=payload.quantity,
        unit="count",
        idempotency_key=key,
        occurred_at=now,
        meta={"manual": True, "reason": payload.reason, "actor_id": admin.id,
              "before": before, "after": agg.used},
    )
    db.add(event)
    audit = write_audit(
        db, actor_id=admin.id, action="quota.adjust", request=request,
        target_type="account", target_id=str(account_id),
        meta={"metric": payload.metric, "quantity": payload.quantity,
              "reason": payload.reason, "before": before, "after": agg.used},
    )
    db.commit()
    db.refresh(event)
    db.refresh(audit)
    return {
        "adjustment": _adjustment_view(event, before, agg.used),
        "audit": _audit_view(audit),
        "duplicate": False,
        "event_id": event.id,
        "before": before,
        "after": agg.used,
    }


@admin_router.get("/accounts/{account_id}/quota-adjustments")
def list_quota_adjustments(
    account_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(UsageEvent)
        .where(UsageEvent.account_id == account_id)
        .order_by(UsageEvent.id.desc())
        .limit(200)
    ).all()
    items = [
        {
            "id": row.id,
            "account_id": row.account_id,
            "metric": row.metric,
            "quantity": row.quantity,
            "reason": (row.meta or {}).get("reason"),
            "actor_id": (row.meta or {}).get("actor_id"),
            "before": (row.meta or {}).get("before"),
            "after": (row.meta or {}).get("after"),
            "created_at": row.occurred_at.isoformat() if row.occurred_at else None,
        }
        for row in rows
        if (row.meta or {}).get("manual")
    ][:limit]
    return {"items": items}


# ---- 订单 / 退款 / 对账查询 ---------------------------------------------------
def _order_view(order: Order) -> dict:
    return {
        "id": order.id,
        "account_id": order.account_id,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "status": order.status,
        "provider": order.provider,
        "external_order_no": order.external_order_no,
        "kind": order.kind,
        "cycle": order.cycle,
        "refunded_cents": order.refunded_cents,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "meta": order.meta,
    }


@admin_router.get("/orders")
def admin_orders(
    q: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    provider: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    if provider:
        query = query.where(Order.provider == provider)
    if q:
        if q.isdigit():
            query = query.where(Order.id == int(q))
        else:
            ids = db.scalars(
                select(Account.id).where(Account.email.ilike(f"%{q}%"))
            ).all()
            query = query.where(Order.account_id.in_(ids or [-1]))
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(Order.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    return {"items": [_order_view(o) for o in rows], "total": total,
            "page": page, "page_size": page_size}


@admin_router.get("/orders/{order_id}")
def admin_order_detail(
    order_id: int,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if order is None:
        raise ApiError(404, "order_not_found", "订单不存在")
    refunds = db.scalars(
        select(Refund).where(Refund.order_id == order_id).order_by(Refund.id.desc())
    ).all()
    return {
        "order": _order_view(order),
        "refunds": [
            {
                "id": r.id,
                "order_id": r.order_id,
                "account_id": r.account_id,
                "amount_cents": r.amount_cents,
                "status": r.status,
                "provider": r.provider,
                "reason": r.reason,
                "requested_at": r.requested_at.isoformat(),
                "succeeded_at": r.succeeded_at.isoformat() if r.succeeded_at else None,
            }
            for r in refunds
        ],
    }


@admin_router.get("/reconcile-reports")
def admin_reconcile_reports(
    provider: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=20, ge=1, le=100),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(ReconcileReport).order_by(ReconcileReport.id.desc()).limit(limit)
    if provider:
        query = query.where(ReconcileReport.provider == provider)
    rows = db.scalars(query).all()
    return {"items": [
        {"id": r.id, "provider": r.provider, "biz_date": r.biz_date.isoformat(),
         "summary": r.summary, "channel_source": r.channel_source}
        for r in rows
    ]}


# ---- 任务看板 ---------------------------------------------------------------
def _task_brief(task: Task) -> dict:
    return {
        "id": task.id,
        "account_id": task.account_id,
        "type": task.type,
        "status": task.status,
        "progress": task.progress,
        "error_code": task.error_code,
        "attempts": task.attempts,
        "lease_until": task.lease_until.isoformat() if task.lease_until else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "created_at": task.created_at.isoformat(),
    }


@admin_router.get("/tasks/dashboard")
def tasks_dashboard(
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    counts = dict(db.execute(select(Task.status, func.count()).group_by(Task.status)).all())
    running = db.scalars(
        select(Task).where(Task.status == "running").order_by(Task.started_at.desc()).limit(20)
    ).all()
    failed = db.scalars(
        select(Task).where(Task.status == "failed").order_by(Task.created_at.desc()).limit(20)
    ).all()
    return {
        "queue_depth": int(counts.get("queued", 0)),
        "running_count": int(counts.get("running", 0)),
        "failed_count": int(counts.get("failed", 0)),
        "retryable_count": int(
            db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.status == "failed", Task.attempts < 3
                )
            ) or 0
        ),
        "generated_at": utcnow().isoformat(),
        "running": [_task_brief(t) for t in running],
        "failed": [_task_brief(t) for t in failed],
        "by_status": {str(k): int(v) for k, v in counts.items()},
    }


@admin_router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: str,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", "任务不存在")
    if task.status not in ("failed", "canceled"):
        raise ApiError(409, "task_not_retryable", f"当前状态不可重试：{task.status}")
    task.status = "queued"
    task.cancel_requested = False
    task.error_code = None
    task.error_message = None
    task.lease_until = None
    task.attempts = 0
    for step in db.scalars(select(TaskStep).where(TaskStep.task_id == task_id)).all():
        if step.status in ("failed", "running"):
            step.status = "pending"
    write_audit(db, actor_id=admin.id, action="task.retry", request=request,
                target_type="task", target_id=task_id)
    db.commit()
    return {"ok": True, "task_id": task_id}


@admin_router.get("/tasks")
def admin_tasks(
    status: str | None = Query(default=None, max_length=16),
    account_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if status:
        query = query.where(Task.status == status)
    if account_id:
        query = query.where(Task.account_id == account_id)
    rows = db.scalars(query).all()
    return {"items": [_task_brief(t) for t in rows]}


# ---- 告警 / 通知 -------------------------------------------------------------
@admin_router.get("/alerts")
def admin_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(Notification).where(Notification.category == "usage_anomaly")
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(Notification.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    items = []
    for row in rows:
        context = (row.meta or {}).get("context", {})
        items.append(
            {
                "id": row.id,
                "account_id": row.account_id,
                "level": row.level,
                "status": row.status,
                "metric": context.get("metric"),
                "quantity": context.get("used_today"),
                "threshold": context.get("threshold"),
                "message": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    # 兼容旧探测：附带近期通道失败与 webhook 失败计数
    since = utcnow() - timedelta(hours=24)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "window_hours": 24,
        "failed_notifications": int(
            db.scalar(
                select(func.count()).select_from(NotificationDelivery).where(
                    NotificationDelivery.status == "failed", NotificationDelivery.created_at >= since
                )
            ) or 0
        ),
        "webhook_failures": int(
            db.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.action == "payment.webhook_rejected", AuditLog.created_at >= since
                )
            ) or 0
        ),
    }


@admin_router.get("/notifications")
def admin_notifications(
    status: str | None = Query(default=None, max_length=16),
    channel: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(NotificationDelivery)
    if status:
        query = query.where(NotificationDelivery.status == status)
    if channel:
        query = query.where(NotificationDelivery.channel == channel)
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(NotificationDelivery.id.desc()).offset(_offset(page, page_size)).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": d.id,
                "account_id": d.account_id,
                "channel": d.channel,
                "recipient": d.recipient,
                "subject": d.subject,
                "template": d.category,
                "status": d.status,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "created_at": d.created_at.isoformat(),
                "sent_at": d.sent_at.isoformat() if d.sent_at else None,
            }
            for d in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@admin_router.get("/notification-deliveries")
def admin_deliveries(
    status: str | None = Query(default=None, max_length=16),
    channel: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(NotificationDelivery).order_by(NotificationDelivery.id.desc()).limit(limit)
    if status:
        query = query.where(NotificationDelivery.status == status)
    if channel:
        query = query.where(NotificationDelivery.channel == channel)
    rows = db.scalars(query).all()
    return {"items": [
        {"id": d.id, "account_id": d.account_id, "channel": d.channel,
         "category": d.category, "recipient": d.recipient, "status": d.status,
         "attempts": d.attempts, "last_error": d.last_error,
         "created_at": d.created_at.isoformat(),
         "sent_at": d.sent_at.isoformat() if d.sent_at else None}
        for d in rows
    ]}


@admin_router.post("/notifications/{delivery_id}/retry")
def retry_notification(
    delivery_id: int,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    delivery = db.get(NotificationDelivery, delivery_id)
    if delivery is None:
        raise ApiError(404, "delivery_not_found", "发送记录不存在")
    if delivery.status not in ("failed", "skipped"):
        raise ApiError(409, "delivery_not_retryable", f"当前状态不可重试：{delivery.status}")
    delivery.status = "failed"
    delivery.attempts = 0
    delivery.next_retry_at = utcnow() - timedelta(seconds=1)
    db.flush()
    nsvc.retry_deliveries(db, request.app.state.settings, utcnow())
    write_audit(db, actor_id=admin.id, action="notification.retry", request=request,
                target_type="notification_delivery", target_id=str(delivery_id))
    db.commit()
    db.refresh(delivery)
    return {"ok": delivery.status == "sent", "status": delivery.status}


@admin_router.post("/notifications")
def admin_send_notification(
    payload: AdminNotificationRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if db.get(Account, payload.account_id) is None:
        raise _user_not_found()
    row = nsvc.emit(
        db,
        account_id=payload.account_id,
        category="admin_message",
        dedupe_key=f"admin:{uuid.uuid4()}",
        context={"title": payload.title, "body": payload.body},
        settings=request.app.state.settings,
        channels=tuple(payload.channels) if payload.channels else None,
    )
    write_audit(
        db, actor_id=admin.id, action="notification.send", request=request,
        target_type="account", target_id=str(payload.account_id),
        meta={"notification_id": row.id if row else None, "channels": payload.channels},
    )
    db.commit()
    return {"notification_id": row.id if row else None}


# ---- 兼容旧看板路径 / 汇总 ----------------------------------------------------
@admin_router.get("/dashboard")
def dashboard(
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    board = tasks_dashboard(_staff=_staff, db=db)
    alerts = admin_alerts(page=1, page_size=5, _staff=_staff, db=db)
    return {
        "tasks": {
            "by_status": board["by_status"],
            "queued": board["queue_depth"],
            "running": board["running_count"],
            "succeeded": board["by_status"].get("succeeded", 0),
            "failed": board["failed_count"],
            "canceled": board["by_status"].get("canceled", 0),
        },
        "alerts": alerts,
        "pending_refunds": db.scalar(
            select(func.count()).select_from(Refund).where(Refund.status == "pending")
        ),
        "paid_orders_24h": db.scalar(
            select(func.count()).select_from(Order).where(
                Order.status == "paid", Order.paid_at >= utcnow() - timedelta(hours=24)
            )
        ),
    }


# ---- 工序模型配置（后台纳管） ----------------------------------------------------
@admin_router.get("/model-configs")
def list_model_configs(
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminModelConfigView]:
    """列出所有工序模块的当前生效模型配置（DB 覆盖 / default 兜底 / 环境变量）。"""
    settings = request.app.state.settings
    return [AdminModelConfigView(**row) for row in describe_configs(db, settings)]


@admin_router.put("/model-configs/{step_key}")
def upsert_model_config(
    step_key: str,
    payload: AdminModelConfigUpsert,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminModelConfigView:
    """新增或更新某工序的模型配置；api_key 留空(null)表示不改动已存 Key，空串表示清空。"""
    settings = request.app.state.settings
    if step_key == "default" and not payload.model:
        raise ApiError(422, "model_required", "default 兜底配置必须填写模型")
    if step_key not in model_config_svc.STEP_REGISTRY:
        raise ApiError(404, "unknown_step", f"未知工序：{step_key}")
    row = db.scalars(select(ModelProviderConfig).where(ModelProviderConfig.step_key == step_key)).one_or_none()
    if row is None:
        row = ModelProviderConfig(step_key=step_key)
        db.add(row)
    row.label = payload.label or model_config_svc.STEP_REGISTRY.get(step_key, step_key)
    row.provider = payload.provider
    row.model = payload.model
    row.base_url = payload.base_url or (
        "https://ai-gateway.edgeone.link/v1" if payload.provider == "edgeone" else settings.llm_base_url
    )
    if payload.api_key is not None:
        row.api_key = encrypt_key(payload.api_key, settings) if payload.api_key else None
    row.enabled = payload.enabled
    row.updated_at = utcnow()
    row.updated_by = _admin.id
    db.commit()
    db.refresh(row)
    eff = resolve_step_model(db, step_key, settings)
    write_audit(
        db, actor_id=_admin.id, action="model_config.update", request=request,
        target_type="model_provider", target_id=step_key,
        meta={"provider": row.provider, "model": row.model, "enabled": row.enabled, "key_set": bool(row.api_key)},
    )
    return AdminModelConfigView(
        step_key=row.step_key, label=row.label, configured=True,
        provider=row.provider, model=row.model, base_url=row.base_url,
        enabled=row.enabled, key_set=bool(row.api_key), source=eff.source,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        recommendation=model_config_svc.recommendation_for(step_key),
        recommended_match=model_config_svc.recommended_match(
            step_key,
            eff.model,
            provider=eff.provider,
            configured=bool(row.enabled) and bool(eff.model),
        ),
    )


@admin_router.delete("/model-configs/{step_key}")
def delete_model_config(
    step_key: str,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除某工序的模型配置（重置为 default/环境变量兜底）。default 不可删。"""
    if step_key == "default":
        raise ApiError(409, "cannot_delete_default", "default 兜底配置不可删除（可清空 Key 并停用）")
    row = db.scalars(select(ModelProviderConfig).where(ModelProviderConfig.step_key == step_key)).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "该工序未配置覆盖")
    label = row.label
    db.delete(row)
    write_audit(
        db, actor_id=_admin.id, action="model_config.delete", request=request,
        target_type="model_provider", target_id=step_key, meta={"label": label},
    )
    db.commit()
    return {"deleted": True, "step_key": step_key}


@admin_router.post("/model-configs/{step_key}/test")
def test_model_config(
    step_key: str,
    payload: AdminModelConfigUpsert,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用提交（或已存）的配置做一次最小调用，验证模型/Key/base_url 是否可用。"""
    settings = request.app.state.settings
    if step_key not in model_config_svc.STEP_REGISTRY:
        raise ApiError(404, "unknown_step", f"未知工序：{step_key}")
    base_url = payload.base_url or (
        "https://ai-gateway.edgeone.link/v1" if payload.provider == "edgeone" else settings.llm_base_url
    )
    api_key = payload.api_key or ""
    if not api_key:
        stored = db.scalars(select(ModelProviderConfig).where(ModelProviderConfig.step_key == step_key)).one_or_none()
        if stored and stored.api_key:
            api_key = decrypt_key(stored.api_key, settings) or ""
    if not api_key:
        api_key = settings.llm_api_key
    try:
        result = complete_sync(
            settings, [{"role": "user", "content": "ping"}],
            model=payload.model, api_key=api_key, base_url=base_url or None,
        )
    except Exception as exc:  # noqa: BLE001 - 明确返回上游错误给后台
        raise ApiError(502, "model_test_failed", f"调用失败：{exc}")
    return {"ok": True, "model": result.model, "tokens": result.total_tokens}


# ---- 离线版安装包（后台上传纳管） -------------------------------------------------
OFFLINE_PLATFORMS = {"windows", "android"}
OFFLINE_SUFFIX = {"windows": ".exe", "android": ".apk"}
OFFLINE_MEDIA = {
    "windows": "application/vnd.microsoft.portable-executable",
    "android": "application/vnd.android.package-archive",
}
VERSION_RE = re.compile(r"v(\d+(?:\.\d+)*)", re.IGNORECASE)


def _version_of(name: str) -> str:
    matched = VERSION_RE.search(name)
    return matched.group(1) if matched else ""


def _offline_view(pkg: OfflinePackage, settings) -> dict:
    return {
        "id": pkg.id,
        "platform": pkg.platform,
        "version": pkg.version,
        "filename": pkg.filename,
        "size": pkg.size,
        "content_type": pkg.content_type,
        "is_active": pkg.is_active,
        "release_notes": pkg.release_notes,
        "uploaded_by": pkg.uploaded_by,
        "created_at": pkg.created_at.isoformat() if pkg.created_at else None,
        "updated_at": pkg.updated_at.isoformat() if pkg.updated_at else None,
        "download_url": f"{settings.api_prefix}/admin/offline-packages/{pkg.id}/download",
    }


class _CountingReader:
    """边读边计数并限大小，避免把超大安装包整段读入内存。"""

    def __init__(self, src, max_bytes: int):
        self.src = src
        self.max = max_bytes
        self.n = 0

    def read(self, size: int = -1):
        chunk = self.src.read(size if size and size > 0 else 1024 * 1024)
        if not chunk:
            return chunk
        self.n += len(chunk)
        if self.n > self.max:
            raise ApiError(413, "package_too_large", f"安装包超过大小限制（{self.max} 字节）")
        return chunk


@admin_router.get("/offline-packages")
def list_offline_packages(
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict]:
    """列出所有后台上传的离线安装包（含历史版本），按平台+时间倒序。"""
    rows = db.scalars(
        select(OfflinePackage).order_by(OfflinePackage.platform, OfflinePackage.created_at.desc())
    ).all()
    return [_offline_view(r, request.app.state.settings) for r in rows]


@admin_router.get("/offline-packages/limits")
def offline_package_limits(
    request: Request,
    _admin: Account = Depends(require_admin),
) -> dict:
    """上传前的前置校验信息：单文件大小上限与各平台要求的扩展名。

    前端拿到上限后可提前拦住超大文件，避免整包传完才被 413 打断。
    """
    settings = request.app.state.settings
    return {
        "max_bytes": settings.offline_package_max_bytes,
        "suffix": dict(OFFLINE_SUFFIX),
    }


@admin_router.post("/offline-packages")
async def upload_offline_package(
    request: Request,
    platform: str = Form(...),
    version: str = Form(""),
    release_notes: str = Form(""),
    file: UploadFile = File(...),
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """上传并提交一个离线安装包（multipart）。上传后自动成为该平台的当前版本。"""
    settings = request.app.state.settings
    if platform not in OFFLINE_PLATFORMS:
        raise ApiError(422, "bad_platform", "platform 必须为 windows 或 android")
    if not file.filename:
        raise ApiError(422, "invalid_filename", "缺少文件名")
    suffix = Path(file.filename).suffix.lower()
    if suffix != OFFLINE_SUFFIX[platform]:
        raise ApiError(415, "bad_file_type", f"{platform} 安装包扩展名需为 {OFFLINE_SUFFIX[platform]}")
    max_bytes = settings.offline_package_max_bytes
    declared = getattr(file, "size", None)
    if declared is not None and declared > max_bytes:
        raise ApiError(413, "package_too_large", f"安装包超过大小限制（{max_bytes} 字节）")
    version_val = (version or "").strip() or _version_of(file.filename) or "0.0.0"
    safe = safe_upload_name(file.filename)
    key = f"offline/{platform}/{uuid.uuid4().hex}-{safe}"
    reader = _CountingReader(file.file, max_bytes)
    try:
        request.app.state.storage.put_stream(key, reader, content_type=OFFLINE_MEDIA[platform])
    except ApiError:
        request.app.state.storage.delete(key)
        raise
    pkg = OfflinePackage(
        platform=platform,
        version=version_val,
        filename=safe,
        source_key=key,
        content_type=OFFLINE_MEDIA[platform],
        size=reader.n,
        is_active=True,
        release_notes=(release_notes or None),
        uploaded_by=_admin.id,
    )
    db.add(pkg)
    # 同平台历史版本置为非当前
    db.execute(
        update(OfflinePackage)
        .where(OfflinePackage.platform == platform, OfflinePackage.id != pkg.id)
        .values(is_active=False)
    )
    db.commit()
    db.refresh(pkg)
    write_audit(
        db, actor_id=_admin.id, action="offline_package.upload", request=request,
        target_type="offline_package", target_id=str(pkg.id),
        meta={"platform": platform, "version": version_val, "size": reader.n, "filename": safe},
    )
    return _offline_view(pkg, settings)


@admin_router.delete("/offline-packages/{pkg_id}")
def delete_offline_package(
    pkg_id: int,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除某条安装包记录；若删的是当前版本，则把该平台最新剩余记录提升为当前。"""
    pkg = db.get(OfflinePackage, pkg_id)
    if pkg is None:
        raise ApiError(404, "not_found", "安装包不存在")
    was_active = pkg.is_active
    request.app.state.storage.delete(pkg.source_key)
    db.delete(pkg)
    if was_active:
        nxt = db.scalars(
            select(OfflinePackage)
            .where(OfflinePackage.platform == pkg.platform)
            .order_by(OfflinePackage.created_at.desc())
        ).first()
        if nxt is not None:
            nxt.is_active = True
    write_audit(
        db, actor_id=_admin.id, action="offline_package.delete", request=request,
        target_type="offline_package", target_id=str(pkg_id),
        meta={"platform": pkg.platform, "version": pkg.version},
    )
    db.commit()
    return {"deleted": True, "id": pkg_id}


@admin_router.get("/offline-packages/{pkg_id}/download")
def download_offline_package(
    pkg_id: int,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """后台直接下载某条安装包（便于管理员校验），鉴权复用 require_admin。"""
    pkg = db.get(OfflinePackage, pkg_id)
    if pkg is None:
        raise ApiError(404, "not_found", "安装包不存在")
    data = request.app.state.storage.get_bytes(pkg.source_key)
    name = pkg.filename
    ascii_name = name.encode("ascii", "ignore").decode() or "package"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content=data,
        media_type=pkg.content_type or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )
