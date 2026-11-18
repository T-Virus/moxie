# -*- coding: utf-8 -*-
"""合规闸门：参考改编的权利校验与法律留痕。

设计要点：
- 明文头 X-Rights-Confirmed 可被任意伪造，只能当"旧客户端兼容回退"，
  且必须标注来源，不能等同于可信声明。
- 结构化声明走加密 body（/v1/agent-runs 未豁免 payload 加密），服务端可信。
- 每次通过闸门都写 LegalConsent（版本化、可导出审计）+ AuditLog（含 basis/IP/UA）。
- 重复同意按 (account, consent_type, version) 唯一键幂等，不重复插行。

业务语义：用户对上传的他人作品声称有权改编，并确认知悉 AIGC 披露义务。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..deps import client_ip
from ..errors import ApiError
from ..models import LegalConsent
from ..schemas import RightsDeclaration
from .audit import write_audit

CONSENT_TYPE = "rights_adaptation"


def _header_confirmed(request) -> bool:
    return (request.headers.get("x-rights-confirmed", "") or "").lower() in ("1", "true", "yes")


def enforce_rights_declaration(
    db: Session,
    *,
    request,
    account_id: int,
    settings,
    declaration: RightsDeclaration | None,
    source_key: str | None = None,
    task_id: str | int | None = None,
    legal_gate_enabled: bool | None = None,
    action: str = "rights.consent",
    legacy_confirmed: bool = False,
) -> dict:
    """校验参考改编的权利声明并落法律留痕。

    Returns: 供 Task.params / 审计 / 响应复用的声明摘要。
    Raises: ApiError(422, rights_confirmation_required) 当闸门开启且声明缺失/无效。
    """
    enabled = settings.legal_gate_enabled if legal_gate_enabled is None else legal_gate_enabled
    if not enabled:
        return {"rights_confirmed": False, "consent_recorded": False}

    if declaration is not None:
        # Pydantic 已校验 basis 枚举与两个 Must-be-true 字段；取可信来源。
        basis = declaration.basis
        ai_notice_ack = declaration.ai_notice_ack
        source = "encrypted_body"
        note = declaration.note
    elif _header_confirmed(request) or legacy_confirmed:
        # 兼容回退：来源标注为明文头/旧参数，审计可见，不能视为强声明。
        basis = "header_legacy"
        ai_notice_ack = False
        source = "plaintext_header"
        note = None
    else:
        raise ApiError(
            422,
            "rights_confirmation_required",
            "参考改编前必须声明作品权利来源并确认 AIGC 标注义务",
        )

    # LegalConsent 幂等写入：(account, type, version) 唯一
    existing = db.scalar(
        select(LegalConsent).where(
            LegalConsent.account_id == account_id,
            LegalConsent.consent_type == CONSENT_TYPE,
            LegalConsent.version == settings.legal_terms_version,
        )
    )
    if existing is None:
        db.add(
            LegalConsent(
                account_id=account_id,
                consent_type=CONSENT_TYPE,
                version=settings.legal_terms_version,
                accepted_at=utcnow(),
                ip=client_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:255],
            )
        )

    write_audit(
        db,
        actor_id=account_id,
        action=action,
        request=request,
        target_type="rights_consent",
        target_id=task_id or source_key,
        meta={
            "basis": basis,
            "ai_notice_ack": ai_notice_ack,
            "source": source,
            "source_key": source_key,
            "terms_version": settings.legal_terms_version,
            "note": note,
        },
    )
    return {
        "rights_confirmed": True,
        "basis": basis,
        "ai_notice_ack": ai_notice_ack,
        "source": source,
        "terms_version": settings.legal_terms_version,
        "consent_recorded": True,
    }
