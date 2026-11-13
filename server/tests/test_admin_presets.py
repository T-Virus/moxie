# -*- coding: utf-8 -*-
"""后台预设值维护（CRUD）与种子策略测试。"""

from __future__ import annotations

from app.models import Account
from app.seed import ensure_presets


def _promote(app, account_id: int, role: str = "admin") -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = role
        session.commit()


def test_presets_require_staff(client, headers):
    assert client.get("/v1/admin/presets", headers=headers).status_code == 403


def test_support_can_read_but_not_write(client, headers, app, account):
    _promote(app, account["account"]["id"], "support")
    assert client.get("/v1/admin/presets", headers=headers).status_code == 200
    assert client.post(
        "/v1/admin/presets", headers=headers, json={"type": "genre", "value": "不该写入"}
    ).status_code == 403


def test_admin_presets_crud(client, headers, app, account):
    _promote(app, account["account"]["id"])
    listed = client.get("/v1/admin/presets", headers=headers, params={"type": "genre"})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 100
    assert "genre" in body["types"]

    # 新增：请求体自动 trim；builtin=False 表示后台维护项
    created = client.post(
        "/v1/admin/presets",
        headers=headers,
        json={"type": "  info_theme  ", "value": "  全新主题  ", "label": "  标签  ", "sort": 999},
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert (row["type"], row["value"], row["label"]) == ("info_theme", "全新主题", "标签")
    assert row["builtin"] is False
    pid = row["id"]

    assert client.post(
        "/v1/admin/presets", headers=headers, json={"type": "info_theme", "value": "全新主题"}
    ).status_code == 409

    updated = client.put(
        f"/v1/admin/presets/{pid}",
        headers=headers,
        json={"type": "info_theme", "value": "新主题V2", "audience": "male,female", "sort": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == "新主题V2"

    # 管理端新增项对前端统一预设接口可见
    visible = client.get("/v1/presets?types=info_theme", headers=headers)
    assert "新主题V2" in {item["value"] for item in visible.json()["groups"]["info_theme"]}

    assert client.delete(f"/v1/admin/presets/{pid}", headers=headers).status_code == 200
    gone = client.get("/v1/admin/presets", headers=headers, params={"q": "新主题V2"})
    assert gone.json()["total"] == 0


def test_startup_seed_does_not_resurrect_deleted_preset(client, headers, app, account):
    """管理员删除的预设不应在应用重启（种子重跑）时被复活。"""
    _promote(app, account["account"]["id"])
    first = client.get(
        "/v1/admin/presets", headers=headers, params={"type": "outline_ending", "page_size": 5}
    ).json()["items"][0]
    assert client.delete(f"/v1/admin/presets/{first['id']}", headers=headers).status_code == 200

    with app.state.db.session() as session:
        ensure_presets(session)

    after = client.get("/v1/admin/presets", headers=headers, params={"q": first["value"]}).json()
    assert after["total"] == 0


def test_sync_seeds_fills_only_missing(client, headers, app, account):
    """手动同步只补缺失项，不覆盖已有、不复活被删项之外的脏数据。"""
    _promote(app, account["account"]["id"])
    first = client.get(
        "/v1/admin/presets", headers=headers, params={"type": "outline_ending", "page_size": 5}
    ).json()["items"][0]
    assert client.delete(f"/v1/admin/presets/{first['id']}", headers=headers).status_code == 200

    result = client.post("/v1/admin/presets/sync-seeds", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["inserted"] == 1

    again = client.post("/v1/admin/presets/sync-seeds", headers=headers)
    assert again.json()["inserted"] == 0
