# -*- coding: utf-8 -*-
"""License 接口：签发、公钥、离线校验。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth
from ..schemas import LicenseVerifyRequest
from ..services.audit import write_audit
from ..services.license import issue_license, verify_license

router = APIRouter(prefix="/license", tags=["license"])


@router.get("")
def get_license(
    request: Request,
    device_id: int = Query(..., ge=1, description="设备 ID，通过 /v1/devices 获取"),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    signer = request.app.state.license_signer
    result = issue_license(
        db,
        account_id=auth.account.id,
        device_id=device_id,
        settings=settings,
        signer=signer,
    )
    write_audit(db, actor_id=auth.account.id, action="license.issue", request=request,
                target_type="device", target_id=device_id,
                meta={"key_id": result["key_id"]})
    db.commit()
    return result


@router.get("/public-key")
def public_key(request: Request):
    signer = request.app.state.license_signer
    return {
        "key_id": signer.key_id,
        "algorithm": "ed25519",
        "public_key": signer.public_key_b64,
        "encoding": "base64url (raw 32 bytes)",
    }


@router.post("/verify")
def verify(payload: LicenseVerifyRequest, request: Request):
    return verify_license(
        payload.payload,
        payload.signature,
        signer=request.app.state.license_signer,
    )
