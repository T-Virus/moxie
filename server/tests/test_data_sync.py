# -*- coding: utf-8 -*-
"""前后端数据同步一致性回归：任务看板 / 预设维护列表。

历史缺陷：
  1. 任务看板只读 tasks 表，用户在创作页触发的写作运行（agent_runs）完全不显示；
  2. 预设维护列表只读系统级预设，用户自定义预设不可见、不可维护；
  3. 前端本地硬编码常量会覆盖服务端结果，导致管理端删除的预设「复活」。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Account, AgentRun, Preset

from .helpers import subscribe


def _promote(app, account_id: int, role: str = "admin") -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = role
        session.commit()


def _create_run(client, headers, title: str = "同步测试书稿") -> str:
    resp = client.post(
        "/v1/agent-runs",
        headers={**headers, "Idempotency-Key": f"sync-{uuid.uuid4()}"},
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


def test_dashboard_includes_user_triggered_agent_runs(client, headers, app, account):
    """创作页触发的写作运行必须出现在任务看板（队列深度/统计/明细）。"""
    subscribe(client, headers)
    run_id = _create_run(client, headers)
    _promote(app, account["account"]["id"])

    dash = client.get("/v1/admin/tasks/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["queue_depth"] >= 1
    assert body["by_status"].get("queued", 0) >= 1

    # 运行中的写作任务应出现在 running 明细，并带上来源与作品名
    with app.state.db.session() as session:
        run = session.get(AgentRun, run_id)
        run.status = "running"
        session.commit()

    dash = client.get("/v1/admin/tasks/dashboard", headers=headers).json()
    assert body["queue_depth"] >= 0
    row = next((r for r in dash["running"] if r["id"] == run_id), None)
    assert row is not None, dash["running"]
    assert row["source"] == "agent_run"
    assert row["title"] == "同步测试书稿"
    assert dash["running_count"] >= 1


def test_admin_task_list_and_user_detail_include_agent_runs(client, headers, app, account):
    """管理端任务列表与用户详情「最近任务」同样要覆盖写作运行。"""
    subscribe(client, headers)
    run_id = _create_run(client, headers, title="用户详情同步")
    _promote(app, account["account"]["id"])
    account_id = account["account"]["id"]

    listed = client.get("/v1/admin/tasks", headers=headers).json()["items"]
    assert any(r["id"] == run_id and r["source"] == "agent_run" for r in listed)

    detail = client.get(f"/v1/admin/users/{account_id}", headers=headers).json()
    assert any(r["id"] == run_id and r["source"] == "agent_run" for r in detail["recent_tasks"])


def test_presets_endpoint_returns_requested_empty_groups(client, headers):
    """请求了但没有数据的类型应显式返回空组，前端才可严格以服务端为准。"""
    resp = client.get("/v1/presets?types=info_selling_point,no_such_type_xyz", headers=headers)
    assert resp.status_code == 200, resp.text
    groups = resp.json()["groups"]
    # info_selling_point 有内置种子；no_such_type_xyz 无数据但必须返回空组
    assert groups.get("no_such_type_xyz") == []


def test_admin_presets_list_includes_user_custom_presets(client, headers, app, account):
    """预设维护列表默认包含用户自定义项，scope 可切换；且可编辑/删除。"""
    custom = client.post(
        "/v1/presets",
        headers=headers,
        json={"type": "info_selling_point", "value": "管理端可见卖点X"},
    )
    assert custom.status_code == 201, custom.text
    pid = custom.json()["id"]
    account_id = account["account"]["id"]
    _promote(app, account_id)

    all_rows = client.get("/v1/admin/presets", headers=headers).json()
    row = next((r for r in all_rows["items"] if r["id"] == pid), None)
    # 自定义项可能在第二页，按精确查询再校验一次归属字段
    if row is None:
        row = client.get(
            "/v1/admin/presets", headers=headers, params={"q": "管理端可见卖点X"}
        ).json()["items"][0]
    assert row["custom"] is True
    assert row["account_id"] == account_id
    assert "info_selling_point" in all_rows["types"]

    system_only = client.get(
        "/v1/admin/presets", headers=headers,
        params={"scope": "system", "q": "管理端可见卖点X"},
    ).json()
    assert system_only["total"] == 0

    custom_only = client.get(
        "/v1/admin/presets", headers=headers,
        params={"scope": "custom", "q": "管理端可见卖点X"},
    ).json()
    assert custom_only["total"] == 1

    # 管理端可编辑用户自定义项，且不改变归属
    updated = client.put(
        f"/v1/admin/presets/{pid}", headers=headers,
        json={"type": "info_selling_point", "value": "管理端改名卖点Y"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["account_id"] == account_id
    assert updated.json()["custom"] is True

    deleted = client.delete(f"/v1/admin/presets/{pid}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    with app.state.db.session() as session:
        assert session.scalar(select(Preset.id).where(Preset.id == pid)) is None


def test_user_custom_preset_flows_to_client_presets(client, headers):
    """用户自定义的预设值能通过前端统一预设接口拉回（闭环一致性）。"""
    resp = client.post(
        "/v1/presets", headers=headers,
        json={"type": "outline_ending", "value": "闭环结局测试值"},
    )
    assert resp.status_code == 201, resp.text
    listed = client.get("/v1/presets?type=outline_ending", headers=headers).json()
    values = {item["value"] for item in listed["groups"]["outline_ending"]}
    assert "闭环结局测试值" in values
