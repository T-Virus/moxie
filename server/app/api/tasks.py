# -*- coding: utf-8 -*-
"""任务接口：创建（幂等）、状态、日志轮询、取消。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import TaskEvent
from ..runners.decompose import validate_source_params
from ..schemas import (
    CancelTaskRequest,
    CancelTaskResponse,
    CreateTaskResponse,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskLogsResponse,
)
from ..services.audit import write_audit
from ..services.compliance import enforce_rights_declaration
from ..services.tasks import cancel_task, create_task, get_task, task_to_dict
from ..worker import enqueue_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201, response_model=CreateTaskResponse)
def create(
    payload: TaskCreateRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    params = dict(payload.params or {})
    rights_summary: dict = {"rights_confirmed": False, "consent_recorded": False}
    if settings.legal_gate_enabled and payload.type in ("decompose", "adapt"):
        # 结构化声明走 body（params.rights_declaration，受 payload 加密保护）；
        # 旧的 params.rights_confirmed / 明文头仅作兼容回退，来源会写入审计。
        from ..schemas import RightsDeclaration

        declaration = None
        raw_decl = params.get("rights_declaration")
        if isinstance(raw_decl, dict):
            try:
                declaration = RightsDeclaration.model_validate(raw_decl)
            except Exception as exc:  # noqa: BLE001 - pydantic ValidationError
                raise ApiError(
                    422,
                    "rights_declaration_invalid",
                    "权利声明字段无效：basis 须为 own/authorized/public_domain，且须确认并知悉 AIGC 标注义务",
                ) from exc
        legacy = bool(params.get("rights_confirmed")) or (
            request.headers.get("x-rights-confirmed", "").lower() in ("1", "true", "yes")
        )
        if declaration is None and not legacy:
            raise ApiError(
                422,
                "rights_confirmation_required",
                "创建拆解/改编任务前必须声明作品权利来源并确认 AIGC 标注义务",
            )
        # 用统一服务落 LegalConsent + 审计（无声明时按明文头回退留痕）
        rights_summary = enforce_rights_declaration(
            db,
            request=request,
            account_id=auth.account.id,
            settings=settings,
            declaration=declaration,
            source_key=str(params.get("source_key") or "") or None,
            action="task.rights_consent",
            legacy_confirmed=bool(params.get("rights_confirmed")),
        )
        params["rights_confirmed"] = True
        params.setdefault("aigc_label", True)
        params.setdefault("rights_confirmed_at", utcnow().isoformat())
    if "source_path" in params or "source_key" in params:
        validate_source_params(
            settings,
            params,
            request.app.state.storage,
            account_id=auth.account.id,
            db=db,
        )
    idempotency_key = request.headers.get("idempotency-key") or payload.idempotency_key
    task, created = create_task(
        db,
        account_id=auth.account.id,
        task_type=payload.type,
        params=params,
        input_artifact=payload.input_artifact,
        book_id=payload.book_id,
        idempotency_key=idempotency_key,
    )
    if created:
        write_audit(db, actor_id=auth.account.id, action="task.create", request=request,
                    target_type="task", target_id=task.id,
                    meta={"type": payload.type, "metric": task.reserved_metric,
                          "quantity": task.reserved_quantity,
                          "rights": rights_summary})
    db.commit()
    db.refresh(task)

    # BYOK 只写 Redis（短期），不落库、不写日志；worker 从 Redis 取用
    byok = (request.headers.get("x-byok-key") or "").strip()
    if byok:
        try:
            request.app.state.redis.setex(f"task:byok:{task.id}", 3600, byok)
        except Exception:  # noqa: BLE001
            pass

    queued = False
    if created:
        queued = enqueue_task(settings, task.id)
    response.status_code = 201 if created else 200
    return {"task": task_to_dict(task), "created": created, "enqueued": queued}


@router.get("/{task_id}", response_model=TaskDetailResponse)
def detail(task_id: str, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    task = get_task(db, auth.account.id, task_id)
    return {"task": task_to_dict(task)}


@router.get("/{task_id}/logs", response_model=TaskLogsResponse)
def logs(
    task_id: str,
    after: int = Query(default=0, ge=0, description="只返回 seq > after 的事件"),
    limit: int = Query(default=200, ge=1, le=1000),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    get_task(db, auth.account.id, task_id)
    rows = db.scalars(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id, TaskEvent.seq > after)
        .order_by(TaskEvent.seq.asc())
        .limit(limit)
    ).all()
    next_seq = rows[-1].seq if rows else after
    return {
        "events": [
            {
                "seq": row.seq,
                "level": row.level,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "next_seq": next_seq,
    }


@router.post("/{task_id}/cancel", response_model=CancelTaskResponse)
def cancel(
    task_id: str,
    request: Request,
    payload: CancelTaskRequest | None = None,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    task = get_task(db, auth.account.id, task_id)
    changed = cancel_task(db, task)
    if changed:
        write_audit(db, actor_id=auth.account.id, action="task.cancel", request=request,
                    target_type="task", target_id=task.id,
                    meta={"reason": (payload.reason if payload else None)})
        # 给 worker 一个快速检查点（DB 标志仍是权威）
        try:
            request.app.state.redis.setex(f"task:cancel:{task.id}", 3600, "1")
        except Exception:  # noqa: BLE001
            pass
    db.commit()
    db.refresh(task)
    return {"task": task_to_dict(task), "changed": changed}
