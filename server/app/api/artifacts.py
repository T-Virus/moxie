# -*- coding: utf-8 -*-
"""产物列表、预签名下载与数据库/本地 fallback 下载。"""

from __future__ import annotations

import posixpath
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..services.storage import DBStorage, LocalStorage, task_prefix
from ..services.tasks import get_task

router = APIRouter(prefix="/tasks", tags=["artifacts"])
public_router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _prefix(task) -> str:
    book = (task.params or {}).get("book") or task.book_id or "book"
    return task_prefix(str(book), task.id)


@router.get("/{task_id}/artifacts")
def list_artifacts(
    task_id: str,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    task = get_task(db, auth.account.id, task_id)
    storage = request.app.state.storage
    prefix = _prefix(task)
    items = storage.list(prefix)
    expires = request.app.state.settings.artifact_presign_seconds
    for item in items:
        item["download_url"] = storage.presign_get(item["key"], expires=expires)
    return {"prefix": prefix, "artifacts": items, "count": len(items)}


@router.get("/{task_id}/artifacts/download")
def presign_artifact(
    task_id: str,
    request: Request,
    key: str = Query(..., min_length=1),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    task = get_task(db, auth.account.id, task_id)
    prefix = _prefix(task)
    if not key.startswith(prefix + "/"):
        raise ApiError(403, "artifact_forbidden", "产物不属于该任务")
    storage = request.app.state.storage
    if not storage.exists(key):
        raise ApiError(404, "artifact_not_found", "产物不存在")
    return {"url": storage.presign_get(key, expires=request.app.state.settings.artifact_presign_seconds)}


@public_router.get("/download")
def local_download(
    request: Request,
    key: str = Query(..., min_length=1),
    expires: int = Query(..., ge=0),
    sig: str = Query(..., min_length=8),
):
    """仅数据库 / 本地磁盘后端使用：校验 HMAC 签名后返回文件。"""
    storage = request.app.state.storage
    if not isinstance(storage, (DBStorage, LocalStorage)):
        raise ApiError(404, "artifact_not_found", "当前存储不支持本地下载")
    if not storage.verify(key, expires, sig):
        raise ApiError(403, "artifact_signature_invalid", "下载链接无效或已过期")
    name = posixpath.basename(key) or "artifact"
    if isinstance(storage, LocalStorage):
        path = storage._path(key)
        if not path.is_file():
            raise ApiError(404, "artifact_not_found", "产物不存在")
        return FileResponse(path, filename=name)
    data = storage.get_bytes(key)
    ascii_name = name.encode("ascii", "ignore").decode() or "artifact"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content=data,
        media_type=storage.content_type_of(key),
        headers={"Content-Disposition": disposition},
    )
