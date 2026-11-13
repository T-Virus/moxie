# -*- coding: utf-8 -*-
"""统一预设接口：前端所有下拉/多选的枚举、分类、标签选项集中从此拉取。

返回按 type 分组；系统级预设（account_id 为 NULL，含内置与后台维护项）与当前账户
私有自定义预设一并返回。所有查询均走 SQLAlchemy ORM 参数化，无字符串拼接。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import Preset
from ..schemas import AdminPresetUpsert

router = APIRouter(tags=["presets"])


def _split_audience(raw: str | None) -> list[str]:
    parts = [a.strip() for a in (raw or "").split(",") if a.strip()]
    return parts or ["all"]


@router.get("/presets")
def list_presets(
    type: str | None = Query(default=None, max_length=64, description="单个预设类型"),
    types: str | None = Query(default=None, max_length=512, description="逗号分隔的多个类型"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    wanted: set[str] = set()
    if type and type.strip():
        wanted.add(type.strip())
    if types:
        wanted.update(t.strip() for t in types.split(",") if t.strip())

    condition = or_(Preset.account_id.is_(None), Preset.account_id == auth.account.id)
    stmt = select(Preset).where(condition)
    if wanted:
        stmt = stmt.where(Preset.type.in_(wanted))
    stmt = stmt.order_by(Preset.type, Preset.sort, Preset.value)
    rows = db.scalars(stmt).all()

    # 显式带上被请求但无数据的类型（空组），让前端能区分「服务端确实没有」
    # 与「接口没成功」，避免管理端清空/删除预设后前端又用本地硬编码常量补回来。
    groups: dict[str, list[dict]] = {t: [] for t in wanted}
    for r in rows:
        groups.setdefault(r.type, []).append(
            {
                "value": r.value,
                "label": r.label or r.value,
                "audience": _split_audience(r.audience),
                "custom": r.account_id is not None,
                "builtin": r.builtin,
            }
        )

    return {"groups": groups, "types": sorted(groups.keys())}


def _assert_custom_value(value: str) -> None:
    if not value or not value.strip() or any(ord(ch) < 32 for ch in value):
        raise ApiError(422, "invalid_preset", "预设值不能为空或包含控制字符")


@router.post("/presets", status_code=201)
def create_preset(
    payload: AdminPresetUpsert,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """新增当前用户私有自定义预设；与系统预设隔离，仅本人可见、可复用。"""
    _assert_custom_value(payload.value)
    dup = db.scalar(
        select(Preset.id)
        .where(
            Preset.type == payload.type,
            Preset.value == payload.value,
            Preset.account_id == auth.account.id,
        )
        .limit(1)
    )
    if dup is not None:
        raise ApiError(409, "preset_exists", "你已添加过该自定义预设值")
    row = Preset(
        type=payload.type,
        value=payload.value,
        label=payload.label,
        audience=payload.audience or "all",
        sort=0,
        builtin=False,
        account_id=auth.account.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "type": row.type,
        "value": row.value,
        "label": row.label or row.value,
        "custom": True,
    }


@router.delete("/presets/{preset_id}")
def delete_preset(
    preset_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    """删除当前用户自己的自定义预设；系统级预设不可由用户删除。"""
    row = db.get(Preset, preset_id)
    if row is None or row.account_id != auth.account.id:
        raise ApiError(404, "not_found", "预设不存在")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": preset_id}
