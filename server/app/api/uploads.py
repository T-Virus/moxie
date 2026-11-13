# -*- coding: utf-8 -*-
"""源文件上传：鉴权 + 限频 + 大小/扩展名校验 + 流式写对象存储。

用法：
    POST /v1/uploads        multipart/form-data，字段名 file → {"source_key": ...}
    DELETE /v1/uploads?key=uploads/<account_id>/...  → 删除自己的上传

任务创建时把 source_key 放进 params 即可（与 source_path 兼容）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth, client_ip
from ..errors import ApiError
from ..metrics import increment
from ..services.audit import write_audit
from ..services.uploads import delete_upload, save_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", status_code=201)
def upload_source(
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    allowed, retry_after = limiter.check(
        f"upload:{auth.account.id}", settings.upload_rate_limit_per_minute, 60
    )
    if not allowed:
        increment("moxie_upload_rejected_total", reason="rate_limited")
        raise ApiError(429, "rate_limited", "上传过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})

    if not file.filename:
        increment("moxie_upload_rejected_total", reason="missing_filename")
        raise ApiError(422, "invalid_filename", "缺少文件名")
    declared_size = getattr(file, "size", None)
    if declared_size is not None and declared_size > settings.upload_max_bytes:
        increment("moxie_upload_rejected_total", reason="too_large")
        raise ApiError(
            413, "source_too_large", f"源文件超过大小限制（{settings.upload_max_bytes} 字节）"
        )

    try:
        saved = save_upload(
            request.app.state.storage,
            settings,
            account_id=auth.account.id,
            filename=file.filename,
            fileobj=file.file,
        )
    except ApiError as exc:
        increment("moxie_upload_rejected_total", reason=exc.code)
        raise

    write_audit(
        db,
        actor_id=auth.account.id,
        action="upload.create",
        request=request,
        target_type="upload",
        target_id=saved["source_key"][:64],
        meta={
            "key": saved["source_key"],
            "filename": saved["filename"],
            "size": saved["size"],
            "ip": client_ip(request),
        },
    )
    db.commit()
    increment("moxie_uploads_total")
    increment("moxie_upload_bytes_total", saved["size"])
    return saved


@router.delete("")
def delete_source(
    request: Request,
    key: str = Query(..., min_length=1),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    if not delete_upload(request.app.state.storage, auth.account.id, key):
        raise ApiError(404, "upload_not_found", "上传文件不存在")
    write_audit(
        db,
        actor_id=auth.account.id,
        action="upload.delete",
        request=request,
        target_type="upload",
        target_id=key[:64],
        meta={"key": key},
    )
    db.commit()
    increment("moxie_uploads_deleted_total")
    return {"deleted": True, "key": key}
