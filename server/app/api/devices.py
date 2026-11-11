# -*- coding: utf-8 -*-
"""设备注册与解绑：每账号最多 2 台（可配置）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..models import Device
from ..schemas import DeviceCreateRequest
from ..services.audit import write_audit
from ..services.license import revoke_device_licenses

router = APIRouter(prefix="/devices", tags=["devices"])


def _device_view(device: Device) -> dict:
    return {
        "id": device.id,
        "platform": device.platform,
        "name": device.name,
        "status": device.status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }


def _active_count(db: Session, account_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Device).where(
            Device.account_id == account_id, Device.status == "active"
        )
    ) or 0


@router.post("", status_code=201)
def register_device(
    payload: DeviceCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    now = utcnow()
    existing = db.scalar(
        select(Device).where(
            Device.account_id == auth.account.id,
            Device.device_hash == payload.device_hash,
        )
    )

    if existing is not None and existing.status == "active":
        existing.last_seen_at = now
        if payload.name:
            existing.name = payload.name
        db.commit()
        return {"device": _device_view(existing), "created": False}

    if _active_count(db, auth.account.id) >= settings.max_devices:
        raise ApiError(
            403,
            "device_limit_reached",
            f"设备数量已达上限（{settings.max_devices} 台），请先在旧设备解绑",
        )

    if existing is not None:
        # 重新绑定曾被解绑的设备
        existing.status = "active"
        existing.last_seen_at = now
        existing.platform = payload.platform
        existing.name = payload.name or existing.name
        db.flush()
        write_audit(db, actor_id=auth.account.id, action="device.rebind", request=request,
                    target_type="device", target_id=existing.id)
        db.commit()
        return {"device": _device_view(existing), "created": False}

    device = Device(
        account_id=auth.account.id,
        device_hash=payload.device_hash,
        platform=payload.platform,
        name=payload.name,
        last_seen_at=now,
        status="active",
    )
    db.add(device)
    db.flush()
    write_audit(db, actor_id=auth.account.id, action="device.register", request=request,
                target_type="device", target_id=device.id)
    db.commit()
    return {"device": _device_view(device), "created": True}


@router.get("")
def list_devices(
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Device).where(Device.account_id == auth.account.id).order_by(Device.id.asc())
    ).all()
    return {
        "max_devices": request.app.state.settings.max_devices,
        "devices": [_device_view(d) for d in rows],
    }


@router.delete("/{device_id}")
def remove_device(
    device_id: int,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    device = db.scalar(
        select(Device).where(Device.id == device_id, Device.account_id == auth.account.id)
    )
    if device is None:
        raise ApiError(404, "device_not_found", "设备不存在")
    if device.status == "revoked":
        return {"ok": True, "device": _device_view(device)}
    device.status = "revoked"
    revoke_device_licenses(db, auth.account.id, device.id)
    write_audit(db, actor_id=auth.account.id, action="device.revoke", request=request,
                target_type="device", target_id=device.id)
    db.commit()
    return {"ok": True, "device": _device_view(device)}
