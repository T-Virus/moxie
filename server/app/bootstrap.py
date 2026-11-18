# -*- coding: utf-8 -*-
"""管理员初始化：按邮箱白名单幂等提升已存在账号。

设计边界：
  · 不自动创建带默认口令的账号，避免把弱口令管理员带进生产；
  · 只提升已注册账号，写审计；重复执行不会重复落审计；
  · 供 lifespan 启动钩子与 scripts/bootstrap_admin.py 共用。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .db import utcnow
from .models import Account
from .services.audit import write_audit

logger = logging.getLogger("moxie.bootstrap")


def parse_admin_emails(raw: str | None) -> list[str]:
    """逗号/换行分隔的邮箱白名单，去空去重且保持顺序。"""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.replace("\n", ",").split(","):
        email = part.strip().lower()
        if email and email not in out:
            out.append(email)
    return out


def bootstrap_admin(session: Session, email: str, *, source: str = "env") -> dict[str, Any]:
    """提升一个已存在账号为管理员；返回可打印的结果字典。"""
    normalized = email.strip().lower()
    if not normalized:
        return {"email": normalized, "status": "invalid"}
    row = session.scalar(select_account(normalized))
    if row is None:
        return {"email": normalized, "status": "account_missing"}
    if row.role == "admin":
        return {"email": normalized, "status": "already_admin", "account_id": row.id}
    previous = row.role
    row.role = "admin"
    row.updated_at = utcnow()
    write_audit(
        session,
        actor_id=None,
        action="account.bootstrap_admin",
        target_type="account",
        target_id=row.id,
        meta={"email": normalized, "from_role": previous, "source": source},
    )
    session.commit()
    logger.info("管理员白名单生效 account=%s", row.id)
    return {"email": normalized, "status": "promoted", "account_id": row.id}


def select_account(email: str):
    """延迟导入 select，保持本模块可独立用于 CLI。"""
    from sqlalchemy import select

    return select(Account).where(Account.email == email)


def bootstrap_admins(session: Session, raw: str | None) -> list[dict[str, Any]]:
    """批量提升；返回每个邮箱的处理结果。"""
    results = []
    for email in parse_admin_emails(raw):
        try:
            results.append(bootstrap_admin(session, email))
        except Exception as exc:  # noqa: BLE001 - 启动钩子不能因单个账号失败而阻断
            session.rollback()
            logger.warning("管理员提升失败 email=%s error=%s", email, type(exc).__name__)
            results.append({"email": email, "status": "error", "error": type(exc).__name__})
    return results
