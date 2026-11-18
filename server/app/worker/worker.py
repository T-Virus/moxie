# -*- coding: utf-8 -*-
"""Worker 入口。

生产（有 Redis）：
    rq worker moxie --url redis://redis:6379/0
本地无 Redis / SQLite：
    python -m app.worker.worker --once   # 取一条 queued 任务直接执行
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from ..agents.engine import execute_agent_run
from ..config import Settings
from ..db import Database
from ..logging_setup import set_trace_id
from ..models import AgentRun, Task
from ..services.storage import build_storage
from ..services.tasks import execute_task, get_runner
from . import enqueue_agent_run, enqueue_task

logger = logging.getLogger("moxie.worker")


def _fetch_byok(settings: Settings, task_id: str, prefix: str = "task") -> str | None:
    """BYOK 只存在 Redis（TTL 1h），不落库、不写日志。"""
    from ..redis_client import try_redis

    client = try_redis(settings)
    if client is None:
        return None
    try:
        value = client.get(f"{prefix}:byok:{task_id}")
        return value.decode("utf-8") if value else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取 BYOK 临时 Key 失败，使用平台 Key：%s", type(exc).__name__)
        return None
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def _run(session, task: Task, settings: Settings, storage) -> str:
    return execute_task(
        session,
        task,
        get_runner(task.type),
        settings=settings,
        storage=storage,
        byok_key=_fetch_byok(settings, task.id),
    )


def _fail_job(session, row, *, code: str, message: str, reservation) -> None:
    """worker 顶层异常兜底：认领已提交，必须落终态并释放预占，避免永久卡 running。"""
    from ..db import utcnow
    from ..services.quota import QuotaService

    now = utcnow()
    QuotaService(session).release(reservation, now=now)
    row.status = "failed"
    row.error_code = code
    row.error_message = message[:255]
    row.finished_at = now
    row.updated_at = now
    if hasattr(row, "lease_until"):
        row.lease_until = None
    session.commit()


def run_task_job(task_id: str) -> str:
    settings = Settings()
    db = Database(settings)
    try:
        try:
            with db.session() as session:
                # 绑定当前会话：产物落库与任务状态在同一事务内，避免 SQLite 写锁冲突
                storage = build_storage(settings, db.session_factory, session=session)
                task = session.get(Task, task_id)
                if task is None:
                    logger.warning("task not found: %s", task_id)
                    return "missing"
                set_trace_id(task.id)
                status = _run(session, task, settings, storage)
                session.commit()
                if status == "queued":
                    # 失败重试的退避未到点时不立即重投，否则会形成秒级空转重投；
                    # 交给 scheduler 的 dispatch_retry_due 到点后统一入队。
                    from ..db import utcnow

                    if task.next_retry_at is not None and task.next_retry_at > utcnow():
                        logger.info("task %s retry deferred until %s, skip re-enqueue", task_id, task.next_retry_at)
                    elif enqueue_task(settings, task_id):
                        # 批量让出后本 RQ job 已结束：必须重新投递，否则任务永久滞留 queued（孤儿）
                        logger.info("task %s rescheduled, re-enqueued", task_id)
                    else:
                        logger.warning("task %s rescheduled but re-enqueue failed（本地模式可用 --loop 执行）", task_id)
                return status
        except Exception as exc:  # noqa: BLE001 - 顶层失败也要落终态
            logger.exception("task job failed task_id=%s", task_id)
            from ..services.tasks import _reservation_of

            with db.session() as session:
                task = session.get(Task, task_id)
                if task is not None and task.status not in ("succeeded", "failed", "canceled"):
                    _fail_job(
                        session,
                        task,
                        code="worker_error",
                        message=f"{type(exc).__name__}: {exc}",
                        reservation=_reservation_of(session, task),
                    )
            return "failed"
    finally:
        db.dispose()


def run_agent_job(run_id: str) -> str:
    settings = Settings()
    db = Database(settings)
    try:
        try:
            with db.session() as session:
                storage = build_storage(settings, db.session_factory, session=session)
                run = session.get(AgentRun, run_id)
                if run is None:
                    logger.warning("agent run not found: %s", run_id)
                    return "missing"
                set_trace_id(run.id)
                byok = _fetch_byok(settings, run.id, prefix="agent")
                status = execute_agent_run(
                    session,
                    run,
                    settings=settings,
                    storage=storage,
                    byok=bool(byok),
                    # 仅传真实 BYOK；平台 Key 由 resolve_step_model 内部按「工序 Key → 环境变量」兜底，
                    # 否则会把环境变量 Key 当成 BYOK，压过工序级配置的 Key。
                    api_key=byok or "",
                )
                session.commit()
                if status == "queued":
                    # 批量上限让出后本 RQ job 已结束：必须重新投递，否则运行永久滞留 queued（孤儿）
                    if enqueue_agent_run(settings, run_id):
                        logger.info("agent run %s rescheduled, re-enqueued", run_id)
                    else:
                        logger.warning("agent run %s rescheduled but re-enqueue failed（本地模式可用 --loop 执行）", run_id)
                return status
        except Exception as exc:  # noqa: BLE001 - 顶层失败也要落终态
            logger.exception("agent run job failed run_id=%s", run_id)
            from ..agents.store import reservation_of

            with db.session() as session:
                run = session.get(AgentRun, run_id)
                if run is not None and run.status not in ("succeeded", "failed", "canceled"):
                    _fail_job(
                        session,
                        run,
                        code="worker_error",
                        message=f"{type(exc).__name__}: {exc}",
                        reservation=reservation_of(session, run),
                    )
            return "failed"
    finally:
        db.dispose()


def run_once() -> int:
    """本地模式：优先执行一条 queued 任务，其次执行一条 queued Agent 运行。"""
    settings = Settings()
    db = Database(settings)
    processed = 0
    try:
        with db.session() as session:
            storage = build_storage(settings, db.session_factory, session=session)
            from ..db import utcnow

            now = utcnow()
            task = session.scalar(
                select(Task)
                .where(
                    Task.status == "queued",
                    (Task.next_retry_at.is_(None) | (Task.next_retry_at <= now)),
                )
                .order_by(Task.created_at.asc())
                .limit(1)
            )
            if task is not None:
                set_trace_id(task.id)
                _run(session, task, settings, storage)
                session.commit()
                return 1
            run = session.scalar(
                select(AgentRun).where(AgentRun.status == "queued").order_by(AgentRun.created_at.asc()).limit(1)
            )
            if run is None:
                return 0
            set_trace_id(run.id)
            byok = _fetch_byok(settings, run.id, prefix="agent")
            execute_agent_run(
                session,
                run,
                settings=settings,
                storage=storage,
                byok=bool(byok),
                # 仅传真实 BYOK；平台 Key 由 resolve_step_model 内部按「工序 Key → 环境变量」兜底，
                # 否则会把环境变量 Key 当成 BYOK，压过工序级配置的 Key。
                api_key=byok or "",
            )
            session.commit()
            processed = 1
    finally:
        db.dispose()
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="墨写任务 Worker")
    parser.add_argument("--once", action="store_true", help="本地模式：执行一条 queued 任务或 Agent 运行后退出")
    parser.add_argument("--loop", action="store_true", help="本地模式：轮询执行 queued 任务")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.once:
        count = run_once()
        print(f"processed={count}")
        return

    if args.loop:
        import time

        while True:
            count = run_once()
            time.sleep(2 if count else 5)

    print("请使用 RQ 启动：rq worker moxie --url <redis_url>，或使用 --once / --loop", file=sys.stderr)


if __name__ == "__main__":
    main()
