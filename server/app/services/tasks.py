# -*- coding: utf-8 -*-
"""任务编排：创建、幂等、预占、执行、取消、日志。

三层幂等：
  1. (account_id, idempotency_key) 唯一 → 重复创建返回同一个任务；
  2. task_steps (task_id, step_key) 主键 → 重跑跳过已完成步骤；
  3. usage_events (account_id, idempotency_key) 唯一 → 重放不重复扣额度。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import AuditLog, Task, TaskEvent, TaskStep
from ..prompts import ADAPT_PROMPT_VERSION, PROMPT_VERSION, REVIEW_PROMPT_VERSION
from .quota import QuotaService, period_of

logger = logging.getLogger("moxie.tasks")

TASK_TYPES = {"decompose", "adapt", "review"}
METRIC_BY_TYPE = {
    "decompose": "books_month",
    "adapt": "adapt_chapters",
    "review": "review_month",
}


class TaskCanceled(Exception):
    pass


class TaskReschedule(Exception):
    """主动让出 worker（分批执行/租约到期重排），保留预占与已完成步骤。"""


def quota_quantity(task_type: str, params: dict) -> int:
    if task_type == "adapt":
        raw = params.get("chapters", 1)
        try:
            quantity = int(raw)
        except (TypeError, ValueError):
            raise ApiError(422, "invalid_chapters", "params.chapters 必须是大于 0 的整数")
        if quantity <= 0:
            raise ApiError(422, "invalid_chapters", "params.chapters 必须大于 0")
        return quantity
    return 1


def append_event(
    session: Session, task_id: str, message: str, *, level: str = "info", seq: int | None = None
) -> int:
    if seq is None:
        current = session.scalar(select(func.max(TaskEvent.seq)).where(TaskEvent.task_id == task_id)) or 0
        seq = current + 1
    session.add(TaskEvent(task_id=task_id, seq=seq, level=level, message=message[:2000]))
    session.flush()
    return seq


def get_task(session: Session, account_id: int, task_id: str) -> Task:
    task = session.scalar(select(Task).where(Task.id == task_id, Task.account_id == account_id))
    if task is None:
        raise ApiError(404, "task_not_found", "任务不存在")
    return task


def create_task(
    session: Session,
    *,
    account_id: int,
    task_type: str,
    params: dict,
    input_artifact: str | None,
    book_id: int | None,
    idempotency_key: str | None,
    now: datetime | None = None,
) -> tuple[Task, bool]:
    """返回 (task, created)。重复幂等键直接返回已有任务。"""
    if task_type not in TASK_TYPES:
        raise ApiError(422, "invalid_task_type", f"不支持的任务类型：{task_type}")
    params = params or {}
    # 密钥只能走请求头/内存，禁止进入任务参数（会落库并出现在任务详情里）
    for banned in ("byok_key", "api_key", "authorization", "x-byok-key"):
        if banned in params:
            raise ApiError(422, "secret_in_params_forbidden", "请通过 X-BYOK-Key 请求头传递密钥")
    now = now or utcnow()
    key = idempotency_key or f"auto:{uuid.uuid4()}"

    existing = session.scalar(
        select(Task).where(Task.account_id == account_id, Task.idempotency_key == key)
    )
    if existing is not None:
        return existing, False

    metric = METRIC_BY_TYPE[task_type]
    quantity = quota_quantity(task_type, params)
    reservation = QuotaService(session).reserve(account_id, metric, quantity, now=now)

    task = Task(
        id=str(uuid.uuid4()),
        account_id=account_id,
        book_id=book_id,
        type=task_type,
        status="queued",
        params=params or {},
        input_artifact=input_artifact,
        idempotency_key=key,
        reserved_metric=metric,
        reserved_quantity=reservation.quantity,
        reserved_plan_quantity=reservation.plan_quantity,
        reserved_pack_items=[dict(item) for item in reservation.pack_items],
        progress=0,
        prompt_version={
            "decompose": PROMPT_VERSION,
            "adapt": ADAPT_PROMPT_VERSION,
            "review": REVIEW_PROMPT_VERSION,
        }[task_type],
        created_at=now,
    )
    session.add(task)
    try:
        session.flush()
    except IntegrityError:
        # 并发同 key：回滚本次预占，返回已有任务
        session.rollback()
        existing = session.scalar(
            select(Task).where(Task.account_id == account_id, Task.idempotency_key == key)
        )
        if existing is None:
            raise
        return existing, False

    append_event(session, task.id, f"任务已创建：{task_type}，预占 {metric}={quantity}")
    return task, True


def task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "type": task.type,
        "status": task.status,
        "book_id": task.book_id,
        "progress": task.progress,
        "params": task.params,
        "input_artifact": task.input_artifact,
        "output_artifact": task.output_artifact,
        "error_code": task.error_code,
        "cancel_requested": task.cancel_requested,
        "attempts": task.attempts,
        "prompt_version": task.prompt_version,
        "cost_estimate_cents": task.cost_estimate_cents,
        "cost_actual_cents": task.cost_actual_cents,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


class RunContext:
    """注入给 runner 的上下文：日志、步骤、进度、协作式取消检查。"""

    def __init__(
        self,
        session: Session,
        task: Task,
        *,
        settings: Settings | None = None,
        storage=None,
        byok_key: str | None = None,
    ):
        self.session = session
        self.task = task
        self.settings = settings
        self.storage = storage
        self.byok_key = byok_key
        self._seq = (
            session.scalar(select(func.max(TaskEvent.seq)).where(TaskEvent.task_id == task.id)) or 0
        )

    def log(self, message: str, level: str = "info") -> int:
        self._seq += 1
        return append_event(self.session, self.task.id, message, level=level, seq=self._seq)

    def progress(self, pct: int) -> None:
        self.task.progress = max(0, min(int(pct), 99))
        self.session.flush()

    def get_step(self, step_key: str) -> TaskStep | None:
        return self.session.get(TaskStep, (self.task.id, step_key))

    def step(
        self, step_key: str, *, output_ref: str | None = None, meta: dict | None = None, status: str = "done"
    ) -> None:
        row = self.session.get(TaskStep, (self.task.id, step_key))
        if row is not None and row.status == "done":
            return  # 断点续跑：跳过已完成步骤
        if row is None:
            self.session.add(
                TaskStep(
                    task_id=self.task.id,
                    step_key=step_key,
                    status=status,
                    output_ref=output_ref,
                    meta=meta or {},
                )
            )
        else:
            row.status = status
            row.output_ref = output_ref
            row.meta = meta or row.meta or {}
            row.updated_at = utcnow()
        self.session.flush()

    def check_cancel(self) -> None:
        # 取消请求可能来自另一个请求/进程，必须刷新数据库行
        self.session.refresh(self.task)
        if self.task.cancel_requested:
            raise TaskCanceled()


class TaskRunner(Protocol):
    def run(self, ctx: RunContext) -> str | None:
        """返回产物引用（可为 None）。抛 TaskCanceled 表示协作式取消。"""


class DefaultRunner:
    """骨架实现：按步骤推进；接入真实拆解/改编时替换这里的 runner。"""

    def __init__(self, steps: int = 3):
        self.steps = max(1, steps)

    def run(self, ctx: RunContext) -> str | None:
        for index in range(self.steps):
            ctx.check_cancel()
            ctx.step(f"chunk:{index + 1:02d}")
            ctx.progress(int((index + 1) * 100 / (self.steps + 1)))
            ctx.log(f"完成步骤 chunk:{index + 1:02d}")
        return f"noop://tasks/{ctx.task.id}/output.json"


_RUNNERS: dict[str, TaskRunner] = {
    "decompose": DefaultRunner(4),
    "adapt": DefaultRunner(3),
    "review": DefaultRunner(2),
}


def register_runner(task_type: str, runner: TaskRunner) -> None:
    _RUNNERS[task_type] = runner


def get_runner(task_type: str) -> TaskRunner:
    runner = _RUNNERS.get(task_type)
    if runner is None:
        raise ApiError(422, "invalid_task_type", f"没有可用的执行器：{task_type}")
    return runner


def _reservation_of(session: Session, task: Task):
    from .quota import Reservation
    from . import subscription as subsvc

    start, end = period_of(task.created_at)
    metric = task.reserved_metric or METRIC_BY_TYPE[task.type]
    unit = "count"
    sub = subsvc.get_active_subscription(session, task.account_id)
    if sub is not None:
        ent = subsvc.get_entitlements(session, sub.plan_id).get(metric)
        if ent is not None:
            unit = ent.unit
    return Reservation(
        account_id=task.account_id,
        metric=metric,
        quantity=task.reserved_quantity,
        period_start=start,
        period_end=end,
        unit=unit,
        plan_quantity=int(task.reserved_plan_quantity or 0),
        pack_items=tuple(dict(item) for item in (task.reserved_pack_items or [])),
    )


def execute_task(
    session: Session,
    task: Task,
    runner: TaskRunner | None = None,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    storage=None,
    byok_key: str | None = None,
) -> str:
    """执行任务并落地最终状态；返回最终状态。调用方负责 commit。"""
    if task.status in ("succeeded", "failed", "canceled"):
        return task.status
    now = now or utcnow()
    if task.cancel_requested:
        task.status = "canceled"
        task.error_code = "canceled"
        task.lease_until = None
        task.finished_at = now
        task.heartbeat_at = now
        QuotaService(session).release(_reservation_of(session, task), now=now)
        append_event(session, task.id, "任务在开始前已取消", level="warning")
        from ..metrics import increment

        increment("moxie_tasks_total", status="canceled")
        session.flush()
        return task.status

    # 原子认领：只有 queued 才能被领取；重复投递/并发执行时这里直接跳过，避免双跑
    claimed = session.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == "queued")
        .values(status="running", attempts=Task.attempts + 1)
    )
    if claimed.rowcount != 1:
        session.expire(task)
        append_event(session, task.id, "任务已被其它 worker 认领，跳过本次重复执行", level="warning")
        session.flush()
        return task.status
    session.expire(task)
    if task.started_at is None:
        task.started_at = now
    task.lease_until = now + timedelta(
        seconds=(settings.task_lease_seconds if settings else 1800)
    )
    task.heartbeat_at = now
    session.flush()
    append_event(session, task.id, f"任务开始执行（第 {task.attempts} 次尝试）")

    ctx = RunContext(session, task, settings=settings, storage=storage, byok_key=byok_key)
    quota = QuotaService(session)
    reservation = _reservation_of(session, task)
    runner = runner or get_runner(task.type)

    try:
        output_ref = runner.run(ctx)
    except TaskReschedule:
        # 分批执行/主动让出：保留预占与已完成步骤，回到队列等待下次执行
        task.status = "queued"
        task.error_code = None
        task.lease_until = None
        task.heartbeat_at = utcnow()
        append_event(session, task.id, "本次执行到达批量上限，任务重新排队（已完成段保留）", level="warning")
        session.flush()
        return task.status
    except TaskCanceled:
        task.status = "canceled"
        task.error_code = "canceled"
        append_event(session, task.id, "任务已取消（协作式检查点）", level="warning")
        quota.release(reservation, now=now)
    except Exception:  # noqa: BLE001
        task.status = "failed"
        task.error_code = "task_failed"
        append_event(session, task.id, "任务执行失败（内部错误，详情见服务端日志）", level="error")
        logger.exception("task failed task_id=%s", task.id)
        quota.release(reservation, now=now)
    else:
        if output_ref:
            task.output_artifact = output_ref
        task.status = "succeeded"
        task.progress = 100
        task.error_code = None
        quota.commit(
            reservation,
            idempotency_key=f"task:{task.id}:{reservation.metric}",
            task_id=task.id,
            meta={"type": task.type},
            now=now,
        )
        append_event(session, task.id, "任务完成，额度已结算")

    task.finished_at = utcnow()
    task.lease_until = None
    task.heartbeat_at = task.finished_at
    from ..metrics import increment

    increment("moxie_tasks_total", status=task.status)
    if task.status == "succeeded":
        meta = {
            "type": task.type,
            "prompt_version": task.prompt_version,
            "cost_actual_cents": task.cost_actual_cents,
            "duration_seconds": int((task.finished_at - task.started_at).total_seconds())
            if task.started_at
            else None,
            "output_artifact": task.output_artifact,
        }
        session.add(
            AuditLog(
                actor_id=task.account_id,
                action="task.execute",
                target_type="task",
                target_id=task.id,
                ip=None,
                ua=None,
                meta=meta,
            )
        )
    session.flush()
    return task.status


# 真实拆解/改编/审查执行器延迟注册，避免 app.prompts/src 在 API 进程导入
from ..runners.adapt import AdaptRunner  # noqa: E402
from ..runners.decompose import DecomposeRunner  # noqa: E402
from ..runners.review import ReviewRunner  # noqa: E402

_RUNNERS["decompose"] = DecomposeRunner()
_RUNNERS["adapt"] = AdaptRunner()
_RUNNERS["review"] = ReviewRunner()


def cancel_task(session: Session, task: Task, *, now: datetime | None = None) -> bool:
    """返回 True 表示状态有变化。queued 立即取消并释放预占；running 只置协作式标志。"""
    now = now or utcnow()
    if task.status in ("succeeded", "failed", "canceled"):
        return False

    if task.status == "queued":
        task.status = "canceled"
        task.cancel_requested = True
        task.finished_at = now
        task.error_code = "canceled"
        QuotaService(session).release(_reservation_of(session, task), now=now)
        append_event(session, task.id, "任务在排队阶段被取消，已释放预占额度", level="warning")
    else:
        task.cancel_requested = True
        append_event(session, task.id, "已请求取消，等待执行器在检查点停止", level="warning")
    session.flush()
    return True
