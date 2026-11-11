# -*- coding: utf-8 -*-
"""审计日志：所有写操作都要留痕（不含请求体与密钥）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog


def write_audit(
    session: Session,
    *,
    actor_id: int | None,
    action: str,
    request=None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip=(request.client.host if request is not None and request.client else None),
        ua=(request.headers.get("user-agent", "")[:255] if request is not None else None),
        meta=meta or {},
    )
    session.add(entry)
    return entry
