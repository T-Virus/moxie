# -*- coding: utf-8 -*-
"""真实 Postgres 集成测试。

SQLite 不支持 `FOR UPDATE SKIP LOCKED`、行锁与并发写语义，这些路径必须在
真实 Postgres 上验证。未提供 MOXIE_TEST_POSTGRES_URL 时整体自动 skip。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.errors import ApiError
from app.models import Task, UsageAggregate
from app.scheduler import sweep_leases
from app.services.quota import QuotaService, period_of

from .helpers import subscribe

pytestmark = pytest.mark.postgres


def _create_task(client, headers, key: str) -> str:
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": key},
        json={"type": "decompose", "params": {"title": "pg-test"}},
    )
    assert response.status_code == 201, response.text
    return response.json()["task"]["id"]


def test_lease_sweep_skips_rows_locked_by_another_session(pg_client, pg_app, pg_headers):
    """SKIP LOCKED：另一个调度事务持有行锁时本轮不重复认领，释放后才会回收。"""
    subscribe(pg_client, pg_headers)
    task_id = _create_task(pg_client, pg_headers, "pg-lease")

    db = pg_app.state.db
    settings = pg_app.state.settings
    now = utcnow()
    with db.session() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.status = "running"
        task.lease_until = now - timedelta(seconds=30)
        session.commit()

    holder = db.session()
    worker = db.session()
    try:
        # 模拟另一个调度进程已锁定该行（尚未提交）
        holder.execute(select(Task).where(Task.id == task_id).with_for_update())
        assert sweep_leases(worker, settings, now=now) == 0
        worker.rollback()

        # 释放行锁后，同一轮扫描应能回收
        holder.rollback()
        assert sweep_leases(worker, settings, now=now) == 1
        worker.commit()
    finally:
        holder.close()
        worker.close()


def test_quota_reserve_concurrency_respects_limit(pg_client, pg_app, pg_headers, pg_account):
    """并发预占：usage_aggregates 行锁串行化，最多只有 limit 个成功。"""
    subscribe(pg_client, pg_headers)  # creator: books_month = 5
    account_id = pg_account["account"]["id"]
    start, end = period_of(utcnow())
    db = pg_app.state.db

    with db.session() as session:
        session.add(
            UsageAggregate(
                account_id=account_id,
                metric="books_month",
                period_start=start,
                period_end=end,
                used=0,
                reserved=0,
            )
        )
        session.commit()

    def reserve_once(_: int) -> str:
        session = db.session()
        try:
            QuotaService(session).reserve(account_id, "books_month", 1)
            session.commit()
            return "ok"
        except ApiError as exc:
            session.rollback()
            return exc.code
        except Exception:  # noqa: BLE001 - 唯一键竞态等也视为失败，不让测试静默通过
            session.rollback()
            return "error"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(reserve_once, range(6)))

    assert results.count("ok") == 5
    assert results.count("quota_exceeded") == 1

    with db.session() as session:
        agg = session.scalar(
            select(UsageAggregate).where(
                UsageAggregate.account_id == account_id,
                UsageAggregate.metric == "books_month",
                UsageAggregate.period_start == start,
            )
        )
        assert agg is not None
        assert agg.used == 0
        assert agg.reserved == 5
