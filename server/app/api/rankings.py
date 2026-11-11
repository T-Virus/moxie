# -*- coding: utf-8 -*-
"""公开榜单：起点/番茄/纵横/晋江/红袖/潇湘排行榜元数据（只取书名/作者/排名/链接）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..deps import AuthContext, get_auth
from ..services.rankings import fetch_rankings_sync

router = APIRouter(tags=["rankings"])


@router.get("/rankings")
def list_rankings(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    genre: str | None = Query(default=None, max_length=32),
    audience: str | None = Query(default=None, pattern="^(male|female)$"),
    refresh: bool = Query(default=False),
    auth: AuthContext = Depends(get_auth),
):
    settings = request.app.state.settings
    items, sources = fetch_rankings_sync(
        settings, limit=limit, genre=genre, audience=audience, refresh=refresh
    )
    return {"enabled": settings.ranking_enabled, "items": items, "sources": sources}
