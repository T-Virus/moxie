# -*- coding: utf-8 -*-
"""运营任务管控：取消 / 暂停 / 继续 / 重新排队 / 强制终止。

历史缺陷：看板只能看不能动，任务卡在 running 时后台既无法取消也无法释放预占，
前端停止后状态也不再刷新，导致「触发之后不可控」。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import Account, AgentRun, AgentRunStep, AuditLog, UsageAggregate


def _promote(app, account_id: int, role: str = "admin") -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = role
        session.commit()


def _create_run(client, headers, title: str = "管控测试书稿") -> str:
    resp = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": f"ctl-{uuid.uuid4()}"},
        json={
            "mode": "hot",
            "title": title,
            "audience": "male",
            "length": "short",
            "genre": {"id": "xuanyi", "name": "悬疑"},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]


def _reserved_total(app, account_id: int) -> int:
    with app.state.db.session() as session:
        return int(
            session.scalar(
                select(func.sum(UsageAggregate.reserved)).where(
                    UsageAggregate.account_id == account_id
                )
            )
            or 0
        )


def _set_status(app, run_id: str, status: str) -> None:
    with app.state.db.session() as session:
        run = session.get(AgentRun, run_id)
        run.status = status
        session.commit()


def test_admin_cancel_paused_run(client, headers, app, account):
    from .helpers import subscribe

    subscribe(client, headers)
    run_id = _create_run(client, headers)
    assert client.post(f"/v1/agent-runs/{run_id}/pause", headers=headers).status_code == 200
    _promote(app, account["account"]["id"])

    resp = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "cancel", "source": "agent_run"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "canceled"
    assert client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()["status"] == "canceled"

    # 重复取消：已终态不再产生状态变化
    again = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "cancel", "source": "agent_run"},
    )
    assert again.status_code == 409


def test_admin_force_cancel_releases_reservation(client, headers, app, account):
    from .helpers import subscribe

    subscribe(client, headers)
    run_id = _create_run(client, headers)
    _promote(app, account["account"]["id"])
    account_id = account["account"]["id"]
    assert _reserved_total(app, account_id) >= 1
    _set_status(app, run_id, "running")
    # 模拟 worker 卡在某个节点上：该节点行残留 running
    with app.state.db.session() as session:
        step = session.scalar(select(AgentRunStep).where(AgentRunStep.run_id == run_id))
        step.status = "running"
        session.commit()

    resp = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "force_cancel", "reason": "任务卡死超过预期"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "agent_run"
    assert resp.json()["status"] == "canceled"

    with app.state.db.session() as session:
        run = session.get(AgentRun, run_id)
        assert run.status == "canceled"
        assert run.error_code == "canceled_by_admin"
        assert run.error_message == "任务卡死超过预期"
    # 卡死任务不再占着额度
    assert _reserved_total(app, account_id) == 0

    # 已结束的运行不能再把残留节点报成「进行中」，否则前端一直显示生成中
    detail = client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()
    assert detail["status"] == "canceled"
    assert detail["current_stage"] is None
    assert all(stage["state"] != "running" for stage in detail["stages"])


def test_admin_resume_and_requeue(client, headers, app, account):
    from .helpers import subscribe

    subscribe(client, headers)
    run_id = _create_run(client, headers)
    _promote(app, account["account"]["id"])

    assert client.post(f"/v1/agent-runs/{run_id}/pause", headers=headers).status_code == 200
    assert client.get(f"/v1/agent-runs/{run_id}", headers=headers).json()["status"] == "paused"

    resp = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "resume"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"

    _set_status(app, run_id, "running")
    resp = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "requeue"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"

    # 管控动作必须留痕
    with app.state.db.session() as session:
        actions = {
            row.action
            for row in session.scalars(
                select(AuditLog).where(AuditLog.target_id == run_id)
            ).all()
        }
    assert {"agent_run.resume", "agent_run.requeue"} <= actions


def test_admin_control_validates_state_and_action(client, headers, app, account):
    from .helpers import subscribe

    subscribe(client, headers)
    run_id = _create_run(client, headers)
    _promote(app, account["account"]["id"])

    # 排队中的运行没有「继续」语义
    resp = client.post(
        f"/v1/admin/tasks/{run_id}/control",
        headers=headers,
        json={"action": "resume"},
    )
    assert resp.status_code == 409

    resp = client.post(
        "/v1/admin/tasks/not-exists/control",
        headers=headers,
        json={"action": "cancel"},
    )
    assert resp.status_code == 404
