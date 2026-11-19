# -*- coding: utf-8 -*-
"""忘记密码 / 重置密码：令牌签发、校验、消费与会话吊销。

与邮箱验证共用同一套「只存哈希 + 邮件链接」的思路，但独立成表：
验证邮箱与重置密码互不影响，任何一方消费都不会误伤另一方。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..deps import client_ip
from ..errors import ApiError
from ..models import Account, PasswordResetToken, RefreshSession
from .notifications import send_verification_email

# 用户端用 history 路由（/reset-password），管理端用 hash 路由且挂在 /admin 前缀下
# （/admin/#/reset-password）；两条链路必须区分，避免管理员收到用户端链接。
RESET_PATH_WEB = "/reset-password"
RESET_PATH_ADMIN = "/#/reset-password"
VALID_CHANNELS = {"web", "admin"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def latest_sent_at(db: Session, account_id: int) -> datetime | None:
    """该账号最近一次重置令牌的签发时间，用于发送冷却判断。"""
    return db.scalar(
        select(PasswordResetToken.created_at)
        .where(PasswordResetToken.account_id == account_id)
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
    )


def build_url(settings, request: Request, token: str, channel: str = "web") -> str:
    """按来源渠道拼重置链接。

    web：用户端 history 路由，基地址取 app_client_base_url；
    admin：管理端 hash 路由（含 /admin 前缀），基地址取 app_admin_base_url。
    两者都留空时回退请求 Origin，便于本地/单前端部署。
    """
    channel = channel if channel in VALID_CHANNELS else "web"
    origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
    if channel == "admin":
        base = (getattr(settings, "app_admin_base_url", "") or origin).rstrip("/")
        path = RESET_PATH_ADMIN
    else:
        base = (settings.app_client_base_url or origin).rstrip("/")
        path = RESET_PATH_WEB
    return f"{base}{path}?token={token}"


def issue(
    db: Session, account: Account, settings, request: Request, channel: str = "web"
) -> tuple[str, str, bool]:
    """签发重置令牌并发送邮件，返回 (明文 token, 重置链接, 是否真正发出)。"""
    token = secrets.token_urlsafe(32)
    ttl = max(1, settings.password_reset_token_ttl_minutes)
    row = PasswordResetToken(
        account_id=account.id,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(minutes=ttl),
        ip=client_ip(request),
    )
    db.add(row)
    db.flush()
    url = build_url(settings, request, token, channel)
    body = (
        "我们收到了重置墨写密码的请求。请点击下面的链接设置新密码"
        f"（{ttl} 分钟内有效，仅可使用一次）：\n\n{url}\n\n"
        "如果这不是你本人的操作，请忽略此邮件，你的密码不会改变。"
    )
    delivery = send_verification_email(
        db,
        account=account,
        subject="重置你的墨写密码",
        body=body,
        settings=settings,
        dedupe_key=f"password_reset:{account.id}:{row.id}",
        category="password_reset",
    )
    sent = bool(delivery is not None and delivery.status == "sent")
    return token, url, sent


def consume(db: Session, token: str) -> PasswordResetToken:
    """校验令牌并返回记录；无效/已用/过期分别给出可区分的错误码。"""
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(token)))
    if row is None:
        raise ApiError(400, "invalid_token", "重置链接无效，请重新申请")
    if row.consumed_at is not None:
        raise ApiError(409, "token_used", "重置链接已使用，请重新申请")
    if row.expires_at <= utcnow():
        raise ApiError(410, "token_expired", "重置链接已过期，请重新申请")
    return row


def invalidate_other_tokens(db: Session, account_id: int, keep_id: int) -> None:
    """重置成功后作废该账号其它未使用的重置令牌，避免旧邮件继续可用。"""
    rows = db.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.account_id == account_id,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.id != keep_id,
        )
    ).all()
    now = utcnow()
    for row in rows:
        row.consumed_at = now


def revoke_sessions(db: Session, account_id: int, keep_session_id: str | None = None) -> int:
    """吊销账号的全部有效会话；keep_session_id 用于修改密码时保留当前设备。"""
    stmt = select(RefreshSession).where(
        RefreshSession.account_id == account_id,
        RefreshSession.revoked_at.is_(None),
    )
    if keep_session_id:
        stmt = stmt.where(RefreshSession.session_id != keep_session_id)
    rows = db.scalars(stmt).all()
    now = utcnow()
    for row in rows:
        row.revoked_at = now
    return len(rows)


def check_cooldown(db: Session, account_id: int, settings) -> None:
    """同一账号两次重置邮件的最小间隔，防邮件轰炸。"""
    cooldown = settings.password_reset_cooldown_seconds
    if cooldown <= 0:
        return
    last = latest_sent_at(db, account_id)
    if last is not None and last > utcnow() - timedelta(seconds=cooldown):
        raise ApiError(429, "too_frequent", "重置邮件发送过于频繁，请稍后再试")
