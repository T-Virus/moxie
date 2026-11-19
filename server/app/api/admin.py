# -*- coding: utf-8 -*-
"""健康检查、就绪检查、审计查询与运营管理接口（对齐 admin/README.md 契约）。

权限：
  · 只读接口 require_staff（admin / support）；
  · 写接口 require_admin，且全部写 audit_logs。
"""

from __future__ import annotations

import csv
import io
import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import require_admin, require_staff
from ..errors import ApiError
from ..metrics import HISTOGRAM_BUCKETS, histogram_snapshot
from ..models import (
    Account,
    AccountDeletionRequest,
    AgentRun,
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
    TaskEvent,
    TaskStep,
    AgentRunEvent,
    UsageAggregate,
    UsageEvent,
)
from ..schemas import (
    AccountDeletionListResponse,
    AccountDeletionRequestView,
    AdminAlertsResponse,
    AdminDashboardResponse,
    AdminDeadLettersResponse,
    AdminModelConfigDeleteResponse,
    AdminModelConfigTestResponse,
    AdminPerformanceResponse,
    AdminTaskReplayBatchRequest,
    AdminTaskReplayBatchResponse,
    AdminTaskReplayRequest,
    AdminTaskReplayResult,
    AdminTasksDashboardResponse,
    BackupCreateResponse,
    BackupDeleteResponse,
    BackupListView,
    BackupRestoreRequest,
    BackupRestoreResponse,
    ModelUsageResponse,
    AdminDeleteByEmailRequest,
    AdminModelConfigUpsert,
    AdminModelConfigView,
    OfflinePackageDeleteResponse,
    OfflinePackageLimitsResponse,
    OfflinePackageView,
    AdminNotificationDetailResponse,
    AdminNotificationBatchRequest,
    AdminNotificationBatchResponse,
    AdminNotificationRequest,
    AdminNotificationsResponse,
    AdminOrdersResponse,
    AdminPlanUpdate,
    AdminPlanView,
    AdminPlansResponse,
    AdminPresetDeleteResponse,
    AdminPresetListResponse,
    AdminPresetSyncResponse,
    AdminPresetView,
    AdminQuotaAdjustRequest,
    AdminQuotaAdjustResponse,
    AdminQuotaAdjustmentsResponse,
    AdminReasonRequest,
    AdminReconcileReportsResponse,
    AdminSubscriptionPatchRequest,
    AdminSubscriptionsResponse,
    AdminTaskControlRequest,
    AdminTasksResponse,
    AdminUserStatusRequest,
    AdminUsersResponse,
    AuditLogsResponse,
    BackupConfigUpdate,
    BackupConfigView,
    HealthResponse,
    PushReceiptHistoryResponse,
    TelemetryConfigUpdate,
    TelemetryConfigView,
)
from ..services import backup as backupsvc
from ..services import data_rights
from ..services import model_config as model_config_svc
from ..services import runtime_config
from ..services import notifications as nsvc
from ..services import password_reset
from ..services import subscription as subsvc
from ..services import usage_stats
from ..services.audit import write_audit
from ..services.model_config import describe_configs, encrypt_key, resolve_step_model
from ..services.model_gateway import complete_sync, validate_upstream_base_url
from ..services.sse import SSE_MAX_TICKS, SSE_POLL_SECONDS, sse_context, sse_response
from ..services.uploads import safe_filename as safe_upload_name
from ..services.quota import QuotaService, period_of
from ..agents.store import run_to_dict
from ..services.tasks import task_to_dict
from .telemetry import redact as redact_error_text

# 统一预设值维护（后台纳管）
from ..models import Preset
from ..schemas import AdminPresetUpsert
from ..seed import seed_presets

health_router = APIRouter(tags=["ops"])
logger = logging.getLogger("moxie.admin")

admin_router = APIRouter(prefix="/admin", tags=["admin"])


@health_router.get("/healthz", response_model=HealthResponse)
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


