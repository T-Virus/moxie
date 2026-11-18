# -*- coding: utf-8 -*-
"""统一技能目录：服务层降级、契约、鉴权与三端一致性回归。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import Account
from app.services import skill_directory


def _promote(app, account_id: int) -> None:
    with app.state.db.session() as session:
        session.get(Account, account_id).role = "admin"
        session.commit()


# —— 服务层 ——

def test_build_user_catalog_reads_ssot(settings):
    catalog = skill_directory.build_skill_catalog(settings)
    assert catalog["degraded"] is None
    assert catalog["schema_version"] == "1.0"
    assert len(catalog["items"]) == 10
    ids = [item["id"] for item in catalog["items"]]
    assert ids == ["scan", "analyze", "character", "outline", "memory", "write", "polish", "review", "consistency", "cover"]
    # 用户端视图不含技术字段
    first = catalog["items"][0]
    assert set(first) == {"id", "index", "name", "external", "trigger", "purpose", "coverage", "available", "entry"}
    assert set(first["entry"]) == {"stages", "cloud_skills", "api"}


def test_build_admin_catalog_has_governance_fields(settings):
    catalog = skill_directory.build_skill_catalog(settings, admin=True)
    assert len(catalog["items"]) == 10
    first = catalog["items"][0]
    for field in ("gap", "ssot", "writes", "registered", "cloud_files", "desktop_files", "reference"):
        assert field in first, field
    # 云端注册状态确实来自 registry（拆书 / 大纲 / 审稿为已注册技能）
    by_id = {item["id"]: item for item in catalog["items"]}
    assert by_id["analyze"]["registered"] is True
    assert by_id["review"]["registered"] is True
    # 2026-11-18 P1–P3：write / polish / cover 三环节云端技能均已注册
    assert by_id["write"]["registered"] is True
    assert by_id["polish"]["registered"] is True
    assert by_id["cover"]["registered"] is True


def test_missing_explicit_path_falls_back_to_ssot(settings, tmp_path):
    """显式路径失效时回退自动探测，保证生产环境不会因一个错误配置丢失目录。"""
    settings.skills_catalog_path = str(tmp_path / "missing.json")
    catalog = skill_directory.build_skill_catalog(settings)
    assert catalog["degraded"] is None
    assert len(catalog["items"]) == 10


def test_all_paths_missing_degrades(settings, tmp_path, monkeypatch):
    """所有候选路径都不可用时降级而非抛 500。"""
    settings.skills_catalog_path = str(tmp_path / "missing.json")
    monkeypatch.setattr(skill_directory, "_resolve_catalog_path", lambda _s: None)
    catalog = skill_directory.build_skill_catalog(settings)
    assert catalog["items"] == []
    assert catalog["degraded"]
    assert catalog["schema_version"] is None


def test_broken_catalog_degrades(settings, tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    settings.skills_catalog_path = str(bad)
    catalog = skill_directory.build_skill_catalog(settings)
    assert catalog["items"] == []
    assert "解析失败" in (catalog["degraded"] or "")


def test_mtime_change_reloads_catalog(settings, tmp_path):
    doc = json.loads((Path(__file__).resolve().parents[2] / "config" / "skills_catalog.json").read_text(encoding="utf-8"))
    target = tmp_path / "catalog.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    settings.skills_catalog_path = str(target)
    assert len(skill_directory.build_skill_catalog(settings)["items"]) == 10

    doc["items"] = doc["items"][:3]
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert len(skill_directory.build_skill_catalog(settings)["items"]) == 3


# —— API 鉴权与契约 ——

def test_skills_requires_auth(client):
    assert client.get("/v1/skills").status_code == 401


def test_skills_user_view(client, headers):
    resp = client.get("/v1/skills", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"items", "degraded", "schema_version", "updated_at"}
    assert len(data["items"]) == 10
    assert set(data["items"][0]) == {"id", "index", "name", "external", "trigger", "purpose", "coverage", "available", "entry"}


def test_admin_skills_forbidden_for_normal_user(client, headers):
    assert client.get("/v1/admin/skills", headers=headers).status_code == 403


def test_admin_skills_for_staff(client, account, headers):
    _promote(client.app, account["account"]["id"])
    resp = client.get("/v1/admin/skills", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 10
    assert "gap" in data["items"][0] and "registered" in data["items"][0]


def test_skills_have_openapi_contract(client):
    spec = client.get("/openapi.json").json()
    for path in ("/v1/skills", "/v1/admin/skills"):
        ref = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in ref, path
    props = spec["components"]["schemas"]["SkillItemView"]["properties"]
    assert set(props) == {"id", "index", "name", "external", "trigger", "purpose", "coverage", "available", "entry"}
    admin_props = spec["components"]["schemas"]["AdminSkillItemView"]["properties"]
    assert "gap" in admin_props and "registered" in admin_props


# —— 与 SSOT 一致性 ——

def test_catalog_ids_match_ssot_file(settings):
    """API 返回的环节集合必须等于磁盘 SSOT，防止前端/服务各自维护一份。"""
    api_items = skill_directory.build_skill_catalog(settings)["items"]
    ssot = json.loads((Path(__file__).resolve().parents[2] / "config" / "skills_catalog.json").read_text(encoding="utf-8"))
    assert [i["id"] for i in api_items] == [i["id"] for i in ssot["items"]]
