# -*- coding: utf-8 -*-
"""数据库备份 / 恢复服务：admin API 与 scheduler 共用。

设计边界：
  · 备份与产物分离，只备份数据库；S3/本地产物卷仍按 ops 脚本单独同步。
  · manifest 不落明文 DATABASE_URL，避免备份文件泄露凭据。
  · 恢复默认只生成暂存副本；apply=True 需管理端显式二次确认，且会中断当前连接。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import smtplib
import sqlite3
import subprocess
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from ..config import Settings, SERVER_DIR
from ..errors import ApiError

logger = logging.getLogger("moxie.backup")

BACKUP_ID_RE = re.compile(r"^backup-[0-9A-Za-z-]+$")
MANIFEST_NAME = "manifest.json"
SQLITE_FILE = "database.sqlite3"
POSTGRES_FILE = "database.dump"


def backup_root(settings: Settings) -> Path:
    raw = (settings.backup_dir or "").strip()
    path = Path(raw).expanduser() if raw else SERVER_DIR / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _resolve_backup(settings: Settings, backup_id: str) -> Path:
    if not BACKUP_ID_RE.match(backup_id or ""):
        raise ApiError(400, "invalid_backup_id", "备份 ID 格式不合法")
    path = (backup_root(settings) / backup_id).resolve()
    if path.parent != backup_root(settings) or not path.is_dir():
        raise ApiError(404, "backup_not_found", "备份不存在")
    return path


def _read_manifest(path: Path) -> dict:
    manifest_path = path / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ApiError(404, "backup_not_found", "备份清单缺失")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApiError(500, "backup_manifest_invalid", "备份清单损坏") from exc


def _write_manifest(path: Path, manifest: dict) -> None:
    (path / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path(url: str) -> Path:
    if not url.startswith("sqlite"):
        raise ApiError(501, "backup_engine_unsupported", "仅支持 SQLite 与 PostgreSQL 数据库备份")
    return Path(url.split("///", 1)[-1]).expanduser().resolve()


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql") or url.startswith("postgres")


def _redacted_url(url: str) -> str:
    try:
        parsed = make_url(url)
        if not parsed.password:
            return url
        return parsed.render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - 只在 manifest 做展示，不能因解析失败阻断备份
        return f"{urlparse(url).scheme}://***"


def _recipients(settings: Settings) -> list[str]:
    return [item.strip() for item in settings.backup_notify_emails.split(",") if item.strip()]


def _notify_backup(settings: Settings, manifest: dict) -> dict:
    recipients = _recipients(settings)
    if not settings.backup_email_enabled or not recipients:
        return {"enabled": False, "status": "skipped", "reason": "no_recipients_or_disabled"}
    if not settings.smtp_host:
        return {"enabled": True, "status": "skipped", "reason": "smtp_not_configured", "recipients": recipients}
    subject = f"[Moxie] 数据库备份完成 · {manifest['id']}"
    body = (
        f"备份 ID：{manifest['id']}\n"
        f"创建时间：{manifest['created_at']}\n"
        f"触发方式：{manifest['trigger']}\n"
        f"数据库类型：{manifest['engine']}\n"
        f"文件大小：{manifest['size_bytes']} bytes\n"
        f"SHA256：{manifest['checksum']}\n"
        "请登录管理端「备份管理」下载并妥善保管。"
    )
    if settings.notification_email_transport == "fake":
        return {"enabled": True, "status": "fake", "recipients": recipients}
    try:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = ", ".join(recipients)
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
        return {"enabled": True, "status": "sent", "recipients": recipients}
    except Exception as exc:  # noqa: BLE001 - 邮件失败不影响备份成功
        logger.warning("备份通知邮件发送失败 backup=%s error=%s", manifest["id"], type(exc).__name__)
        return {"enabled": True, "status": "failed", "error": type(exc).__name__, "recipients": recipients}


def _sqlite_snapshot(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ApiError(500, "backup_source_missing", "数据库文件不存在，无法备份")
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        dst.commit()
        status = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
        dst.close()
    if status != "ok":
        raise ApiError(500, "backup_integrity_failed", f"SQLite 备份完整性检查失败：{status}")


def _postgres_dump(settings: Settings, target: Path) -> None:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise ApiError(501, "pg_dump_missing", "未找到 pg_dump，请先安装 PostgreSQL 客户端")
    url = make_url(settings.database_url)
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    command = [
        pg_dump,
        "--format=custom",
        "--file",
        str(target),
        "--dbname",
        settings.database_url,
    ]
    try:
        subprocess.run(command, check=True, env=env, timeout=1800, capture_output=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("pg_dump failed: %s", exc.stderr.decode("utf-8", "ignore")[-500:])
        raise ApiError(500, "backup_failed", "pg_dump 备份失败") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(504, "backup_timeout", "pg_dump 备份超时") from exc


def _prune(root: Path, keep: int) -> None:
    if keep <= 0:
        return
    dirs = sorted(
        (path for path in root.glob("backup-*") if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for old in dirs[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        logger.info("旧备份已清理 backup=%s", old.name)


def create_backup(settings: Settings, *, trigger: str = "manual", db: Any = None) -> dict:
    """创建一次数据库备份，返回 manifest；邮件发送状态写回 manifest。"""
    if not settings.backup_enabled:
        raise ApiError(503, "backup_disabled", "数据库备份功能已关闭")
    root = backup_root(settings)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"backup-{stamp}-{uuid.uuid4().hex[:6]}"
    workdir = root / backup_id
    workdir.mkdir(parents=True, exist_ok=False)

    engine = "postgres" if _is_postgres(settings.database_url) else "sqlite"
    filename = POSTGRES_FILE if engine == "postgres" else SQLITE_FILE
    target = workdir / filename
    try:
        if engine == "postgres":
            _postgres_dump(settings, target)
        else:
            _sqlite_snapshot(_sqlite_path(settings.database_url), target)
        checksum = _sha256(target)
        size = target.stat().st_size
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise

    manifest: dict[str, Any] = {
        "id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "engine": engine,
        "database_url": _redacted_url(settings.database_url),
        "database": {"kind": engine, "file": filename},
        "files": {filename: checksum},
        "checksum": checksum,
        "size_bytes": size,
        "email": {"status": "pending"},
    }
    # 先写一次，确保邮件失败/进程中断也能列出备份
    _write_manifest(workdir, manifest)
    manifest["email"] = _notify_backup(settings, manifest)
    _write_manifest(workdir, manifest)
    _prune(root, settings.backup_retention_count)
    logger.info("数据库备份完成 backup=%s engine=%s trigger=%s", backup_id, engine, trigger)
    return manifest


def _database_file(path: Path, manifest: dict) -> Path:
    """从清单解析数据库文件：只接受本服务生成的固定文件名。

    清单是可被外部改动的文件，不能直接用其中的 file 字段拼接路径，
    否则 download/restore 会变成任意文件读取/覆盖。
    """
    filename = (manifest.get("database") or {}).get("file") or ""
    if filename not in (SQLITE_FILE, POSTGRES_FILE):
        raise ApiError(422, "backup_manifest_invalid", "备份清单数据库文件名不合法")
    source = (path / filename).resolve()
    if source.parent != path.resolve() or not source.is_file():
        raise ApiError(404, "backup_file_missing", "备份文件缺失")
    return source


def list_backups(settings: Settings) -> list[dict]:
    root = backup_root(settings)
    items: list[dict] = []
    for path in root.glob("backup-*"):
        if not path.is_dir() or not BACKUP_ID_RE.match(path.name):
            continue
        try:
            manifest = _read_manifest(path)
        except ApiError:
            continue
        items.append(
            {
                "id": path.name,
                "created_at": manifest.get("created_at"),
                "trigger": manifest.get("trigger", "manual"),
                "engine": manifest.get("engine", "sqlite"),
                "size_bytes": int(manifest.get("size_bytes") or 0),
                "checksum": manifest.get("checksum", ""),
                "email": manifest.get("email") or {},
            }
        )
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def download_backup(settings: Settings, backup_id: str) -> tuple[str, bytes]:
    path = _resolve_backup(settings, backup_id)
    manifest = _read_manifest(path)
    source = _database_file(path, manifest)
    filename = source.name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, filename)
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    return f"{backup_id}.zip", buffer.getvalue()


def delete_backup(settings: Settings, backup_id: str) -> dict:
    path = _resolve_backup(settings, backup_id)
    shutil.rmtree(path, ignore_errors=True)
    return {"id": backup_id, "deleted": True}


def restore_backup(settings: Settings, backup_id: str, *, apply: bool = False, db: Any = None) -> dict:
    """默认只生成可验证的暂存副本；apply=True 才覆盖当前数据库。"""
    path = _resolve_backup(settings, backup_id)
    manifest = _read_manifest(path)
    source = _database_file(path, manifest)
    filename = source.name
    expected = (manifest.get("files") or {}).get(filename)
    if expected and _sha256(source) != expected:
        raise ApiError(422, "backup_checksum_mismatch", "备份校验失败，文件可能已损坏")

    if not apply:
        staged_root = backup_root(settings) / "restores" / backup_id
        staged_root.mkdir(parents=True, exist_ok=True)
        staged = staged_root / filename
        shutil.copy2(source, staged)
        guide = (
            f"# 恢复指引 · {backup_id}\n\n"
            "已生成暂存副本，未覆盖当前数据库。\n"
            f"- 副本路径：`{staged}`\n"
            f"- 数据库类型：{manifest.get('engine')}\n\n"
            "SQLite：停服后将该文件替换 DATABASE_URL 指向的文件，并清理同目录 -wal/-shm。\n"
            "PostgreSQL：停服后用 `pg_restore --clean --if-exists --dbname <NEW_DB> "
            f"{staged}` 恢复到新库，再切换 DATABASE_URL 并重启。\n"
        )
        (staged_root / "RESTORE_GUIDE.md").write_text(guide, encoding="utf-8")
        return {"id": backup_id, "mode": "staged", "path": str(staged), "engine": manifest.get("engine")}

    engine = manifest.get("engine") or "sqlite"
    if engine == "postgres":
        pg_restore = shutil.which("pg_restore")
        if not pg_restore:
            raise ApiError(501, "pg_restore_missing", "未找到 pg_restore，请先安装 PostgreSQL 客户端")
        url = make_url(settings.database_url)
        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = url.password
        try:
            subprocess.run(
                [
                    pg_restore,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--exit-on-error",
                    "--dbname",
                    settings.database_url,
                    str(source),
                ],
                check=True,
                env=env,
                timeout=1800,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("pg_restore failed: %s", exc.stderr.decode("utf-8", "ignore")[-500:])
            raise ApiError(500, "restore_failed", "数据库恢复失败") from exc
        return {"id": backup_id, "mode": "applied", "engine": "postgres"}

    target = _sqlite_path(settings.database_url)
    if db is not None and hasattr(db, "dispose"):
        db.dispose()
    tmp = target.with_name(f".{target.name}.restore-{uuid.uuid4().hex[:6]}.tmp")
    shutil.copy2(source, tmp)
    os.replace(tmp, target)
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        if stale.exists():
            stale.unlink()
    if db is not None and hasattr(db, "create_all"):
        db.create_all()
    return {"id": backup_id, "mode": "applied", "engine": "sqlite", "path": str(target)}


def run_scheduled(settings: Settings, db: Any = None) -> dict:
    """scheduler phase：按间隔触发；最近已有备份则跳过。"""
    if not settings.backup_schedule_enabled:
        return {"status": "disabled"}
    items = list_backups(settings)
    if items and items[0].get("created_at"):
        try:
            created = datetime.fromisoformat(str(items[0]["created_at"]))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created < timedelta(minutes=settings.backup_interval_minutes):
                return {"status": "skipped", "reason": "recent_backup_exists"}
        except ValueError:
            pass
    try:
        manifest = create_backup(settings, trigger="scheduled", db=db)
        return {"status": "created", "id": manifest["id"], "email": manifest["email"]}
    except Exception as exc:  # noqa: BLE001 - scheduler 单项失败不阻塞其它 phase
        logger.exception("定时备份失败")
        return {"status": "error", "error": type(exc).__name__}