@admin_router.get("/audit-logs", response_model=AuditLogsResponse)
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
def _admin_plan_view(db: Session, plan: Plan) -> dict:
    entitlements = subsvc.get_entitlements(db, plan.id)
    return {
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


@admin_router.get("/plans", response_model=AdminPlansResponse)
def admin_list_plans(
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """管理端套餐列表：包含已下架项，并标注状态；公开列表只返回上架项。"""
    plans = db.scalars(
        select(Plan).order_by(Plan.active.desc(), Plan.price_month_cents.asc(), Plan.id.asc())
    ).all()
    return {"plans": [_admin_plan_view(db, plan) for plan in plans]}


@admin_router.patch("/plans/{plan_code}", response_model=AdminPlanView)
def admin_update_plan(
    plan_code: str,
    payload: AdminPlanUpdate,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """后台调整套餐价格 / 名称 / 上下架与权益上限；改动即时对公开套餐页生效。"""
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        raise ApiError(404, "plan_not_found", f"套餐不存在：{plan_code}")

    changes: dict[str, object] = {}
    if payload.name is not None:
        plan.name = payload.name.strip()
        changes["name"] = plan.name
    if payload.price_month_cents is not None:
        plan.price_month_cents = int(payload.price_month_cents)
        changes["price_month_cents"] = plan.price_month_cents
    if payload.price_year_cents is not None:
        plan.price_year_cents = int(payload.price_year_cents)
        changes["price_year_cents"] = plan.price_year_cents
    if payload.active is not None:
        plan.active = bool(payload.active)
        changes["active"] = plan.active
    if payload.entitlements:
        current = subsvc.get_entitlements(db, plan.id)
        unknown = sorted(set(payload.entitlements) - set(current))
        if unknown:
            raise ApiError(422, "unknown_entitlement", f"未知权益项：{', '.join(unknown)}")
        for key, value in payload.entitlements.items():
            limit = int(value)
            if limit < -1 or limit > 1_000_000_000:
                raise ApiError(422, "invalid_entitlement_limit", f"{key} 的上限必须是 -1 或非负整数")
            current[key].limit_value = limit
            changes[f"entitlements.{key}"] = limit

    write_audit(
        db,
        actor_id=admin.id,
        action="plan.update",
        request=request,
        target_type="plan",
        target_id=plan.code,
        meta=changes,
    )
    db.commit()
    db.refresh(plan)
    return _admin_plan_view(db, plan)


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


@admin_router.get("/users", response_model=AdminUsersResponse)
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
    # 用户详情「最近任务」同样要覆盖用户触发的写作运行，否则与创作页/看板数据不一致
    recent_tasks = db.scalars(
        select(Task).where(Task.account_id == account_id).order_by(Task.created_at.desc()).limit(10)
    ).all()
    recent_runs = db.scalars(
        select(AgentRun).where(AgentRun.account_id == account_id)
        .order_by(AgentRun.created_at.desc()).limit(10)
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
        "recent_tasks": sorted(
            [
                {
                    "id": t.id,
                    "type": t.type,
                    "status": t.status,
                    "progress": t.progress,
                    "created_at": t.created_at.isoformat(),
                    "source": "task",
                    "title": None,
                }
                for t in recent_tasks
            ]
            + [
                {
                    "id": r.id,
                    "type": f"agent_run:{r.mode}",
                    "status": r.status,
                    "progress": r.progress,
                    "created_at": r.created_at.isoformat(),
                    "source": "agent_run",
                    "title": r.title,
                }
                for r in recent_runs
            ],
            key=lambda row: row["created_at"],
            reverse=True,
        )[:10],
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


@admin_router.post("/users/{account_id}/reset-password")
def reset_user_password(
    account_id: int,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """客服代发重置密码邮件：不下发明文密码，链接一次性且限时有效。"""
    account = db.get(Account, account_id)
    if account is None:
        raise _user_not_found()
    if not account.email:
        raise ApiError(400, "email_missing", "该账号未绑定邮箱，无法发送重置邮件")
    if account.status in ("disabled", "banned"):
        raise ApiError(409, "account_disabled", "账号已停用，请先解封后再重置密码")
    settings = request.app.state.settings
    password_reset.check_cooldown(db, account.id, settings)
    _token, reset_url, sent = password_reset.issue(db, account, settings, request)
    write_audit(
        db, actor_id=admin.id, action="user.password_reset_requested", request=request,
        target_type="account", target_id=str(account.id), meta={"sent": sent},
    )
    db.commit()
    result = {
        "ok": True,
        "email": account.email,
        "sent": sent,
        "message": "重置密码邮件已发送。" if sent else "邮件未发出（SMTP 未配置），请检查服务配置。",
    }
    if not sent and not settings.is_production:
        result["reset_url"] = reset_url
    return result


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
    """硬删除账号：与用户注销到期清理共用同一套级联/对象清理逻辑。"""
    data_rights.purge_account(
        db,
        account,
        actor_id=admin.id,
        settings=request.app.state.settings,
        storage=request.app.state.storage,
        request=request,
        audit_action="user.delete",
    )


# 静态路由必须注册在 /users/{account_id} 之前：Starlette 按注册顺序匹配，
# 否则 DELETE /users/by-email 会被动态段吞掉，account_id="by-email" 导致 422。
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


# ---- 用户注销申请 -----------------------------------------------------------
@admin_router.get("/account-deletions", response_model=AccountDeletionListResponse)
def list_account_deletions(
    status: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(AccountDeletionRequest)
    if status:
        query = query.where(AccountDeletionRequest.status == status)
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(AccountDeletionRequest.purge_at)
        .offset(_offset(page, page_size))
        .limit(page_size)
    ).all()
    return {"items": [data_rights.deletion_view(row) for row in rows], "total": total}


@admin_router.post("/account-deletions/{request_id}/cancel", response_model=AccountDeletionRequestView)
def cancel_account_deletion(
    request_id: int,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """撤销注销申请并恢复账号登录；原会话已吊销，用户需重新登录。"""
    row = db.get(AccountDeletionRequest, request_id)
    if row is None:
        raise ApiError(404, "deletion_request_not_found", "注销申请不存在")
    result = data_rights.cancel_deletion(db, row, request=request, actor_id=admin.id)
    db.commit()
    return result


@admin_router.post("/account-deletions/{request_id}/purge")
def purge_account_deletion(
    request_id: int,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员立即执行已申请的注销（跳过剩余宽限期）。"""
    row = db.get(AccountDeletionRequest, request_id)
    if row is None or row.status != "pending":
        raise ApiError(404, "deletion_request_not_found", "待处理的注销申请不存在")
    account = db.get(Account, row.account_id)
    if account is None:
        raise ApiError(404, "account_not_found", "账号不存在")
    result = data_rights.purge_account(
        db,
        account,
        actor_id=admin.id,
        settings=request.app.state.settings,
        storage=request.app.state.storage,
        request=request,
        reason="admin_immediate_purge",
        audit_action="account.deleted",
    )
    db.commit()
    return {"deleted": True, **result}


# ---- 订阅与额度 -------------------------------------------------------------
@admin_router.get("/subscriptions", response_model=AdminSubscriptionsResponse)
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


@admin_router.post("/accounts/{account_id}/quota-adjustments", response_model=AdminQuotaAdjustResponse)
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
    # 与后台表单「正数增加，负数扣减」保持一致：quantity 是**可用额度**的增减量，
    # 而 used 是已消耗量。此前写成 used += quantity，导致管理员补偿 +20 反而
    # 把用户可用额度扣掉 20（跨端语义相反）。
    agg.used = max(agg.used - payload.quantity, 0)
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
              "before": before, "after": agg.used,
              "direction": "grant" if payload.quantity >= 0 else "deduct"},
    )
    db.add(event)
    audit = write_audit(
        db, actor_id=admin.id, action="quota.adjust", request=request,
        target_type="account", target_id=str(account_id),
        meta={"metric": payload.metric, "quantity": payload.quantity,
              "reason": payload.reason, "before": before, "after": agg.used,
              "direction": "grant" if payload.quantity >= 0 else "deduct"},
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


@admin_router.get("/accounts/{account_id}/quota-adjustments", response_model=AdminQuotaAdjustmentsResponse)
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


@admin_router.get("/orders", response_model=AdminOrdersResponse)
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


@admin_router.get("/reconcile-reports", response_model=AdminReconcileReportsResponse)
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
# 看板聚合两类「用户触发的任务」：拆解/改编任务（tasks）与写作运行（agent_runs）。
# 二者由不同接口创建、落在不同表，早期看板只读 tasks，导致创作页触发的写作任务
# 完全不出现在看板上。此处统一读取同一套 brief 结构，保证前后端数据一致。
# 运行中任务超过该时长没有心跳（章节完成、阶段切换都会刷新），视为疑似卡死，
# 运营据此判断是否需要「重新排队」或「强制终止」。
STALLED_SECONDS = 900


def _stalled(status: str, last_activity: datetime | None) -> bool:
    if status != "running" or last_activity is None:
        return False
    return (utcnow() - last_activity).total_seconds() > STALLED_SECONDS


def _task_brief(task: Task) -> dict:
    last_activity = task.heartbeat_at or task.started_at or task.created_at
    return {
        "id": task.id,
        "account_id": task.account_id,
        "type": task.type,
        "status": task.status,
        "progress": task.progress,
        "error_code": task.error_code,
        "error_message": None,
        "attempts": task.attempts,
        "lease_until": task.lease_until.isoformat() if task.lease_until else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat(),
        "last_activity_at": last_activity.isoformat() if last_activity else None,
        "stalled": _stalled(task.status, last_activity),
        "source": "task",
        "mode": None,
        "title": None,
    }


def _agent_run_brief(run: AgentRun) -> dict:
    last_activity = run.updated_at or run.started_at or run.created_at
    return {
        "id": run.id,
        "account_id": run.account_id,
        "type": f"agent_run:{run.mode}",
        "status": run.status,
        "progress": run.progress,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "attempts": run.attempts,
        "lease_until": None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat(),
        "last_activity_at": last_activity.isoformat() if last_activity else None,
        "stalled": _stalled(run.status, last_activity),
        "source": "agent_run",
        "mode": run.mode,
        "title": run.title,
    }


def _status_counts(db: Session) -> dict[str, int]:
    task_counts = dict(
        db.execute(select(Task.status, func.count()).group_by(Task.status)).all()
    )
    run_counts = dict(
        db.execute(select(AgentRun.status, func.count()).group_by(AgentRun.status)).all()
    )
    merged: dict[str, int] = {}
    for status in set(task_counts) | set(run_counts):
        merged[str(status)] = int(task_counts.get(status, 0)) + int(run_counts.get(status, 0))
    return merged


def _briefs_by_status(db: Session, status: str, *, order_by_started: bool) -> list[dict]:
    order = Task.started_at if order_by_started else Task.created_at
    tasks = db.scalars(
        select(Task).where(Task.status == status).order_by(order.desc()).limit(20)
    ).all()
    run_order = AgentRun.started_at if order_by_started else AgentRun.created_at
    runs = db.scalars(
        select(AgentRun).where(AgentRun.status == status).order_by(run_order.desc()).limit(20)
    ).all()
    briefs = [_task_brief(t) for t in tasks] + [_agent_run_brief(r) for r in runs]
    key = "started_at" if order_by_started else "created_at"
    briefs.sort(key=lambda row: row[key] or row["created_at"] or "", reverse=True)
    return briefs[:20]


@admin_router.get("/tasks/dashboard", response_model=AdminTasksDashboardResponse)
def tasks_dashboard(
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    counts = _status_counts(db)
    retryable = int(
        db.scalar(
            select(func.count()).select_from(Task).where(
                Task.status == "failed", Task.attempts < 3
            )
        ) or 0
    ) + int(
        db.scalar(
            select(func.count()).select_from(AgentRun).where(
                AgentRun.status == "failed", AgentRun.attempts < 3
            )
        ) or 0
    )
    return {
        "queue_depth": int(counts.get("queued", 0)),
        "running_count": int(counts.get("running", 0)),
        "failed_count": int(counts.get("failed", 0)),
        "retryable_count": retryable,
        "generated_at": utcnow().isoformat(),
        "running": _briefs_by_status(db, "running", order_by_started=True),
        "failed": _briefs_by_status(db, "failed", order_by_started=False),
        "by_status": counts,
    }


def _is_dead_letter(task: Task, settings) -> bool:
    return task.status == "failed" and task.attempts >= settings.task_max_attempts


def _requeue_failed_task(
    task: Task,
    request: Request,
    admin: Account,
    db: Session,
    *,
    action: str = "task.retry",
    reason: str | None = None,
    reset_attempts: bool = True,
) -> dict:
    task.status = "queued"
    task.cancel_requested = False
    task.error_code = None
    task.lease_until = None
    task.next_retry_at = None
    task.heartbeat_at = utcnow()
    if reset_attempts:
        task.attempts = 0
    for step in db.scalars(select(TaskStep).where(TaskStep.task_id == task.id)).all():
        if step.status in ("failed", "running"):
            step.status = "pending"
    meta = {"reason": reason} if reason else None
    write_audit(
        db,
        actor_id=admin.id,
        action=action,
        request=request,
        target_type="task",
        target_id=task.id,
        meta=meta,
    )
    db.commit()
    from ..worker import enqueue_task

    enqueue_task(request.app.state.settings, task.id)
    return {"ok": True, "task_id": task.id, "source": "task", "status": task.status}


@admin_router.get("/tasks/dead-letters", response_model=AdminDeadLettersResponse)
def list_dead_letters(
    request: Request,
    account_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    query = select(Task).where(
        Task.status == "failed", Task.attempts >= settings.task_max_attempts
    )
    if account_id is not None:
        query = query.where(Task.account_id == account_id)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(or_(Task.id.contains(keyword), Task.error_code.contains(keyword)))
    total = _total(db, query)
    rows = db.scalars(
        query.order_by(Task.finished_at.desc())
        .offset(_offset(page, page_size))
        .limit(page_size)
    ).all()
    return {"items": [_task_brief(row) for row in rows], "total": total}


@admin_router.post("/tasks/{task_id}/replay", response_model=AdminTaskReplayResult)
def replay_dead_letter(
    task_id: str,
    payload: AdminTaskReplayRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is None:
        raise ApiError(404, "task_not_found", "任务不存在")
    if not _is_dead_letter(task, request.app.state.settings):
        raise ApiError(409, "task_not_dead_letter", "仅重试耗尽的死信任务可重放")
    return _requeue_failed_task(
        task,
        request,
        admin,
        db,
        action="task.replay",
        reason=payload.reason,
        reset_attempts=payload.reset_attempts,
    )


@admin_router.post(
    "/tasks/dead-letters/replay-batch",
    response_model=AdminTaskReplayBatchResponse,
)
def replay_dead_letters_batch(
    payload: AdminTaskReplayBatchRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    results: list[dict] = []
    succeeded = 0
    for task_id in payload.task_ids:
        task = db.get(Task, task_id)
        if task is None:
            results.append({"task_id": task_id, "ok": False, "code": "task_not_found"})
            continue
        if not _is_dead_letter(task, request.app.state.settings):
            results.append({"task_id": task_id, "ok": False, "code": "task_not_dead_letter"})
            continue
        _requeue_failed_task(
            task,
            request,
            admin,
            db,
            action="task.replay_batch",
            reason=payload.reason,
            reset_attempts=True,
        )
        results.append({"task_id": task_id, "ok": True, "source": "task"})
        succeeded += 1
    write_audit(
        db,
        actor_id=admin.id,
        action="task.replay_batch_summary",
        request=request,
        target_type="task",
        meta={"count": succeeded, "requested": len(payload.task_ids), "reason": payload.reason},
    )
    db.commit()
    return {
        "items": results,
        "succeeded": succeeded,
        "failed": len(payload.task_ids) - succeeded,
    }


@admin_router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: str,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is not None:
        if task.status not in ("failed", "canceled"):
            raise ApiError(409, "task_not_retryable", f"当前状态不可重试：{task.status}")
        return _requeue_failed_task(task, request, admin, db)

    # 写作运行：复用编排侧 resume 语义（重新预占额度、只重跑失败节点），
    # 与用户端 /agent-runs/{id}/resume 保持一致，避免看板重试造成额度/状态漂移。
    from ..agents.store import resume_run
    from ..worker import enqueue_agent_run

    run = db.get(AgentRun, task_id)
    if run is None:
        raise ApiError(404, "task_not_found", "任务不存在")
    if run.status != "failed":
        raise ApiError(409, "task_not_retryable", f"当前状态不可重试：{run.status}")
    resume_run(db, run, approval=False, retry_failed=True)
    write_audit(db, actor_id=admin.id, action="agent_run.retry", request=request,
                target_type="agent_run", target_id=task_id)
    db.commit()
    enqueue_agent_run(request.app.state.settings, run.id)
    return {"ok": True, "task_id": task_id, "source": "agent_run"}


@admin_router.post("/tasks/{task_id}/control")
def control_task(
    task_id: str,
    payload: AdminTaskControlRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """运营统一管控：取消 / 暂停 / 继续 / 重新排队 / 强制终止。

    同时覆盖拆解改编任务（tasks）与写作运行（agent_runs）。协作式动作只置标志，
    需要「立刻停下」的场景用 force_cancel（直接落终态并释放预占）。
    """
    from ..agents.store import cancel_run, force_cancel_run, pause_run, requeue_run, resume_run
    from ..services.tasks import cancel_task, force_cancel_task, requeue_task
    from ..worker import enqueue_agent_run, enqueue_task

    run = db.get(AgentRun, task_id) if payload.source in (None, "agent_run") else None
    task = db.get(Task, task_id) if run is None and payload.source in (None, "task") else None
    if run is None and task is None:
        raise ApiError(404, "task_not_found", "任务不存在")

    reason = payload.reason or {
        "cancel": "已由运营取消",
        "pause": "已由运营暂停",
        "resume": "已由运营继续",
        "requeue": "已由运营重新排队",
        "force_cancel": "已由运营强制终止",
    }[payload.action]
    action = payload.action
    source = "agent_run" if run is not None else "task"

    if run is not None:
        if action == "cancel":
            changed = cancel_run(db, run)
        elif action == "pause":
            changed = pause_run(db, run)
        elif action == "resume":
            # 失败运行等同「重试失败节点」：与看板 retry 语义保持一致
            if run.status not in ("paused", "failed"):
                raise ApiError(409, "invalid_state", f"当前状态不可继续：{run.status}")
            resume_run(db, run, approval=True, retry_failed=True)
            changed = True
        elif action == "requeue":
            changed = requeue_run(db, run)
        else:
            changed = force_cancel_run(db, run, reason=reason)
    else:
        if action == "cancel":
            changed = cancel_task(db, task)
        elif action == "force_cancel":
            changed = force_cancel_task(db, task, reason=reason)
        elif action == "requeue":
            changed = requeue_task(db, task)
        else:
            # 拆解/改编任务没有「暂停/继续」语义，避免造出前端无法展示的中间态
            raise ApiError(409, "unsupported_action", "拆解/改编任务仅支持取消、重新排队与强制终止")

    if not changed:
        raise ApiError(409, "invalid_state", "任务已结束或状态未发生变化")

    write_audit(
        db,
        actor_id=admin.id,
        action=f"{source}.{action}",
        request=request,
        target_type=source,
        target_id=task_id,
        meta={"reason": reason},
    )
    db.commit()

    # 需要重新执行的动作用 RQ 立即投递；投递失败时调度器会兜底重投
    if action in ("resume", "requeue"):
        if run is not None:
            enqueue_agent_run(request.app.state.settings, run.id)
        else:
            enqueue_task(request.app.state.settings, task.id)

    return {
        "ok": True,
        "task_id": task_id,
        "source": source,
        "status": (run.status if run is not None else task.status),
        "action": action,
    }


EVENT_PAGE_LIMIT = 2000

ADMIN_FEED_STATUSES = ("queued", "running", "paused")
TASK_TERMINAL_STATUSES = ("succeeded", "failed", "canceled")


@admin_router.get("/tasks/stream")
def admin_tasks_stream(request: Request, admin: Account = Depends(require_staff)):
    """运营看板聚合变更流：任务状态变化时通知前端重查列表与概览。"""
    frame, headers = sse_context(request)
    database = request.app.state.db

    def _signature() -> tuple[int, str, str]:
        with database.session() as session:
            task_row = session.execute(
                select(
                    func.count(Task.id),
                    func.max(Task.heartbeat_at),
                    func.max(Task.created_at),
                ).where(Task.status.in_(ADMIN_FEED_STATUSES))
            ).one()
            run_row = session.execute(
                select(
                    func.count(AgentRun.id),
                    func.max(AgentRun.updated_at),
                    func.max(AgentRun.created_at),
                ).where(AgentRun.status.in_(ADMIN_FEED_STATUSES))
            ).one()
        stamps = [stamp for stamp in (task_row[1], task_row[2], run_row[1], run_row[2]) if stamp]
        return (
            int(task_row[0] or 0) + int(run_row[0] or 0),
            max((s.isoformat() for s in stamps), default=""),
            f"{task_row[0] or 0}:{run_row[0] or 0}",
        )

    def _stream():
        current = _signature()
        yield f"event: ready\ndata: {frame({'type': 'ready', 'active': current[0]})}\n\n"
        for _ in range(SSE_MAX_TICKS):
            time.sleep(SSE_POLL_SECONDS)
            nxt = _signature()
            if nxt != current:
                current = nxt
                yield f"event: refresh\ndata: {frame({'type': 'refresh', 'active': nxt[0], 'at': time.time()})}\n\n"
        yield f"event: end\ndata: {frame({'type': 'closed', 'since': current[0]})}\n\n"

    return sse_response(_stream(), headers)


@admin_router.get("/tasks/{task_id}/events")
def admin_task_events(
    task_id: str,
    request: Request,
    source: str | None = Query(default=None, pattern="^(task|agent_run)$"),
    since: int = Query(default=0, ge=0),
    admin: Account = Depends(require_staff),
):
    """任务详情增量事件流：替代管理端每 4 秒拉一次详情的轮询。"""
    frame, headers = sse_context(request)
    database = request.app.state.db

    def _stream():
        last = since
        status_seen: str | None = None
        for _ in range(SSE_MAX_TICKS):
            status = "missing"
            resolved_source: str | None = None
            payloads: list[dict] = []
            with database.session() as session:
                if source != "task":
                    run = session.get(AgentRun, task_id)
                    if run is not None:
                        status = run.status
                        resolved_source = "agent_run"
                        rows = session.scalars(
                            select(AgentRunEvent)
                            .where(AgentRunEvent.run_id == run.id, AgentRunEvent.seq > last)
                            .order_by(AgentRunEvent.seq.asc())
                            .limit(200)
                        ).all()
                        payloads = [
                            {
                                "seq": row.seq,
                                "stage": row.stage,
                                "level": row.level,
                                "message": row.message,
                                "at": row.created_at.isoformat() if row.created_at else None,
                            }
                            for row in rows
                        ]
                if resolved_source is None and source != "agent_run":
                    task = session.get(Task, task_id)
                    if task is not None:
                        status = task.status
                        resolved_source = "task"
                        rows = session.scalars(
                            select(TaskEvent)
                            .where(TaskEvent.task_id == task.id, TaskEvent.seq > last)
                            .order_by(TaskEvent.seq.asc())
                            .limit(200)
                        ).all()
                        payloads = [
                            {
                                "seq": row.seq,
                                "stage": "task",
                                "level": row.level,
                                "message": row.message,
                                "at": row.created_at.isoformat() if row.created_at else None,
                            }
                            for row in rows
                        ]
            if status_seen != status:
                status_seen = status
                yield f"event: status\ndata: {frame({'status': status, 'source': resolved_source})}\n\n"
            for item in payloads:
                last = max(last, int(item["seq"]))
                yield f"data: {frame(item)}\n\n"
            if status in TASK_TERMINAL_STATUSES or status == "missing":
                break
            time.sleep(SSE_POLL_SECONDS)
        yield f"event: end\ndata: {frame({'status': 'closed', 'since': last})}\n\n"

    return sse_response(_stream(), headers)


@admin_router.get("/tasks/{task_id}")
def admin_task_detail(
    task_id: str,
    request: Request,
    source: str | None = Query(default=None, pattern="^(task|agent_run)$"),
    since: int = Query(default=0, ge=0),
    admin: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """运营看板任务详情：统一返回任务/写作运行信息与执行过程事件流。

    执行过程事件已完整落库（task_events / agent_run_events），此前只由用户端 SSE 暴露，
    运营后台看不到；这里补齐管理端读取入口，便于排查「章节缺失 / 卡死」等问题。
    `since` 用于日志轮询：只返回该 seq 之后的新事件，前端可增量追加。
    """
    events: list[dict] = []
    detail: dict = {}
    resolved_source: str | None = None
    truncated = False

    if source in (None, "agent_run"):
        run = db.get(AgentRun, task_id)
        if run is not None:
            resolved_source = "agent_run"
            detail = run_to_dict(db, run, storage=request.app.state.storage)
            rows = db.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == run.id, AgentRunEvent.seq > since)
                .order_by(AgentRunEvent.seq.asc())
                .limit(EVENT_PAGE_LIMIT + 1)
            ).all()
            truncated = len(rows) > EVENT_PAGE_LIMIT
            events = [
                {
                    "seq": row.seq,
                    "stage": row.stage,
                    "level": row.level,
                    "message": row.message,
                    "at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows[:EVENT_PAGE_LIMIT]
            ]
    if resolved_source is None and source in (None, "task"):
        task = db.get(Task, task_id)
        if task is not None:
            resolved_source = "task"
            detail = task_to_dict(task)
            steps = db.scalars(
                select(TaskStep)
                .where(TaskStep.task_id == task.id)
                .order_by(TaskStep.updated_at.asc())
            ).all()
            detail["steps"] = [
                {
                    "step_key": row.step_key,
                    "status": row.status,
                    "output_ref": row.output_ref,
                    "meta": row.meta,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in steps
            ]
            rows = db.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task.id, TaskEvent.seq > since)
                .order_by(TaskEvent.seq.asc())
                .limit(EVENT_PAGE_LIMIT + 1)
            ).all()
            truncated = len(rows) > EVENT_PAGE_LIMIT
            events = [
                {
                    "seq": row.seq,
                    "stage": "(task)",
                    "level": row.level,
                    "message": row.message,
                    "at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows[:EVENT_PAGE_LIMIT]
            ]
    if resolved_source is None:
        raise ApiError(404, "task_not_found", "任务不存在")
    max_seq = events[-1]["seq"] if events else since
    return {
        "source": resolved_source,
        "detail": detail,
        "events": events,
        "last_seq": max_seq,
        "truncated": truncated,
    }


@admin_router.get("/tasks", response_model=AdminTasksResponse)
def admin_tasks(
    status: str | None = Query(default=None, max_length=16),
    source: str | None = Query(default=None, pattern="^(task|agent_run)$"),
    account_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=200),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """后台任务记录：合并 tasks 与 agent_runs，支持状态/来源/账号/关键词过滤与分页。

    所有任务（排队、运行、暂停、完成、失败、取消）都按创建时间倒序返回，
    点击任意一条即可通过 /tasks/{id} 查看完整执行日志。
    """
    # 兼容旧调用：早期只传 limit，等价于第一页
    if limit is not None and page_size == 50:
        page_size = limit

    task_query = select(Task)
    run_query = select(AgentRun)
    if status:
        task_query = task_query.where(Task.status == status)
        run_query = run_query.where(AgentRun.status == status)
    if account_id:
        task_query = task_query.where(Task.account_id == account_id)
        run_query = run_query.where(AgentRun.account_id == account_id)
    text = (q or "").strip()
    if text:
        like = f"%{text}%"
        task_filters = [Task.id.ilike(like), Task.type.ilike(like)]
        run_filters = [
            AgentRun.id.ilike(like),
            AgentRun.title.ilike(like),
            AgentRun.mode.ilike(like),
        ]
        if text.isdigit():
            task_filters.append(Task.account_id == int(text))
            run_filters.append(AgentRun.account_id == int(text))
        task_query = task_query.where(or_(*task_filters))
        run_query = run_query.where(or_(*run_filters))

    offset = _offset(page, page_size)
    # 两张表各取「前 offset+page_size 条」后合并排序，再切出当前页，
    # 避免为了分页把全量任务读进内存。
    window = offset + page_size
    total = 0
    items: list[dict] = []
    if source in (None, "task"):
        total += _total(db, task_query)
        items += [
            _task_brief(row)
            for row in db.scalars(
                task_query.order_by(Task.created_at.desc()).limit(window)
            ).all()
        ]
    if source in (None, "agent_run"):
        total += _total(db, run_query)
        items += [
            _agent_run_brief(row)
            for row in db.scalars(
                run_query.order_by(AgentRun.created_at.desc()).limit(window)
            ).all()
        ]
    items.sort(key=lambda row: row["created_at"] or "", reverse=True)
    return {
        "items": items[offset : offset + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---- 告警 / 通知 -------------------------------------------------------------
@admin_router.get("/alerts", response_model=AdminAlertsResponse)
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


def _delivery_meta_summary(d: NotificationDelivery) -> dict:
    """从 delivery.meta 提取可视化摘要：列表页不返回完整 receipts，避免大响应。"""
    meta = d.meta or {}
    receipts = meta.get("receipts") or []
    expired = meta.get("expired") or []
    return {
        "subscribers": meta.get("subscribers"),
        "delivered": meta.get("delivered"),
        "expired_count": len(expired),
        "receipt_count": len(receipts),
        "retry_after_seconds": meta.get("retry_after_seconds"),
        "reason": meta.get("reason"),
    }


def _notification_view(d: NotificationDelivery) -> dict:
    return {
        "id": d.id,
        "account_id": d.account_id,
        "channel": d.channel,
        "recipient": d.recipient,
        "subject": d.subject,
        "template": d.category,
        "status": d.status,
        "attempts": d.attempts,
        "max_attempts": d.max_attempts,
        "last_error": d.last_error,
        "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
        "provider_message_id": d.provider_message_id,
        "meta_summary": _delivery_meta_summary(d),
        "created_at": d.created_at.isoformat(),
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
    }


@admin_router.get("/notifications", response_model=AdminNotificationsResponse)
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
        "items": [_notification_view(d) for d in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@admin_router.get("/notifications/{delivery_id}", response_model=AdminNotificationDetailResponse)
def admin_notification_detail(
    delivery_id: int,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """单条投递详情：返回完整 meta（逐订阅 receipts / expired / retry_after）。"""
    d = db.get(NotificationDelivery, delivery_id)
    if d is None:
        raise ApiError(404, "delivery_not_found", "发送记录不存在")
    return {"delivery": {**_notification_view(d), "meta": d.meta or {}}}


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


@admin_router.post("/notifications/batch", response_model=AdminNotificationBatchResponse)
def admin_send_notification_batch(
    payload: AdminNotificationBatchRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """批量发送：共享 batch_id，逐账号独立 dedupe_key 与投递记录。

    单个账号失败（不存在 / emit 异常）不影响其它账号；所有成功项在同一事务提交，
    失败项记录原因后继续。dedupe_key 带 batch_id，重复提交同一批不会重复发送。
    """
    batch_id = f"batch-{uuid.uuid4()}"
    account_ids = list(dict.fromkeys(payload.account_ids))  # 去重且保序
    results: list[dict] = []
    sent = 0
    for account_id in account_ids:
        if db.get(Account, account_id) is None:
            results.append({
                "account_id": account_id, "notification_id": None,
                "status": "invalid_account", "detail": "账号不存在",
            })
            continue
        try:
            row = nsvc.emit(
                db,
                account_id=account_id,
                category="admin_message",
                dedupe_key=f"admin:{batch_id}",
                context={"title": payload.title, "body": payload.body},
                settings=request.app.state.settings,
                channels=tuple(payload.channels) if payload.channels else None,
            )
            results.append({
                "account_id": account_id,
                "notification_id": row.id if row else None,
                "status": "sent" if row else "skipped",
                "detail": None,
            })
            sent += 1
        except Exception as exc:  # noqa: BLE001 - 单账号失败不影响整批
            logger.warning("批量通知单账号失败 account=%s error=%s", account_id, type(exc).__name__)
            results.append({
                "account_id": account_id, "notification_id": None,
                "status": "skipped", "detail": f"{type(exc).__name__}: {str(exc)[:120]}",
            })
    write_audit(
        db, actor_id=admin.id, action="notification.batch", request=request,
        target_type="notification", target_id=batch_id,
        meta={"batch_id": batch_id, "total": len(account_ids), "sent": sent,
              "channels": payload.channels},
    )
    db.commit()
    return {
        "batch_id": batch_id, "total": len(account_ids), "sent": sent,
        "skipped": len(account_ids) - sent, "results": results,
    }


@admin_router.get("/notifications/{delivery_id}/receipts", response_model=PushReceiptHistoryResponse)
def admin_notification_receipt_history(
    delivery_id: int,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """结构化回执历史：把 delivery.meta 的 receipts 拆成稳定字段，便于跨投递对账。"""
    d = db.get(NotificationDelivery, delivery_id)
    if d is None:
        raise ApiError(404, "delivery_not_found", "发送记录不存在")
    meta = d.meta or {}
    receipts = [
        {
            "sub_id": int(r.get("sub_id") or 0),
            "status": str(r.get("status") or "unknown"),
            "http_status": r.get("http_status"),
            "retry_after_seconds": r.get("retry_after_seconds"),
            "error": redact_error_text(str(r.get("error") or "")),
        }
        for r in (meta.get("receipts") or [])
        if isinstance(r, dict)
    ]
    return {"delivery": {
        "delivery_id": d.id, "channel": d.channel, "status": d.status,
        "attempts": d.attempts,
        "subscribers": int(meta.get("subscribers") or 0),
        "delivered": int(meta.get("delivered") or 0),
        "expired": list(meta.get("expired") or []),
        "receipts": receipts,
        "retry_after_seconds": meta.get("retry_after_seconds"),
        "reason": meta.get("reason"),
        "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
    }}


@admin_router.get("/notifications/{delivery_id}/receipts/export")
def admin_notification_receipts_export(
    delivery_id: int,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """单次投递回执导出 CSV（对账用）：逐订阅一行，含 HTTP 状态/退避/错误。

    error 来自 webpush 异常文本，属不可信外部输入：统一做 CSV 公式注入防护，
    并清理单元格内换行；文件名用 quote 编码，避免 Content-Disposition 头注入。
    """
    d = db.get(NotificationDelivery, delivery_id)
    if d is None:
        raise ApiError(404, "delivery_not_found", "发送记录不存在")
    meta = d.meta or {}

    def cell(value) -> str:
        text = redact_error_text("" if value is None else str(value))
        text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        # Excel 会忽略前置空白：必须先 lstrip 再判首字符，否则 " =CMD" 可绕过防护。
        significant = text.lstrip(" \t")
        return "'" + text if significant and significant[0] in "=+-@" else text

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "delivery_id", "channel", "delivery_status", "sub_id", "status",
        "http_status", "retry_after_seconds", "error",
    ])
    for r in (meta.get("receipts") or []):
        if not isinstance(r, dict):
            continue
        writer.writerow([
            cell(d.id), cell(d.channel), cell(d.status),
            cell(r.get("sub_id") or 0), cell(r.get("status") or "unknown"),
            cell(r.get("http_status")), cell(r.get("retry_after_seconds")), cell(r.get("error")),
        ])
    expired = list(meta.get("expired") or [])
    # 失效订阅单独一行标注，便于后台统计退订率
    for sub_id in expired:
        writer.writerow([
            cell(d.id), cell(d.channel), cell(d.status), cell(sub_id), "expired",
            "", "", "subscription expired / gone (410/404)",
        ])
    write_audit(
        db, actor_id=_admin.id, action="notification.receipts_export", request=request,
        target_type="notification_delivery", target_id=str(d.id),
        meta={"receipts": len(meta.get("receipts") or []), "expired": len(expired)},
    )
    db.commit()
    filename = f"receipts-{d.id}.csv"
    return PlainTextResponse(
        "\ufeff" + buffer.getvalue(),  # UTF-8 BOM 兼容中文 Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=receipts-{d.id}.csv; filename*=UTF-8''{quote(filename)}"},
    )


def _histogram_quantile_ms(buckets: list[int], count: int, quantile: float) -> float | None:
    if count <= 0:
        return None
    target = count * quantile
    cumulative = 0
    for bound, bucket_count in zip(HISTOGRAM_BUCKETS, buckets):
        cumulative += bucket_count
        if cumulative >= target:
            return round(bound * 1000, 1)
    return None


@admin_router.get("/performance", response_model=AdminPerformanceResponse)
def performance(_staff: Account = Depends(require_staff)):
    """进程内 HTTP 延迟快照；多 worker 部署请优先看 Prometheus 聚合。"""
    rows = histogram_snapshot("moxie_http_request_duration_seconds")
    total_buckets = [0] * len(HISTOGRAM_BUCKETS)
    total_count = 0
    total_errors = 0
    by_path: dict[
        str, dict[str, object]
    ] = {}

    for labels, buckets, _total, count in rows:
        path = labels.get("path", "unmatched")
        status = labels.get("status", "")
        entry = by_path.setdefault(
            path,
            {"buckets": [0] * len(HISTOGRAM_BUCKETS), "count": 0, "errors": 0},
        )
        entry_buckets = entry["buckets"]
        assert isinstance(entry_buckets, list)
        for index, bucket_count in enumerate(buckets):
            entry_buckets[index] += bucket_count
            total_buckets[index] += bucket_count
        entry["count"] = int(entry["count"]) + count
        total_count += count
        if status.startswith("5"):
            entry["errors"] = int(entry["errors"]) + count
            total_errors += count

    routes = []
    for path, entry in sorted(
        by_path.items(), key=lambda item: int(item[1]["count"]), reverse=True
    )[:20]:
        buckets = entry["buckets"]
        assert isinstance(buckets, list)
        count = int(entry["count"])
        routes.append(
            {
                "path": path,
                "count": count,
                "p95_ms": _histogram_quantile_ms(buckets, count, 0.95),
                "p99_ms": _histogram_quantile_ms(buckets, count, 0.99),
                "error_rate": round(int(entry["errors"]) / count, 4) if count else 0.0,
            }
        )

    return {
        "generated_at": utcnow().isoformat(),
        "requests": total_count,
        "p95_ms": _histogram_quantile_ms(total_buckets, total_count, 0.95),
        "p99_ms": _histogram_quantile_ms(total_buckets, total_count, 0.99),
        "error_rate": round(total_errors / total_count, 4) if total_count else 0.0,
        "routes": routes,
    }


# ---- 兼容旧看板路径 / 汇总 ----------------------------------------------------
@admin_router.get("/dashboard", response_model=AdminDashboardResponse)
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
    if payload.base_url:
        row.base_url = validate_upstream_base_url(
            payload.base_url,
            allow_private=settings.model_gateway_allow_private_networks,
        )
    else:
        row.base_url = (
            "https://ai-gateway.edgeone.link/v1"
            if payload.provider == "edgeone"
            else settings.llm_base_url
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


@admin_router.delete("/model-configs/{step_key}", response_model=AdminModelConfigDeleteResponse)
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


@admin_router.post("/model-configs/{step_key}/test", response_model=AdminModelConfigTestResponse)
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
    if payload.base_url:
        base_url = validate_upstream_base_url(
            payload.base_url,
            allow_private=settings.model_gateway_allow_private_networks,
        )
    else:
        base_url = (
            "https://ai-gateway.edgeone.link/v1"
            if payload.provider == "edgeone"
            else settings.llm_base_url
        )
    api_key = payload.api_key or ""
    if not api_key:
        stored = db.scalars(select(ModelProviderConfig).where(ModelProviderConfig.step_key == step_key)).one_or_none()
        if stored and stored.api_key:
            api_key = decrypt_key(stored.api_key, settings) or ""
    using_server_key = False
    if not api_key:
        api_key = settings.llm_api_key
        using_server_key = True
    # 服务端全局 Key 只允许发往服务端自己配置的地址：否则管理员可把真实 Key
    # 引流到任意外部域名（即便地址通过了 SSRF 校验）。
    if using_server_key and payload.base_url:
        if base_url.rstrip("/") != (settings.llm_base_url or "").rstrip("/"):
            raise ApiError(
                422,
                "server_key_base_url_mismatch",
                "使用服务端 Key 时不允许自定义 base_url，请显式提供 api_key",
            )
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


@admin_router.get("/offline-packages", response_model=list[OfflinePackageView])
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


@admin_router.get("/offline-packages/limits", response_model=OfflinePackageLimitsResponse)
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


@admin_router.post("/offline-packages", response_model=OfflinePackageView)
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
    platform = (platform or "").strip()
    version = (version or "").strip()
    release_notes = (release_notes or "").strip()
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
    # 先 flush 取得自增主键：否则下面的 `id != pkg.id` 与审计 target_id
    # 拿到的都是 None（`IS NOT NULL` 会把刚上传的包也置为非当前）。
    db.flush()
    # 同平台历史版本置为非当前
    db.execute(
        update(OfflinePackage)
        .where(OfflinePackage.platform == platform, OfflinePackage.id != pkg.id)
        .values(is_active=False)
    )
    write_audit(
        db, actor_id=_admin.id, action="offline_package.upload", request=request,
        target_type="offline_package", target_id=str(pkg.id),
        meta={"platform": platform, "version": version_val, "size": reader.n, "filename": safe},
    )
    db.commit()
    db.refresh(pkg)
    return _offline_view(pkg, settings)


@admin_router.delete("/offline-packages/{pkg_id}", response_model=OfflinePackageDeleteResponse)
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


# ---- 统一预设值维护（题材 / 枚举 / 分类 / 标签） -------------------------------
def _preset_view(row: Preset) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "value": row.value,
        "label": row.label or row.value,
        "audience": row.audience or "all",
        "sort": row.sort,
        "builtin": row.builtin,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        # 用户自定义预设（account_id 非 NULL）此前被维护列表过滤掉，导致
        # 管理端看到的列表与前端实际可选数据不一致。这里显式带上归属信息。
        "custom": row.account_id is not None,
        "account_id": row.account_id,
    }


def _assert_preset_value(value: str) -> None:
    """拒绝控制字符等非法的预设值，避免脏数据进入前端选项。"""
    if not value or any(ord(ch) < 32 for ch in value):
        raise ApiError(422, "invalid_preset", "预设值不能为空或包含控制字符")


def _preset_duplicate(
    db: Session,
    ptype: str,
    value: str,
    exclude_id: int | None = None,
    account_id: int | None = None,
) -> bool:
    """按归属范围查重：account_id=None 表示系统级；否则限定该用户的自定义项。

    唯一约束是 (type, value, account_id)，不同用户可同名、系统项与用户项也可同名，
    因此查重必须与待写入行的 account_id 一致，否则会把用户自定义项误判为重复。
    """
    conditions = [
        Preset.type == ptype,
        Preset.value == value,
        Preset.account_id.is_(None) if account_id is None else Preset.account_id == account_id,
    ]
    if exclude_id is not None:
        conditions.append(Preset.id != exclude_id)
    return db.scalar(select(Preset.id).where(*conditions).limit(1)) is not None


def _preset_scope_condition(scope: str):
    """维护列表的可见范围：all=全部，system=仅系统级，custom=仅用户自定义项。"""
    if scope == "system":
        return Preset.account_id.is_(None)
    if scope == "custom":
        return Preset.account_id.is_not(None)
    return None


@admin_router.get("/presets", response_model=AdminPresetListResponse)
def admin_list_presets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    type: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=128),
    scope: str = Query(default="all", pattern=r"^(all|system|custom)$"),
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """分页查询预设值。默认全部（系统级 + 用户自定义），与前端 GET /v1/presets
    的数据口径一致；scope 可切到 system / custom。type 精确筛选，q 模糊匹配值/标签。
    """
    conditions = []
    scope_condition = _preset_scope_condition(scope)
    if scope_condition is not None:
        conditions.append(scope_condition)
    if type and type.strip():
        conditions.append(Preset.type == type.strip())
    keyword = q.strip() if q else ""
    if keyword:
        # like 的模式串作为绑定参数传入，不拼接 SQL；转义通配符避免误匹配
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.append(or_(Preset.value.like(pattern, escape="\\"), Preset.label.like(pattern, escape="\\")))
    stmt = select(Preset).where(*conditions) if conditions else select(Preset)
    total = _total(db, stmt)
    rows = db.scalars(
        stmt.order_by(Preset.type, Preset.sort, Preset.value)
        .offset(_offset(page, page_size))
        .limit(page_size)
    ).all()
    type_stmt = select(Preset.type).distinct()
    if scope_condition is not None:
        type_stmt = type_stmt.where(scope_condition)
    types = list(db.scalars(type_stmt.order_by(Preset.type)).all())
    return {
        "items": [_preset_view(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "types": types,
        "scope": scope,
    }


@admin_router.post("/presets", status_code=201, response_model=AdminPresetView)
def admin_create_preset(
    payload: AdminPresetUpsert,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """新增系统级预设值；builtin=False 表示由后台维护而非程序种子。"""
    _assert_preset_value(payload.value)
    if _preset_duplicate(db, payload.type, payload.value):
        raise ApiError(409, "preset_exists", "该类型下已存在同名预设值")
    row = Preset(
        type=payload.type,
        value=payload.value,
        label=payload.label or payload.value,
        audience=payload.audience or "all",
        sort=payload.sort,
        builtin=False,
        account_id=None,
    )
    db.add(row)
    write_audit(
        db, actor_id=_admin.id, action="preset.create", request=request,
        target_type="preset", target_id=payload.type,
        meta={"type": payload.type, "value": payload.value},
    )
    db.commit()
    db.refresh(row)
    return _preset_view(row)


@admin_router.put("/presets/{preset_id}", response_model=AdminPresetView)
def admin_update_preset(
    preset_id: int,
    payload: AdminPresetUpsert,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """修改预设值（系统级或用户自定义项均可维护），归属 account_id 保持不变。"""
    row = db.get(Preset, preset_id)
    if row is None:
        raise ApiError(404, "not_found", "预设不存在")
    _assert_preset_value(payload.value)
    if _preset_duplicate(
        db, payload.type, payload.value, exclude_id=preset_id, account_id=row.account_id
    ):
        raise ApiError(409, "preset_exists", "该类型下已存在同名预设值")
    before = _preset_view(row)
    row.type = payload.type
    row.value = payload.value
    row.label = payload.label or payload.value
    row.audience = payload.audience or "all"
    row.sort = payload.sort
    write_audit(
        db, actor_id=_admin.id, action="preset.update", request=request,
        target_type="preset", target_id=payload.type,
        meta={"before": before, "after": _preset_view(row)},
    )
    db.commit()
    db.refresh(row)
    return _preset_view(row)


@admin_router.delete("/presets/{preset_id}", response_model=AdminPresetDeleteResponse)
def admin_delete_preset(
    preset_id: int,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """硬删除预设值（含用户自定义项）。系统级内置项删除后不会被种子自动复活。"""
    row = db.get(Preset, preset_id)
    if row is None:
        raise ApiError(404, "not_found", "预设不存在")
    snapshot = _preset_view(row)
    db.delete(row)
    write_audit(
        db, actor_id=_admin.id, action="preset.delete", request=request,
        target_type="preset", target_id=row.type, meta=snapshot,
    )
    db.commit()
    return {"deleted": True, "id": preset_id}


@admin_router.post("/presets/sync-seeds", response_model=AdminPresetSyncResponse)
def admin_sync_preset_seeds(
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """按程序内置清单补齐缺失预设（只插入，不覆盖已有、不删除），用于版本升级后补数据。"""
    result = seed_presets(db, only_if_empty=False)
    write_audit(
        db, actor_id=_admin.id, action="preset.sync_seeds", request=request,
        target_type="preset", target_id="seeds", meta=result,
    )
    db.commit()
    return {"synced": True, **result}


@admin_router.get("/telemetry-config")
def get_telemetry_config_settings(
    request: Request,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
) -> TelemetryConfigView:
    """查看当前生效的前端错误上报策略（DB 覆盖优先于环境变量）。"""
    cfg = runtime_config.get_telemetry_config(db, request.app.state.settings)
    return TelemetryConfigView(**cfg)


@admin_router.put("/telemetry-config")
def update_telemetry_config_settings(
    payload: TelemetryConfigUpdate,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TelemetryConfigView:
    """热改采样率/去重窗口/zset 容量：写库后本进程立即生效，其它 worker TTL 内收敛。"""
    settings = request.app.state.settings
    runtime_config.set_telemetry_config(
        db,
        settings,
        _admin.id,
        sample_rate=payload.sample_rate,
        dedupe_window_seconds=payload.dedupe_window_seconds,
        dedupe_max_entries=payload.dedupe_max_entries,
        canary_percent=payload.canary_percent,
        canary=payload.canary.model_dump(exclude_none=True) if payload.canary else {},
    )
    write_audit(
        db, actor_id=_admin.id, action="telemetry_config.update", request=request,
        target_type="operational_setting", target_id="telemetry",
        meta={
            "sample_rate": payload.sample_rate,
            "dedupe_window_seconds": payload.dedupe_window_seconds,
            "dedupe_max_entries": payload.dedupe_max_entries,
            "canary_percent": payload.canary_percent,
            "canary": payload.canary.model_dump(exclude_none=True) if payload.canary else {},
        },
    )
    db.commit()
    return TelemetryConfigView(**runtime_config.get_telemetry_config(db, settings))


# —— 运维：数据库备份 / 恢复 ——
def _backup_view(item: dict) -> dict:
    email = item.get("email") if isinstance(item.get("email"), dict) else {}
    return {
        "id": item.get("id", ""),
        "created_at": item.get("created_at"),
        "trigger": item.get("trigger", "manual"),
        "engine": item.get("engine", "sqlite"),
        "size_bytes": int(item.get("size_bytes") or 0),
        "checksum": item.get("checksum", ""),
        # 收件地址属运营凭据：只披露发送状态，不在列表/创建响应中回显。
        "email": {
            "enabled": bool(email.get("enabled", False)),
            "status": str(email.get("status", "unknown")),
            "reason": email.get("reason"),
            "error": email.get("error"),
        },
    }


@admin_router.get("/backup-config", response_model=BackupConfigView)
def get_backup_config_settings(
    request: Request,
    _staff: Account = Depends(require_staff),
    db: Session = Depends(get_db),
) -> BackupConfigView:
    """查看当前生效的定时备份策略（DB 覆盖优先于环境变量）。"""
    cfg = runtime_config.get_backup_config(db, request.app.state.settings)
    return BackupConfigView(**cfg)


@admin_router.put("/backup-config", response_model=BackupConfigView)
def update_backup_config_settings(
    payload: BackupConfigUpdate,
    request: Request,
    _admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BackupConfigView:
    """热改定时备份开关/间隔/通知邮箱/保留份数：写库后本进程立即生效。"""
    settings = request.app.state.settings
    runtime_config.set_backup_config(
        db,
        settings,
        _admin.id,
        schedule_enabled=payload.schedule_enabled,
        interval_minutes=payload.interval_minutes,
        email_enabled=payload.email_enabled,
        notify_emails=payload.notify_emails,
        retention_count=payload.retention_count,
    )
    write_audit(
        db, actor_id=_admin.id, action="backup_config.update", request=request,
        target_type="operational_setting", target_id="backup",
        meta={
            "schedule_enabled": payload.schedule_enabled,
            "interval_minutes": payload.interval_minutes,
            "email_enabled": payload.email_enabled,
            "notify_emails": payload.notify_emails,
            "retention_count": payload.retention_count,
        },
    )
    db.commit()
    return BackupConfigView(**runtime_config.get_backup_config(db, settings))


@admin_router.get("/backups", response_model=BackupListView)
def admin_list_backups(request: Request, admin: Account = Depends(require_staff)):
    settings = request.app.state.settings
    return {"items": [_backup_view(item) for item in backupsvc.list_backups(settings)]}


@admin_router.post("/backups", status_code=201, response_model=BackupCreateResponse)
def admin_create_backup(
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    manifest = backupsvc.create_backup(settings, trigger="manual", db=db)
    view = _backup_view(manifest)
    write_audit(
        db, actor_id=admin.id, action="db.backup.created", request=request,
        target_type="backup", target_id=manifest["id"],
        meta={"engine": manifest["engine"], "trigger": "manual", "size_bytes": manifest["size_bytes"]},
    )
    db.commit()
    return {"item": view}


@admin_router.get("/backups/{backup_id}/download")
def admin_download_backup(
    backup_id: str,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    filename, content = backupsvc.download_backup(request.app.state.settings, backup_id)
    write_audit(
        db, actor_id=admin.id, action="db.backup.downloaded", request=request,
        target_type="backup", target_id=backup_id,
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@admin_router.post("/backups/{backup_id}/restore", response_model=BackupRestoreResponse)
def admin_restore_backup(
    backup_id: str,
    payload: BackupRestoreRequest,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.apply and payload.confirm != "RESTORE":
        raise ApiError(422, "restore_confirmation_required", "破坏性恢复必须输入 RESTORE 确认")
    write_audit(
        db, actor_id=admin.id, action="db.restore.requested", request=request,
        target_type="backup", target_id=backup_id,
        meta={"apply": payload.apply, "confirm": "RESTORE" if payload.apply else ""},
    )
    db.commit()
    result = backupsvc.restore_backup(
        request.app.state.settings, backup_id, apply=payload.apply, db=request.app.state.db
    )
    if payload.apply:
        # 覆盖恢复会替换当前库，上面的「请求」审计随旧库一起消失；成功后重写一条落在新库。
        with request.app.state.db.session() as audit_db:
            write_audit(
                audit_db, actor_id=admin.id, action="db.restore.applied", request=request,
                target_type="backup", target_id=backup_id,
                meta={"mode": result["mode"], "engine": result["engine"]},
            )
            audit_db.commit()
    return BackupRestoreResponse(**result)


@admin_router.delete("/backups/{backup_id}", response_model=BackupDeleteResponse)
def admin_delete_backup(
    backup_id: str,
    request: Request,
    admin: Account = Depends(require_admin),
    db: Session = Depends(get_db),
):
    result = backupsvc.delete_backup(request.app.state.settings, backup_id)
    write_audit(
        db, actor_id=admin.id, action="db.backup.deleted", request=request,
        target_type="backup", target_id=backup_id,
    )
    db.commit()
    return BackupDeleteResponse(**result)


@admin_router.get("/usage/models", response_model=ModelUsageResponse)
def admin_model_usage(
    days: int = Query(default=30, ge=1, le=366),
    group_by: str = Query(default="model", pattern="^(model|provider|account|day)$"),
    provider: str = Query(default=""),
    model: str = Query(default=""),
    route: str = Query(default=""),
    account_id: int | None = Query(default=None, ge=1),
    admin: Account = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """AI 模型消费统计：按模型 / 供应商 / 账户 / 日期聚合 usage_events。"""
    return usage_stats.model_usage(
        db,
        days=days,
        group_by=group_by,
        provider=provider,
        model=model,
        route=route,
        account_id=account_id,
    )
