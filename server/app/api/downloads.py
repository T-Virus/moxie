# -*- coding: utf-8 -*-
"""离线版安装包：登录后可下载 Windows / Android 安装包。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from ..deps import AuthContext, get_auth
from ..errors import ApiError

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


def _describe(platform: str, request: Request) -> dict:
    meta = PLATFORMS[platform]
    settings = request.app.state.settings
    path = _latest(getattr(settings, meta["dir_setting"]), meta["suffix"])
    item = {
        "platform": platform,
        "label": meta["label"],
        "available": path is not None,
        "requires_login": True,
        "download_url": f"{settings.api_prefix}/downloads/{platform}",
    }
    if path is not None:
        stat = path.stat()
        item.update(
            {
                "version": _version_of(path.name),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return item


@router.get("")
def list_downloads(request: Request):
    """安装包元数据（公开）：页面未登录时也能展示版本与大小。"""
    return {"items": [_describe(platform, request) for platform in PLATFORMS]}


@router.get("/{platform}")
def download(platform: str, request: Request, auth: AuthContext = Depends(get_auth)):
    """登录后才能下载安装包，避免裸链接被直接抓取。"""
    meta = PLATFORMS.get(platform)
    if meta is None:
        raise ApiError(404, "download_not_found", "下载项不存在")
    path = _latest(getattr(request.app.state.settings, meta["dir_setting"]), meta["suffix"])
    if path is None:
        raise ApiError(404, "download_unavailable", "安装包尚未发布")
    return FileResponse(path, media_type=meta["media_type"], filename=meta["filename"])
