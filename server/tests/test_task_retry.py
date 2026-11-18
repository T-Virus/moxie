# -*- coding: utf-8 -*-
"""任务失败重试：有限次数内回队列保留预占，达上限落 failed 死信。"""

from __future__ import annotations

from datetime import timedelta

from app.db import utcnow
from app.models import Task
from app.scheduler import dispatch_retry_due
from app.services.tasks import execute_task, retry_backoff_seconds

from .helpers import db_session, subscribe


class AlwaysFailRunner:
    """始终失败的 runner（duck typing，满足 TaskRunner 协议的 run 方法）。"""

    def run(self, ctx) -> str | None:
        raise RuntimeError("upstream 503")


def _create_task(client, headers) -> str:
    subscribe(client, headers)
    created = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "retry-case"},
        json={"type": "decompose", "params": {}},
    )
    assert created.status_code == 201, created.text
    return created.json()["task"]["id"]


def test_task_retries_then_becomes_dead_letter(client, headers, app):
    task_id = _create_task(client, headers)
    app.state.settings.task_max_attempts = 3

    statuses = []
    # 每次重试模拟 scheduler 到点重投：把 now 推进到 next_retry_at 之后
    due_at = utcnow()
    for i in range(3):
        with db_session(app) as session:
            task = session.get(Task, task_id)
            status = execute_task(
                session, task, AlwaysFailRunner(), now=due_at, settings=app.state.settings
            )
            session.commit()
            statuses.append((status, task.attempts, task.status))
            if i < 2:
                # 失败已写入退避到点时间，推进模拟时钟越过它
                due_at = task.next_retry_at + timedelta(seconds=1)
        if i == 0:
            # 第一次重试后：预占必须仍在（否则重试会重复扣额度）
            midway = client.get("/v1/entitlements", headers=headers).json()
            books = next(m for m in midway["metrics"] if m["metric"] == "books_month")
            assert books["reserved"] == 1, "重试期间预占被错误释放"

    # 前两次失败回到 queued（重试），第三次达上限落 failed（死信）
    assert statuses[0][0] == "queued" and statuses[0][1] == 1
    assert statuses[1][0] == "queued" and statuses[1][1] == 2
    assert statuses[2][0] == "failed" and statuses[2][1] == 3

    detail = client.get(f"/v1/tasks/{task_id}", headers=headers).json()["task"]
    assert detail["status"] == "failed"
    assert detail["error_code"] == "task_failed"

    # 关键：重试期间预占保留，死信后才释放——额度不会重复扣
    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 0  # 最终失败已释放
    assert books["used"] == 0  # 从未结算（没有成功）


def test_max_attempts_one_disables_retry(client, headers, app):
    task_id = _create_task(client, headers)
    app.state.settings.task_max_attempts = 1

    with db_session(app) as session:
        task = session.get(Task, task_id)
        status = execute_task(session, task, AlwaysFailRunner(), settings=app.state.settings)
        session.commit()
    assert status == "failed"
    assert task.attempts == 1


def test_retry_backoff_exponential_with_cap(app):
    """退避按 base*2^(n-1) 指数增长并封顶；jitter=0 落在区间下沿（half jitter）。"""
    s = app.state.settings
    s.task_retry_backoff_seconds = 5
    s.task_retry_backoff_max_seconds = 300
    zero = lambda: 0.0
    # half jitter：rng=0 取 delay/2（向上取整）
    assert retry_backoff_seconds(1, s, rng=zero) == 3
    assert retry_backoff_seconds(2, s, rng=zero) == 5
    assert retry_backoff_seconds(3, s, rng=zero) == 10
    assert retry_backoff_seconds(20, s, rng=zero) == 150  # 封顶 300 的下沿
    assert retry_backoff_seconds(0, s, rng=zero) == 3     # 下限保护


def test_retry_backoff_jitter_spreads_same_attempt(app):
    """同一次失败的不同任务加抖动后落在不同时点，避免同频惊群。"""
    s = app.state.settings
    s.task_retry_backoff_seconds = 10
    s.task_retry_backoff_max_seconds = 300
    # rng=0 → 5s；rng=1 → 10s；中间值落在区间内
    assert retry_backoff_seconds(1, s, rng=lambda: 0.0) == 5
    assert retry_backoff_seconds(1, s, rng=lambda: 1.0) == 10
    assert 5 <= retry_backoff_seconds(1, s, rng=lambda: 0.5) <= 10


def test_failure_retry_sets_next_retry_at(client, headers, app):
    """首次失败回到 queued 时写入退避到点时间，未到点前无法被再次认领。"""
    task_id = _create_task(client, headers)
    app.state.settings.task_max_attempts = 3
    app.state.settings.task_retry_backoff_seconds = 5
    t0 = utcnow()

    with db_session(app) as session:
        task = session.get(Task, task_id)
        status = execute_task(session, task, AlwaysFailRunner(), now=t0, settings=app.state.settings)
        session.commit()
        assert status == "queued"
        assert task.next_retry_at is not None
        # jitter 落在 [base/2, base] = [2.5s, 5s]
        delta = (task.next_retry_at - t0).total_seconds()
        assert 2.5 <= delta <= 5.0

    # 详情 API 暴露下次重试时间（jitter 后落在 [2.5s, 5s] 内）
    detail = client.get(f"/v1/tasks/{task_id}", headers=headers).json()["task"]
    assert detail["next_retry_at"] is not None
    assert detail["attempts"] == 1

    # 未到点直接重投：原子认领被拒，attempts 不变（worker 不会空转）
    with db_session(app) as session:
        task = session.get(Task, task_id)
        status = execute_task(session, task, AlwaysFailRunner(), now=t0 + timedelta(seconds=1), settings=app.state.settings)
        session.commit()
        assert task.attempts == 1, "退避未到点却被再次认领"


def test_scheduler_dispatches_retry_when_due(client, headers, app):
    """调度器到点清 next_retry_at 并收集 task_id 供重新入队。"""
    task_id = _create_task(client, headers)
    app.state.settings.task_max_attempts = 3
    t0 = utcnow()
    with db_session(app) as session:
        task = session.get(Task, task_id)
        execute_task(session, task, AlwaysFailRunner(), now=t0, settings=app.state.settings)
        session.commit()

    # 未到点不触发
    with db_session(app) as session:
        out: list[str] = []
        assert dispatch_retry_due(session, app.state.settings, now=t0 + timedelta(seconds=1), task_out=out) == 0
        assert out == []

    # 到点触发，清字段并回流 task_id
    with db_session(app) as session:
        out = []
        assert dispatch_retry_due(session, app.state.settings, now=t0 + timedelta(seconds=10), task_out=out) == 1
        session.commit()
        assert out == [task_id]
        task = session.get(Task, task_id)
        assert task.next_retry_at is None
        assert task.status == "queued"
