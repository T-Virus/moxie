# -*- coding: utf-8 -*-
"""死信任务列表与重放回归。"""

from __future__ import annotations

import uuid

from app.db import utcnow
from app.models import Account, AuditLog, Task


def test_dead_letter_list_and_replay(client, headers, app, account):
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        session.get(Account, account_id).role = "admin"
        task_id = str(uuid.uuid4())
        session.add(
            Task(
                id=task_id,
                account_id=account_id,
                type="decompose",
                status="failed",
                params={},
                attempts=3,
                error_code="task_failed",
                finished_at=utcnow(),
            )
        )
        session.commit()

    resp = client.get("/v1/admin/tasks/dead-letters", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    assert any(item["id"] == task_id for item in data["items"])

    replay = client.post(
        f"/v1/admin/tasks/{task_id}/replay",
        headers=headers,
        json={"reason": "试点客户催办"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["ok"] is True

    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.status == "queued"
        assert task.attempts == 0
        assert session.query(AuditLog).filter(AuditLog.action == "task.replay").count() >= 1


def test_replay_rejects_non_dead_letter(client, headers, app, account):
    account_id = account["account"]["id"]
    with app.state.db.session() as session:
        session.get(Account, account_id).role = "admin"
        task_id = str(uuid.uuid4())
        session.add(
            Task(
                id=task_id,
                account_id=account_id,
                type="decompose",
                status="failed",
                params={},
                attempts=1,
            )
        )
        session.commit()

    resp = client.post(f"/v1/admin/tasks/{task_id}/replay", headers=headers, json={})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "task_not_dead_letter"
