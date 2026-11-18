# -*- coding: utf-8 -*-
"""SSE 聚合流与详情流：路由顺序、鉴权与事件回放。"""

from __future__ import annotations

import uuid

from app.models import AgentRun, AgentRunEvent

from .test_admin_ext import _promote


def test_account_run_feed_route_is_not_shadowed(client, headers, monkeypatch):
    from app.api import agent_runs

    monkeypatch.setattr(agent_runs, "FEED_MAX_TICKS", 1)
    monkeypatch.setattr(agent_runs, "FEED_POLL_SECONDS", 0.01)

    resp = client.get("/v1/agent-runs/stream", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "text/event-stream" in resp.headers["content-type"]
    assert "event: ready" in resp.text
    assert "event: end" in resp.text


def test_admin_feed_and_task_detail_stream(client, headers, app, account, monkeypatch):
    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "SSE_MAX_TICKS", 1)
    monkeypatch.setattr(admin_api, "SSE_POLL_SECONDS", 0.01)
    _promote(app, account["account"]["id"], "admin")

    feed = client.get("/v1/admin/tasks/stream", headers=headers)
    assert feed.status_code == 200, feed.text
    assert "event: ready" in feed.text

    run_id = uuid.uuid4().hex
    with app.state.db.session() as session:
        session.add(
            AgentRun(
                id=run_id,
                account_id=account["account"]["id"],
                mode="hot",
                title="流测试",
                audience="male",
                length="short",
                genre_name="玄幻",
                idempotency_key=f"sse-{run_id}",
                status="running",
            )
        )
        session.add(
            AgentRunEvent(
                run_id=run_id,
                seq=1,
                stage="outline",
                level="info",
                message="stream-hello",
            )
        )
        session.commit()

    detail = client.get(
        f"/v1/admin/tasks/{run_id}/events",
        headers=headers,
        params={"source": "agent_run", "since": 0},
    )
    assert detail.status_code == 200, detail.text
    assert "stream-hello" in detail.text
    assert "event: status" in detail.text
