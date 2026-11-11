# -*- coding: utf-8 -*-
"""任务创建幂等、执行、取消、日志轮询。"""

from __future__ import annotations

from app.models import Task
from app.services.tasks import execute_task, get_runner

from .helpers import db_session, subscribe


def test_create_is_idempotent(client, headers, app):
    subscribe(client, headers)
    body = {"type": "decompose", "params": {"title": "demo"}}
    first = client.post(
        "/v1/tasks", headers={**headers, "Idempotency-Key": "decompose-1"}, json=body
    )
    assert first.status_code == 201, first.text
    task_id = first.json()["task"]["id"]

    second = client.post(
        "/v1/tasks", headers={**headers, "Idempotency-Key": "decompose-1"}, json=body
    )
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["task"]["id"] == task_id

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 1  # 只预占一次


def test_execute_task_succeeds_and_settles_quota(client, headers, app):
    subscribe(client, headers)
    created = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "run-1"},
        json={"type": "decompose", "params": {}},
    )
    task_id = created.json()["task"]["id"]

    with db_session(app) as session:
        task = session.get(Task, task_id)
        status = execute_task(session, task, get_runner("decompose"))
        session.commit()
    assert status == "succeeded"

    detail = client.get(f"/v1/tasks/{task_id}", headers=headers).json()["task"]
    assert detail["status"] == "succeeded"
    assert detail["progress"] == 100
    assert detail["output_artifact"].startswith("noop://")

    logs = client.get(f"/v1/tasks/{task_id}/logs", headers=headers).json()
    assert logs["events"]
    assert logs["next_seq"] >= 1

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["used"] == 1
    assert books["reserved"] == 0


def test_cancel_queued_task(client, headers, app):
    subscribe(client, headers)
    created = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "cancel-1"},
        json={"type": "review", "params": {}},
    )
    task_id = created.json()["task"]["id"]

    response = client.post(f"/v1/tasks/{task_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert response.json()["task"]["status"] == "canceled"

    # 再取消一次：幂等，不再产生状态变化
    again = client.post(f"/v1/tasks/{task_id}/cancel", headers=headers)
    assert again.json()["changed"] is False

    summary = client.get("/v1/entitlements", headers=headers).json()
    reviews = next(m for m in summary["metrics"] if m["metric"] == "review_month")
    assert reviews["reserved"] == 0
    assert reviews["used"] == 0


def test_running_task_is_cancelled_cooperatively(client, headers, app):
    subscribe(client, headers)
    created = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "coop-1"},
        json={"type": "adapt", "params": {"chapters": 2}},
    )
    task_id = created.json()["task"]["id"]

    # 模拟取消请求已经写入（真实场景由 /cancel 接口写入）
    with db_session(app) as session:
        task = session.get(Task, task_id)
        task.cancel_requested = True
        session.commit()

    with db_session(app) as session:
        task = session.get(Task, task_id)
        status = execute_task(session, task, get_runner("adapt"))
        session.commit()
    assert status == "canceled"

    summary = client.get("/v1/entitlements", headers=headers).json()
    chapters = next(m for m in summary["metrics"] if m["metric"] == "adapt_chapters")
    assert chapters["reserved"] == 0
    assert chapters["used"] == 0


def test_task_not_found_and_isolation(client, headers, app):
    subscribe(client, headers)
    created = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "iso-1"},
        json={"type": "decompose", "params": {}},
    )
    task_id = created.json()["task"]["id"]

    other = client.post(
        "/v1/auth/register",
        json={"email": "other-tasks@example.com", "password": "password123"},
    ).json()
    response = client.get(
        f"/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {other['access_token']}"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"
