# -*- coding: utf-8 -*-
"""用户数据权利：个人数据导出、注销申请、到期清除与对象存储级联清理。

边界：
  · 导出只取当前账号可见数据，密码哈希/令牌哈希/推送密钥不导出；
  · 注销不立即硬删：写申请 + 停登录 + 撤销会话，宽限期后由 scheduler 清除；
  · 清除逻辑与管理端硬删除共用 purge_account()，避免两条路径清理范围漂移；
  · 对象存储里的上传源文件、任务产物、Agent 产物与封面按账号全部删除。
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, inspect, or_, select, update

from ..config import Settings
from ..db import utcnow
from ..errors import ApiError
from ..models import (
    Account,
    AccountDeletionRequest,
    AuditLog,
    Base,
    Preset,
    RefreshSession,
    Task,
    TaskStep,
)
from .audit import write_audit
from .storage import Storage, book_slug, build_storage, task_prefix

logger = logging.getLogger("moxie.data_rights")

_MASK_FIELDS: dict[str, set[str]] = {
    "accounts": {"password_hash"},
    "email_verifications": {"token_hash"},
    "refresh_sessions": {"token_hash"},
    "web_push_subscriptions": {"p256dh", "auth"},
    "licenses": {"signature"},
}
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".log"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _row_to_dict(row, table_name: str) -> dict[str, Any]:
    masked = _MASK_FIELDS.get(table_name, set())
    mapper = inspect(row).mapper
    return {
        prop.key: ("[redacted]" if prop.key in masked and getattr(row, prop.key) else _jsonable(getattr(row, prop.key)))
        for prop in mapper.column_attrs
    }


def _orm_classes() -> dict[str, type]:
    return {
        mapper.class_.__tablename__: mapper.class_
        for mapper in Base.registry.mappers
        if hasattr(mapper.class_, "__tablename__")
    }


def _reachable_tables() -> dict[str, Any]:
    """从 accounts 沿外键「被引用」方向可达的表（含传递依赖）。"""
    tables = Base.metadata.tables
    relevant: dict[str, Any] = {}
    frontier = ["accounts"]
    while frontier:
        current = frontier.pop()
        for table in tables.values():
            if table.name == "accounts" or table.name in relevant:
                continue
            if any(fk.column.table.name == current for fk in table.foreign_keys):
                relevant[table.name] = table
                frontier.append(table.name)
    return relevant


def _scope_of(table: Any, account_id: int, relevant: dict[str, Any], _seen: frozenset[str] = frozenset()) -> Any:
    """圈定某表中属于该账号的行：直接 account_id，或沿已圈定的父表子查询。"""
    if table.name in _seen:
        return None
    seen = _seen | {table.name}
    for fk in table.foreign_keys:
        if fk.column.table.name == "accounts" and fk.column.name == "id":
            return fk.parent == account_id
    conds = []
    for fk in table.foreign_keys:
        parent = fk.column.table
        if parent.name == "accounts" or parent.name not in relevant:
            continue
        parent_scope = _scope_of(parent, account_id, relevant, seen)
        if parent_scope is not None:
            conds.append(fk.parent.in_(select(fk.column).where(parent_scope)))
    return or_(*conds) if conds else None


def _deletion_order(relevant: dict[str, Any]) -> list[str]:
    """A 引用 B ⇒ A 先删；异常成环时把剩余表追加到末尾兜底。"""
    indegree = {name: 0 for name in relevant}
    dependents: dict[str, list[str]] = {name: [] for name in relevant}
    for name, table in relevant.items():
        for fk in table.foreign_keys:
            ref = fk.column.table.name
            if ref != name and ref in relevant:
                dependents[name].append(ref)
                indegree[ref] += 1
    queue = [name for name, degree in indegree.items() if degree == 0]
    order: list[str] = []
    while queue:
        name = queue.pop()
        order.append(name)
        for ref in dependents[name]:
            indegree[ref] -= 1
            if indegree[ref] == 0:
                queue.append(ref)
    order.extend(name for name in relevant if name not in order)
    return order


def collect_object_keys(session, storage: Storage, account_id: int) -> list[str]:
    """收集账号名下的全部对象 key（上传源、任务产物、Agent 产物、封面）。"""
    keys: set[str] = set()

    for item in storage.list(f"uploads/{account_id}"):
        key = str(item.get("key") or "").replace("\\", "/").strip("/")
        if key.startswith(f"uploads/{account_id}/"):
            keys.add(key)

    tasks = session.scalars(select(Task).where(Task.account_id == account_id)).all()
    task_ids = [task.id for task in tasks]
    for task in tasks:
        for field in (task.input_artifact, task.output_artifact):
            if field:
                keys.add(str(field).replace("\\", "/").strip("/"))
        params = task.params if isinstance(task.params, dict) else {}
        book = str(params.get("book") or task.book_id or "book")
        for item in storage.list(task_prefix(book, task.id)):
            keys.add(str(item.get("key") or "").replace("\\", "/").strip("/"))

    if task_ids:
        for ref in session.scalars(select(TaskStep.output_ref).where(TaskStep.task_id.in_(task_ids))).all():
            if ref:
                keys.add(str(ref).replace("\\", "/").strip("/"))

    from ..models import AgentRun

    runs = session.scalars(select(AgentRun).where(AgentRun.account_id == account_id)).all()
    for run in runs:
        if run.source_key:
            keys.add(str(run.source_key).replace("\\", "/").strip("/"))
        meta = run.meta if isinstance(run.meta, dict) else {}
        slug = str(meta.get("book_slug") or book_slug(run.title))
        for prefix in (f"{slug}/{run.id}", f"covers/{account_id}/{run.id}"):
            for item in storage.list(prefix):
                keys.add(str(item.get("key") or "").replace("\\", "/").strip("/"))

    keys.discard("")
    return sorted(keys)


def _object_content_type(key: str) -> str:
    suffix = key.rsplit(".", 1)[-1].lower() if "." in key.rsplit("/", 1)[-1] else ""
    return {
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
        "json": "application/json",
        "csv": "text/csv; charset=utf-8",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def collect_account_data(
    session,
    account: Account,
    storage: Storage,
    settings: Settings,
) -> dict[str, Any]:
    """生成结构化个人数据快照；二进制内容受限内联，超出只给下载链接。"""
    relevant = _reachable_tables()
    classes = _orm_classes()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "exported_at": utcnow().isoformat(),
        "account": _row_to_dict(account, "accounts"),
    }

    for name, cls in classes.items():
        if name not in relevant:
            continue
        condition = _scope_of(relevant[name], account.id, relevant)
        if condition is None:
            continue
        rows = session.scalars(select(cls).where(condition)).all()
        payload[name] = [_row_to_dict(row, name) for row in rows]

    # AuditLog 用 actor_id 软关联，不在外键可达图内；按操作者与目标账号各取一次。
    audit_rows = session.scalars(
        select(AuditLog)
        .where(or_(AuditLog.actor_id == account.id, AuditLog.target_id == str(account.id)))
        .order_by(AuditLog.id)
    ).all()
    payload["audit_logs"] = [_row_to_dict(row, "audit_logs") for row in audit_rows]

    objects: list[dict[str, Any]] = []
    truncated = False
    keys = collect_object_keys(session, storage, account.id)
    max_objects = max(1, int(settings.account_export_max_objects))
    max_bytes = max(1, int(settings.account_export_object_max_bytes))
    for index, key in enumerate(keys):
        if index >= max_objects:
            truncated = True
            break
        item: dict[str, Any] = {"key": key, "content_type": _object_content_type(key)}
        try:
            data = storage.get_bytes(key)
            item["size"] = len(data)
            if len(data) <= max_bytes:
                ctype = item["content_type"]
                if ctype.startswith("text/") or ctype == "application/json":
                    item["content"] = data.decode("utf-8", errors="replace")
                else:
                    item["content_base64"] = base64.b64encode(data).decode("ascii")
            else:
                item["content_omitted"] = "object_exceeds_export_limit"
            item["download_url"] = storage.presign_get(key, settings.artifact_presign_seconds)
        except Exception as exc:  # noqa: BLE001 - 单个对象失败不影响整体导出
            item["error"] = type(exc).__name__
        objects.append(item)
    payload["objects"] = objects
    payload["objects_truncated"] = truncated
    payload["objects_total"] = len(keys)
    return payload


def deletion_view(row: AccountDeletionRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "status": row.status,
        "reason": row.reason,
        "requested_at": _jsonable(row.requested_at),
        "purge_at": _jsonable(row.purge_at),
        "cancelled_at": _jsonable(row.cancelled_at),
    }


def request_deletion(
    session,
    account: Account,
    *,
    request,
    settings: Settings,
    reason: str | None = None,
) -> dict[str, Any]:
    """提交注销申请：幂等；停登录、撤销全部会话，宽限期后统一清除。"""
    if account.role == "admin":
        raise ApiError(409, "admin_deletion_requires_admin_flow", "管理员账号请通过管理端流程处理")
    existing = session.scalar(
        select(AccountDeletionRequest).where(
            AccountDeletionRequest.account_id == account.id,
            AccountDeletionRequest.status == "pending",
        )
    )
    if existing is not None:
        return deletion_view(existing)

    now = utcnow()
    grace_days = max(1, int(settings.account_deletion_grace_days))
    row = AccountDeletionRequest(
        account_id=account.id,
        status="pending",
        reason=reason,
        requested_at=now,
        purge_at=now + timedelta(days=grace_days),
        meta={"grace_days": grace_days, "previous_status": account.status},
    )
    session.add(row)
    account.status = "closing"
    account.updated_at = now
    session.execute(
        update(RefreshSession)
        .where(RefreshSession.account_id == account.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    session.flush()
    write_audit(
        session,
        actor_id=account.id,
        action="account.deletion_requested",
        request=request,
        target_type="account",
        target_id=str(account.id),
        meta={"purge_at": row.purge_at.isoformat(), "grace_days": grace_days, "reason": reason},
    )
    return deletion_view(row)


def cancel_deletion(
    session,
    row: AccountDeletionRequest,
    *,
    request,
    actor_id: int,
) -> dict[str, Any]:
    """管理员撤销注销申请，账号恢复登录（需重新登录，原会话已撤销）。"""
    if row.status != "pending":
        raise ApiError(409, "deletion_request_not_pending", "该注销申请不是待处理状态")
    account = session.get(Account, row.account_id)
    if account is None:
        raise ApiError(404, "account_not_found", "账号不存在")
    now = utcnow()
    row.status = "cancelled"
    row.cancelled_at = now
    if account.status == "closing":
        previous_status = str((row.meta or {}).get("previous_status") or "active")
        account.status = previous_status
        account.updated_at = now
    write_audit(
        session,
        actor_id=actor_id,
        action="account.deletion_cancelled",
        request=request,
        target_type="account",
        target_id=str(account.id),
        meta={"deletion_request_id": row.id},
    )
    return deletion_view(row)


def purge_account(
    session,
    account: Account,
    *,
    actor_id: int | None,
    settings: Settings | None = None,
    storage: Storage | None = None,
    request=None,
    reason: str | None = None,
    audit_action: str = "user.delete",
) -> dict[str, Any]:
    """硬删除账号及其全部子数据、对象存储文件；供管理端与注销调度共用。"""
    if account.role == "admin":
        raise ApiError(409, "cannot_delete_admin", "不允许删除管理员账号")
    if actor_id is not None and actor_id == account.id:
        raise ApiError(409, "cannot_delete_self", "不能删除当前登录的账号")

    account_id = account.id
    email = account.email
    if storage is None:
        if settings is None:
            raise RuntimeError("purge_account 需要 settings 或 storage")
        storage = build_storage(settings, session=session)

    keys = collect_object_keys(session, storage, account_id)
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # noqa: BLE001 - 单个对象清理失败不阻断数据库级联
            logger.warning("账号清除时对象删除失败 account=%s key=%s", account_id, key)

    relevant = _reachable_tables()
    for name in _deletion_order(relevant):
        condition = _scope_of(relevant[name], account_id, relevant)
        if condition is not None:
            session.execute(sa_delete(relevant[name]).where(condition))

    # Preset 只有软关联 account_id，不在外键可达图内。
    session.execute(sa_delete(Preset).where(Preset.account_id == account_id))

    session.delete(account)
    write_audit(
        session,
        actor_id=actor_id,
        action=audit_action,
        request=request,
        target_type="account",
        target_id=str(account_id),
        meta={"email": email, "role": account.role, "reason": reason, "objects_deleted": len(keys)},
    )
    return {"account_id": account_id, "email": email, "objects_deleted": len(keys)}


def purge_due_deletions(
    session,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """清理到期的注销申请；单条失败回滚后继续，不让一个账号卡住整轮调度。"""
    now = now or utcnow()
    ids = session.scalars(
        select(AccountDeletionRequest.id)
        .where(
            AccountDeletionRequest.status == "pending",
            AccountDeletionRequest.purge_at <= now,
        )
        .limit(max(1, limit))
    ).all()
    done = 0
    for request_id in ids:
        row = session.get(AccountDeletionRequest, request_id)
        if row is None:
            continue
        account = session.get(Account, row.account_id)
        if account is None:
            row.status = "completed"
            session.commit()
            done += 1
            continue
        try:
            purge_account(
                session,
                account,
                actor_id=None,
                settings=settings,
                reason="account_deletion_request",
                audit_action="account.deleted",
            )
            session.commit()
            done += 1
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.exception("注销到期清除失败 account=%s", row.account_id)
    return done


def pending_deletion_count(session) -> int:
    return int(session.scalar(select(func.count()).select_from(AccountDeletionRequest).where(
        AccountDeletionRequest.status == "pending"
    )) or 0)
