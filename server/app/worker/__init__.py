# -*- coding: utf-8 -*-
"""Worker 骨架：RQ 队列 + 可注入 runner。"""

from __future__ import annotations

import logging

from ..config import Settings
from ..redis_client import try_redis

logger = logging.getLogger("moxie.queue")


def _enqueue(settings: Settings, target: str, job_id: str, timeout: int, failure: str) -> bool:
    """投递到 RQ；Redis 不可用时立即返回 False（任务保持 queued，可用 --once 执行）。"""
    connection = try_redis(settings)
    if connection is None:
        return False
    try:
        from rq import Queue

        Queue("moxie", connection=connection).enqueue(target, job_id, job_timeout=timeout)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s：%s", failure, exc)
        return False
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass


def enqueue_agent_run(settings: Settings, run_id: str) -> bool:
    """把 Agent 运行投递到同一个 RQ 队列；无 Redis 时保持 queued，可用 --once 执行。"""
    return _enqueue(
        settings,
        "app.worker.worker.run_agent_job",
        run_id,
        3600,
        "enqueue agent run failed（保持 queued，可用 worker --once 执行）",
    )


def enqueue_task(settings: Settings, task_id: str) -> bool:
    """投递到 RQ。失败（没有 Redis / 非生产环境）返回 False，任务保持 queued。"""
    return _enqueue(
        settings,
        "app.worker.worker.run_task_job",
        task_id,
        1800,
        "enqueue failed（任务保持 queued，可用 worker --once 执行）",
    )
