# -*- coding: utf-8 -*-
"""RQ worker 启动入口。

compose 里原本直接跑 `rq worker moxie`；这样 worker 进程内的任务成功/失败、
模型调用、技能耗时等指标永远没有出口。改为本入口后：
1) 先把指标增量接入 Redis 汇总（与 api/scheduler 同口径）；
2) 起一个只读 /metrics 端点；
3) 再交给 RQ 消费队列。
"""

from __future__ import annotations

import logging
import os
import sys

from redis import Redis
from rq import Queue, Worker

from .. import metrics
from ..config import Settings
from .metrics_server import start_metrics_server

logger = logging.getLogger("moxie.worker")


def _queue_depth(settings: Settings) -> dict[str, float]:
    """抓取时实时读取队列长度；Redis 异常时不影响其它指标输出。"""
    connection = None
    try:
        connection = Redis.from_url(settings.redis_url)
        return {"moxie_worker_queue_depth": float(len(Queue("moxie", connection=connection)))}
    except Exception:  # noqa: BLE001
        return {}
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    if settings.metrics_enabled:
        metrics.configure(settings.redis_url)
    port = int(os.getenv("WORKER_METRICS_PORT", "9101"))
    start_metrics_server(port, extra_samples=lambda: _queue_depth(settings))

    connection = Redis.from_url(settings.redis_url)
    try:
        Worker(["moxie"], connection=connection).work()
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass
        metrics.disable()
    return 0


if __name__ == "__main__":
    sys.exit(main())
