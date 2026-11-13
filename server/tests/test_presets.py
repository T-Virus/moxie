# -*- coding: utf-8 -*-
"""统一预设接口与题材接口测试。"""

from __future__ import annotations


def test_presets_grouped(client, headers):
    resp = client.get("/v1/presets?types=genre,character_gender,info_theme", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    groups = body["groups"]
    assert "genre" in groups
    assert "character_gender" in groups
    assert "info_theme" in groups
    # 题材全量（含跨频/男频/女频）已入库
    genre_values = {item["value"] for item in groups["genre"]}
    assert "玄幻" in genre_values
    assert "言情" in genre_values
    assert "无限流" in genre_values
    # audience 已解析为列表
    xuanhuan = next(i for i in groups["genre"] if i["value"] == "玄幻")
    assert "all" in xuanhuan["audience"]
    # 性别预设
    assert "女" in {i["value"] for i in groups["character_gender"]}


def test_presets_single_type(client, headers):
    resp = client.get("/v1/presets?type=outline_ending", headers=headers)
    assert resp.status_code == 200, resp.text
    endings = {i["value"] for i in resp.json()["groups"]["outline_ending"]}
    assert "HE 圆满" in endings
    assert "BE 悲剧" in endings


def test_genres_from_presets(client, headers):
    resp = client.get("/v1/genres", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["custom_allowed"] is True
    names = {item["name"] for item in body["items"]}
    assert "玄幻" in names
    assert len(names) >= 100


def test_user_custom_preset_isolation(client, headers):
    # 创建本人私有自定义预设
    r = client.post("/v1/presets", json={"type": "outline_ending", "value": "自定义结局隔离"}, headers=headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["custom"] is True

    # 本人可见
    me = client.get("/v1/presets?type=outline_ending", headers=headers).json()
    assert any(i["value"] == "自定义结局隔离" and i["custom"] for i in me["groups"]["outline_ending"])

    # 重复创建同 type+value → 409
    dup = client.post("/v1/presets", json={"type": "outline_ending", "value": "自定义结局隔离"}, headers=headers)
    assert dup.status_code == 409, dup.text

    # 另一用户注册并登录，互相隔离
    client.post(
        "/v1/auth/register",
        json={"email": "u2preset@example.com", "password": "password123", "phone": "13800001234"},
    )
    la = client.post("/v1/auth/login", json={"email": "u2preset@example.com", "password": "password123"})
    h2 = {"Authorization": f"Bearer {la.json()['access_token']}"}
    other = client.get("/v1/presets?type=outline_ending", headers=h2).json()
    assert not any(i["value"] == "自定义结局隔离" for i in other["groups"]["outline_ending"])

    # 不能删除别人的预设
    forbidden = client.delete(f"/v1/presets/{pid}", headers=h2)
    assert forbidden.status_code == 404, forbidden.text

    # 本人可删除
    own = client.delete(f"/v1/presets/{pid}", headers=headers)
    assert own.status_code == 200, own.text


def test_delete_user_cascades_custom_presets(client, app):
    from sqlalchemy import select

    from app.models import Account, Preset

    # 构造一个 admin 账号用于调用删除接口
    client.post(
        "/v1/auth/register",
        json={"email": "admin_cp@example.com", "password": "password123", "phone": "13800001111"},
    )
    with app.state.db.session() as s:
        acc = s.scalar(select(Account).where(Account.email == "admin_cp@example.com"))
        acc.role = "admin"
        s.commit()
    admin_la = client.post(
        "/v1/auth/login", json={"email": "admin_cp@example.com", "password": "password123"}
    )
    admin_h = {"Authorization": f"Bearer {admin_la.json()['access_token']}"}

    # 普通用户注册、登录、创建自定义预设
    client.post(
        "/v1/auth/register",
        json={"email": "cascade_p@example.com", "password": "password123", "phone": "13800005678"},
    )
    la = client.post("/v1/auth/login", json={"email": "cascade_p@example.com", "password": "password123"})
    ha = {"Authorization": f"Bearer {la.json()['access_token']}"}
    pid = client.post("/v1/presets", json={"type": "item_category", "value": "级联类别"}, headers=ha).json()["id"]

    # admin 删除该普通账号（用整数 id；/users/by-email 会被 /users/{id} 路由抢先匹配，故此处用 id）
    with app.state.db.session() as s:
        cascade_id = s.scalar(select(Account.id).where(Account.email == "cascade_p@example.com"))
    d = client.request("DELETE", f"/v1/admin/users/{cascade_id}", headers=admin_h)
    assert d.status_code == 200, d.text

    # 删除用户后，其自定义预设应被级联清理（无孤儿数据）
    with app.state.db.session() as s:
        assert s.scalar(select(Preset.id).where(Preset.id == pid)) is None
