# -*- coding: utf-8 -*-
"""鉴权依赖：所有写接口都要求登录；资源按 account_id 隔离。"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import ApiError
from .models import Account, RefreshSession
from .security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthContext:
    account: Account
    session_id: str
    device_id: int | None


def get_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise ApiError(401, "unauthorized", "需要登录（缺少 Bearer Token）")
    settings = request.app.state.settings
    try:
        payload = decode_token(credentials.credentials, settings, "access")
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "Access Token 已过期")
    except jwt.InvalidTokenError:
        raise ApiError(401, "invalid_token", "Access Token 无效")

    try:
        account_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise ApiError(401, "invalid_token", "Access Token 无效")

    account = db.get(Account, account_id)
    if account is None or account.status != "active":
        raise ApiError(401, "account_disabled", "账号不存在或已停用")

    session_id = payload.get("sid") or ""
    session = db.scalar(select(RefreshSession).where(RefreshSession.session_id == session_id))
    if session is None or session.revoked_at is not None:
        raise ApiError(401, "session_revoked", "登录会话已失效，请重新登录")

    return AuthContext(account=account, session_id=session_id, device_id=payload.get("dev"))


def get_current_account(auth: AuthContext = Depends(get_auth)) -> Account:
    return auth.account


def require_admin(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "admin":
        raise ApiError(403, "admin_required", "需要管理员权限")
    return account


def require_staff(account: Account = Depends(get_current_account)) -> Account:
    """admin 或 support 可读；写操作单独用 require_admin。"""
    if account.role not in ("admin", "support"):
        raise ApiError(403, "staff_required", "需要管理员或客服权限")
    return account


def client_ip(request: Request) -> str | None:
    # 默认只取直连对端 IP；仅当显式信任代理时才解析 X-Forwarded-For，
    # 否则客户端可伪造 XFF 让每次请求都"换 IP"，绕过基于 IP 的限流与失败锁定。
    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "trust_proxy", False):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
