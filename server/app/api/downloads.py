# -*- coding: utf-8 -*-
"""离线版安装包：登录后可下载 Windows / Android 安装包。

解析优先级：后台上传纳管（offline_packages 表中 is_active 的版本）→ 目录式最新构建（回退）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import OfflinePackage

router = APIRouter(prefix="/downloads", tags=["downloads"])

PLATFORMS = {
    "windows": {
        "label": "Windows 离线版",
        "suffix": ".exe",
        "dir_setting": "offline_windows_dir",
        "filename": "墨写-Windows离线版.exe",
        "media_type": "application/vnd.microsoft.portable-executable",
    },
    "android": {
        "label": "Android 离线版",
        "suffix": ".apk",
        "dir_setting": "offline_android_dir",
        "filename": "墨写-Android离线版.apk",
        "media_type": "application/vnd.android.package-archive",
    },
}

VERSION_RE = re.compile(r"v(\d+(?:\.\d+)*)", re.IGNORECASE)


def _active_package(db: Session, platform: str) -> OfflinePackage | None:
    return db.scalars(
        select(OfflinePackage)
        .where(OfflinePackage.platform == platform, OfflinePackage.is_active.is_(True))
        .order_by(OfflinePackage.created_at.desc())
    ).first()


def _latest(directory: str, suffix: str) -> Path | None:
    base = Path(directory)
    if not base.is_dir():
        return None
    candidates = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() == suffix]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _version_of(name: str) -> str:
    matched = VERSION_RE.search(name)
    return matched.group(1) if matched else ""


def _describe(platform: str, request: Request, db: Session) -> dict:
    meta = PLATFORMS[platform]
    settings = request.app.state.settings
    item = {
        "platform": platform,
        "label": meta["label"],
        "available": False,
        "requires_login": True,
        "download_url": f"{settings.api_prefix}/downloads/{platform}",
    }
    # 1) 后台上传纳管的当前版本优先
    pkg = _active_package(db, platform)
    if pkg is not None:
        item.update(
            available=True,
            version=pkg.version,
            size=pkg.size,
            updated_at=pkg.updated_at.isoformat() if pkg.updated_at else None,
        )
        return item
    # 2) 回退到目录式最新构建
    path = _latest(getattr(settings, meta["dir_setting"]), meta["suffix"])
    if path is not None:
        stat = path.stat()
        item.update(
            available=True,
            version=_version_of(path.name),
            size=stat.st_size,
            updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        )
    return item


@router.get("")
def list_downloads(request: Request, db: Session = Depends(get_db)):
    """安装包元数据（公开）：页面未登录时也能展示版本与大小。"""
    return {"items": [_describe(platform, request, db) for platform in PLATFORMS]}


@router.get("/{platform}")
def download(platform: str, request: Request, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """登录后才能下载安装包，避免裸链接被直接抓取。"""
    meta = PLATFORMS.get(platform)
    if meta is None:
        raise ApiError(404, "download_not_found", "下载项不存在")
    # 1) 后台上传纳管的当前版本
    pkg = _active_package(db, platform)
    if pkg is not None:
        storage = request.app.state.storage
        data = storage.get_bytes(pkg.source_key)
        name = pkg.filename or meta["filename"]
        ctype = pkg.content_type or meta["media_type"]
        ascii_name = name.encode("ascii", "ignore").decode() or "package"
        disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        return Response(content=data, media_type=ctype, headers={"Content-Disposition": disposition})
    # 2) 回退到目录式最新构建
    path = _latest(getattr(request.app.state.settings, meta["dir_setting"]), meta["suffix"])
    if path is None:
        raise ApiError(404, "download_unavailable", "安装包尚未发布")
    return FileResponse(path, media_type=meta["media_type"], filename=meta["filename"])
