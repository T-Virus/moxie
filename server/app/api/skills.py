# -*- coding: utf-8 -*-
"""统一技能目录 API：产品把 10 个创作环节作为可发现的能力暴露给三端。

- GET /v1/skills         用户端精简视图（登录即可读）
- GET /v1/admin/skills   管理端完整治理视图（staff 可读）

唯一事实源是 config/skills_catalog.json；读写一致性由 services/skill_directory.py
与 scripts/check_skills.py 保证，前端不得再硬编码一份环节清单。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..deps import AuthContext, get_auth, require_staff
from ..models import Account
from ..schemas import AdminSkillsCatalogResponse, SkillsCatalogResponse
from ..services.skill_directory import build_skill_catalog

router = APIRouter(tags=["skills"])
admin_router = APIRouter(tags=["admin", "skills"])


@router.get("/skills", response_model=SkillsCatalogResponse)
def list_skills(
    request: Request,
    _auth: AuthContext = Depends(get_auth),
):
    return build_skill_catalog(request.app.state.settings)


@admin_router.get("/admin/skills", response_model=AdminSkillsCatalogResponse)
def admin_list_skills(
    request: Request,
    _staff: Account = Depends(require_staff),
):
    return build_skill_catalog(request.app.state.settings, admin=True)
