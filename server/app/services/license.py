# -*- coding: utf-8 -*-
"""离线 License：Ed25519 签名的权益快照。

时间窗口：
  issued_at ── refresh_after（7 天，建议联网刷新）── expires_at（7 天）── grace_until（再 +14 天，宽限可用）── 失效
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import Device, License, Subscription
from ..security import LicenseSigner
from . import subscription as subsvc


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def device_for(session: Session, account_id: int, device_id: int) -> Device:
    device = session.scalar(
        select(Device).where(Device.id == device_id, Device.account_id == account_id)
    )
    if device is None:
        raise ApiError(404, "device_not_found", "设备不存在或不属于当前账号")
    if device.status != "active":
        raise ApiError(403, "device_revoked", "设备已解绑，请重新注册")
    return device


def issue_license(
    session: Session,
    *,
    account_id: int,
    device_id: int,
    settings: Settings,
    signer: LicenseSigner,
    now: datetime | None = None,
) -> dict:
    now = now or utcnow()
    device = device_for(session, account_id, device_id)

    sub: Subscription | None = subsvc.get_active_subscription(session, account_id)
    if sub is None:
        raise ApiError(402, "no_active_subscription", "没有生效中的订阅，无法签发 License")
    plan = subsvc.get_plan(session, sub.plan_id)
    entitlements = subsvc.get_entitlements(session, plan.id)

    expires_at = now + timedelta(days=settings.license_refresh_days)
    grace_until = expires_at + timedelta(days=settings.license_grace_days)
    payload = {
        "v": 1,
        "key_id": signer.key_id,
        "account_id": account_id,
        "device_id": device.id,
        "device_hash": device.device_hash,
        "plan_code": plan.code,
        "plan_name": plan.name,
        "features": plan.features or {},
        "entitlements": {k: v.limit_value for k, v in entitlements.items()},
        "subscription_status": sub.status,
        "issued_at": _iso(now),
        "refresh_after": _iso(expires_at),
        "expires_at": _iso(expires_at),
        "grace_until": _iso(grace_until),
        "nonce": secrets.token_hex(8),
    }
    signature = signer.sign(payload)

    row = License(
        account_id=account_id,
        device_id=device.id,
        key_id=signer.key_id,
        payload=payload,
        signature=signature,
        issued_at=now,
        expires_at=expires_at,
        refresh_after=expires_at,
        grace_until=grace_until,
    )
    session.add(row)
    session.flush()

    device.last_seen_at = now
    return {
        "license": payload,
        "signature": signature,
        "key_id": signer.key_id,
        "public_key": signer.public_key_b64,
        "expires_at": payload["expires_at"],
        "refresh_after": payload["refresh_after"],
        "grace_until": payload["grace_until"],
        "license_id": row.id,
    }


def verify_license(
    payload: dict,
    signature: str,
    *,
    signer: LicenseSigner,
    now: datetime | None = None,
) -> dict:
    now = now or utcnow()
    if payload.get("key_id") != signer.key_id or not signer.verify(payload, signature):
        return {"valid": False, "status": "invalid", "reason": "签名校验失败"}

    try:
        expires_at = datetime.fromisoformat(payload["expires_at"])
        grace_until = datetime.fromisoformat(payload["grace_until"])
        refresh_after = datetime.fromisoformat(payload["refresh_after"])
    except (KeyError, ValueError):
        return {"valid": False, "status": "invalid", "reason": "时间字段缺失或格式错误"}

    if now > grace_until:
        return {"valid": False, "status": "expired", "reason": "已超过宽限期"}
    if now > expires_at:
        return {"valid": True, "status": "grace", "reason": "已过期，处于宽限期，请联网刷新"}
    if now >= refresh_after:
        return {"valid": True, "status": "refresh_required", "reason": "建议联网刷新 License"}
    return {"valid": True, "status": "ok", "reason": ""}


def revoke_device_licenses(session: Session, account_id: int, device_id: int, now: datetime | None = None) -> int:
    now = now or utcnow()
    rows = session.scalars(
        select(License).where(
            License.account_id == account_id,
            License.device_id == device_id,
            License.revoked_at.is_(None),
        )
    ).all()
    for row in rows:
        row.revoked_at = now
    return len(rows)
