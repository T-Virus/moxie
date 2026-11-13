# -*- coding: utf-8 -*-
"""登录、刷新、登出。Refresh Token 轮换 + 服务端会话吊销。"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import AuthContext, client_ip as resolve_client_ip, get_auth
from ..errors import ApiError
from ..metrics import increment
from ..models import Account, EmailVerification, LegalConsent, RefreshSession
from ..schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    VerifyEmailRequest,
)
from ..security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    token_hash,
    verify_password,
)
from ..services.audit import write_audit
from ..services.notifications import send_verification_email

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
    ip = resolve_client_ip(request) or "-"
    allowed, retry_after = limiter.check(f"register:{ip}", settings.register_rate_limit_per_minute, 60)
    if not allowed:
        increment("moxie_rate_limited_total", scope="register")
        raise ApiError(429, "rate_limited", "注册过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
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
    if settings.email_verification_required and email:
        account.status = "pending"
        token, verify_url, sent = _create_verification(db, account, settings, request)
        db.commit()
        result: dict = {
            "status": "pending_verification",
            "email": email,
            "message": "验证邮件已发送，请前往邮箱点击链接完成验证后再登录。",
        }
        # 未真正发出（SMTP 未配置等）且非生产：把链接直接返回，方便本地验证
        if not sent and not settings.is_production:
            result["verify_url"] = verify_url
        return result
    result = _issue_tokens(db, request, account)
    db.commit()
    return result


def _create_verification(
    db: Session, account: Account, settings, request: Request
) -> tuple[str, str, bool]:
    """生成邮箱验证令牌并发送验证邮件；返回 (明文 token, 验证链接, 是否真正发出)。"""
    token = secrets.token_urlsafe(32)
    token_hash_value = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utcnow() + timedelta(minutes=settings.email_verify_token_ttl_minutes)
    row = EmailVerification(
        account_id=account.id, token_hash=token_hash_value, expires_at=expires_at
    )
    db.add(row)
    db.flush()
    origin = request.headers.get("origin") or str(request.base_url).rstrip("/")
    base = (settings.app_client_base_url or origin).rstrip("/")
    verify_url = f"{base}/verify-email?token={token}"
    subject = "验证你的墨写邮箱"
    body = (
        "欢迎注册墨写。请点击下面的链接完成邮箱验证"
        f"（{settings.email_verify_token_ttl_minutes} 分钟内有效）：\n\n{verify_url}\n\n"
        "如果这不是你本人的操作，请忽略此邮件。"
    )
    dedupe_key = f"email_verify:{account.id}:{row.id}"
    delivery = send_verification_email(
        db, account=account, subject=subject, body=body, settings=settings, dedupe_key=dedupe_key
    )
    sent = bool(delivery is not None and delivery.status == "sent")
    return token, verify_url, sent


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    token_hash_value = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    row = db.scalar(
        select(EmailVerification).where(EmailVerification.token_hash == token_hash_value)
    )
    if row is None:
        raise ApiError(400, "invalid_token", "验证链接无效或已使用")
    if row.consumed_at is not None:
        raise ApiError(409, "already_verified", "该邮箱已验证，请直接登录")
    if row.expires_at <= utcnow():
        raise ApiError(410, "token_expired", "验证链接已过期，请重新获取验证邮件")
    account = db.get(Account, row.account_id)
    if account is None:
        raise ApiError(400, "invalid_token", "验证链接无效")
    if account.status == "active":
        row.consumed_at = utcnow()
        db.commit()
        raise ApiError(409, "already_verified", "该邮箱已验证，请直接登录")
    account.status = "active"
    account.email_verified_at = utcnow()
    row.consumed_at = utcnow()
    write_audit(db, actor_id=account.id, action="account.email_verified", request=request,
                target_type="account", target_id=account.id)
    result = _issue_tokens(db, request, account)
    db.commit()
    return result


@router.post("/resend-verification")
def resend_verification(payload: ResendVerificationRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    ip = resolve_client_ip(request) or "-"
    allowed, retry_after = limiter.check(f"resend:{ip}", settings.register_rate_limit_per_minute, 60)
    if not allowed:
        increment("moxie_rate_limited_total", scope="resend")
        raise ApiError(429, "rate_limited", "发送过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
    email = payload.email.strip().lower()
    account = _lookup_account(db, email, None)
    # 不泄露账号是否存在：仅当存在且处于待验证才真正发信
    if account and account.status == "pending":
        # 同一账号两次验证邮件的最小间隔：防接口盗刷 / 邮件轰炸（独立于 IP 限速）
        latest = db.scalar(
            select(EmailVerification)
            .where(EmailVerification.account_id == account.id)
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
        if latest is not None and latest.created_at > utcnow() - timedelta(
            seconds=settings.email_resend_cooldown_seconds
        ):
            raise ApiError(429, "too_frequent", "验证邮件发送过于频繁，请稍后再试")
        token, verify_url, sent = _create_verification(db, account, settings, request)
        db.commit()
        if not sent and not settings.is_production:
            return {
                "status": "pending_verification",
                "email": email,
                "message": "验证邮件已重新发送，请查收。",
                "verify_url": verify_url,
            }
    return {
        "status": "ok",
        "email": email,
        "message": "若该邮箱已注册且未验证，验证邮件已重新发送。",
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    ip = resolve_client_ip(request) or "-"
    allowed, retry_after = limiter.check(f"login:{ip}", settings.login_rate_limit_per_minute, 60)
    if not allowed:
        increment("moxie_rate_limited_total", scope="login")
        raise ApiError(429, "rate_limited", "登录尝试过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})

    # 账号维度的失败锁定：窗口内连续输错达到上限即拒绝，防止针对固定账号撞库。
    # 与上面的 IP 限流互补（IP 防刷量，本项防撞库）；登录成功即清零。
    identity = (payload.email or payload.phone or "").strip()
    if payload.email:
        identity = identity.lower()
    fail_key = f"login_fail:{identity or ip}"
    failed, lock_ttl = limiter.status(fail_key)
    if settings.login_failure_limit > 0 and failed >= settings.login_failure_limit:
        increment("moxie_rate_limited_total", scope="login_failure")
        raise ApiError(
            429, "too_many_attempts", "密码错误次数过多，请稍后再试",
            headers={"Retry-After": str(lock_ttl or settings.login_failure_window_seconds)},
        )

    account = _lookup_account(db, payload.email, payload.phone)
    if account is None or not verify_password(payload.password, account.password_hash):
        limiter.check(fail_key, settings.login_failure_limit, settings.login_failure_window_seconds)
        raise ApiError(401, "invalid_credentials", "账号或密码错误")
    if account.status != "active":
        if account.status == "pending":
            raise ApiError(403, "email_not_verified", "账号邮箱尚未验证，请先查收验证邮件完成验证后再登录")
        raise ApiError(403, "account_disabled", "账号已被停用")
    limiter.reset(fail_key)
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
