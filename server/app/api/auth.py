# -*- coding: utf-8 -*-
"""登录、刷新、登出。Refresh Token 轮换 + 服务端会话吊销。"""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..metrics import increment
from ..models import Account, LegalConsent, RefreshSession
from ..schemas import LoginRequest, RefreshRequest, RegisterRequest
from ..security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    token_hash,
    verify_password,
)
from ..services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

REQUIRED_CONSENTS = ("terms", "privacy")


def _require_consents(payload: RegisterRequest, settings) -> None:
    """注册必须显式同意当前版本的用户协议与隐私政策，缺失/版本不符即 422。

    测试环境 legal_gate_enabled=False 时跳过，便于既有用例无感运行。
    """
    if not settings.legal_gate_enabled:
        return
    consents = payload.consents or {}
    for consent_type in REQUIRED_CONSENTS:
        entry = consents.get(consent_type)
        if entry is None or not entry.accepted or entry.version != settings.legal_terms_version:
            raise ApiError(
                422,
                "legal_consent_required",
                "注册前须阅读并同意当前版本的《用户协议》与《隐私政策》",
            )


def _account_view(account: Account) -> dict:
    return {
        "id": account.id,
        "email": account.email,
        "phone": account.phone,
        "status": account.status,
        "role": account.role,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def _issue_tokens(
    db: Session, request: Request, account: Account, *, device_id: int | None = None,
    rotated_from: str | None = None,
) -> dict:
    settings = request.app.state.settings
    session_id = uuid.uuid4().hex
    refresh_token = create_refresh_token(settings, account.id, session_id, device_id)
    row = RefreshSession(
        account_id=account.id,
        device_id=device_id,
        session_id=session_id,
        token_hash=token_hash(refresh_token),
        expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        rotated_from=rotated_from,
    )
    db.add(row)
    access_token = create_access_token(settings, account.id, session_id, device_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_minutes * 60,
        "refresh_expires_in": settings.refresh_token_days * 86400,
        "account": _account_view(account),
    }


def _lookup_account(db: Session, email: str | None, phone: str | None) -> Account | None:
    conditions = []
    if email:
        conditions.append(Account.email == email.strip().lower())
    if phone:
        conditions.append(Account.phone == phone.strip())
    if not conditions:
        return None
    return db.scalar(select(Account).where(or_(*conditions)))


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    ip = request.client.host if request.client else "-"
    if not limiter.allow(
        f"register:{ip}", settings.register_rate_limit_per_minute, 60
    ):
        increment("moxie_rate_limited_total", scope="register")
        raise ApiError(429, "rate_limited", "注册过于频繁，请稍后再试")
    _require_consents(payload, settings)
    email = payload.email.strip().lower() if payload.email else None
    phone = payload.phone.strip() if payload.phone else None
    if _lookup_account(db, email, phone) is not None:
        raise ApiError(409, "account_exists", "该邮箱或手机号已注册")
    account = Account(email=email, phone=phone, password_hash=hash_password(payload.password))
    db.add(account)
    db.flush()
    if settings.legal_gate_enabled:
        user_agent = (request.headers.get("user-agent") or "")[:255]
        client_ip = request.client.host if request.client else None
        for consent_type in REQUIRED_CONSENTS:
            db.add(
                LegalConsent(
                    account_id=account.id,
                    consent_type=consent_type,
                    version=settings.legal_terms_version,
                    accepted_at=utcnow(),
                    ip=client_ip,
                    user_agent=user_agent,
                )
            )
    write_audit(db, actor_id=account.id, action="account.register", request=request,
                target_type="account", target_id=account.id)
    result = _issue_tokens(db, request, account)
    db.commit()
    return result


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    ip = request.client.host if request.client else "-"
    if not limiter.allow(f"login:{ip}", settings.login_rate_limit_per_minute, 60):
        increment("moxie_rate_limited_total", scope="login")
        raise ApiError(429, "rate_limited", "登录尝试过于频繁，请稍后再试")
    account = _lookup_account(db, payload.email, payload.phone)
    if account is None or not verify_password(payload.password, account.password_hash):
        raise ApiError(401, "invalid_credentials", "账号或密码错误")
    if account.status != "active":
        raise ApiError(403, "account_disabled", "账号已被停用")
    write_audit(db, actor_id=account.id, action="account.login", request=request,
                target_type="account", target_id=account.id)
    result = _issue_tokens(db, request, account)
    db.commit()
    return result


@router.post("/refresh")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    try:
        decoded = jwt.decode(payload.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "refresh_expired", "Refresh Token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise ApiError(401, "invalid_refresh", "Refresh Token 无效")
    if decoded.get("typ") != "refresh":
        raise ApiError(401, "invalid_refresh", "Token 类型不对")

    session_id = decoded.get("sid") or ""
    row = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(payload.refresh_token)))
    if (
        row is None
        or row.session_id != session_id
        or row.revoked_at is not None
        or row.expires_at <= utcnow()
    ):
        raise ApiError(401, "invalid_refresh", "Refresh Token 已失效，请重新登录")

    account = db.get(Account, row.account_id)
    if account is None or account.status != "active":
        raise ApiError(401, "account_disabled", "账号不存在或已停用")

    row.revoked_at = utcnow()
    result = _issue_tokens(
        db, request, account, device_id=row.device_id, rotated_from=session_id
    )
    db.commit()
    return result


@router.post("/logout")
def logout(
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    row = db.scalar(select(RefreshSession).where(RefreshSession.session_id == auth.session_id))
    if row is not None:
        row.revoked_at = utcnow()
    write_audit(db, actor_id=auth.account.id, action="account.logout", request=request,
                target_type="session", target_id=auth.session_id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(auth: AuthContext = Depends(get_auth)):
    return _account_view(auth.account)
