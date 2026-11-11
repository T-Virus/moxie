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
from ..schemas import CancelTaskRequest, TaskCreateRequest
from ..services.audit import write_audit
from ..services.tasks import cancel_task, create_task, get_task, task_to_dict
from ..worker import enqueue_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", status_code=201)
def create(
    payload: TaskCreateRequest,
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    params = dict(payload.params or {})
    if settings.legal_gate_enabled and payload.type in ("decompose", "adapt"):
        confirmed = bool(params.get("rights_confirmed")) or (
            request.headers.get("x-rights-confirmed", "").lower() in ("1", "true", "yes")
        )
        if not confirmed:
            raise ApiError(
                422,
                "rights_confirmation_required",
                "创建拆解/改编任务前必须确认已获得参考作品使用权，并声明 AIGC 标注方式"
                "（params.rights_confirmed=true）",
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
                          "rights_confirmed": bool(params.get("rights_confirmed"))})
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


@router.get("/{task_id}")
def detail(task_id: str, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    task = get_task(db, auth.account.id, task_id)
    return {"task": task_to_dict(task)}


@router.get("/{task_id}/logs")
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


@router.post("/{task_id}/cancel")
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
