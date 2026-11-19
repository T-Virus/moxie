# -*- coding: utf-8 -*-
"""管理端数据库备份 / 恢复：权限、清单、下载、暂存恢复与确认闸门。"""

from __future__ import annotations

import io
import json
import zipfile

from .test_admin_ext import _promote


def test_backup_lifecycle_and_permissions(client, headers, app, account, tmp_path):
    app.state.settings.backup_dir = str(tmp_path / "backups")
    account_id = account["account"]["id"]
    _promote(app, account_id, "admin")

    empty = client.get("/v1/admin/backups", headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []

    created = client.post("/v1/admin/backups", headers=headers, json={})
    assert created.status_code == 201, created.text
    item = created.json()["item"]
    assert item["engine"] == "sqlite"
    assert item["trigger"] == "manual"
    assert item["size_bytes"] > 0
    assert item["email"]["status"] in {"skipped", "fake", "sent", "failed"}
    backup_id = item["id"]

    listed = client.get("/v1/admin/backups", headers=headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [backup_id]

    downloaded = client.get(f"/v1/admin/backups/{backup_id}/download", headers=headers)
    assert downloaded.status_code == 200, downloaded.text
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert "database.sqlite3" in archive.namelist()

    staged = client.post(
        f"/v1/admin/backups/{backup_id}/restore", headers=headers, json={"apply": False}
    )
    assert staged.status_code == 200, staged.text
    assert staged.json()["mode"] == "staged"
    assert (tmp_path / "backups" / "restores" / backup_id / "RESTORE_GUIDE.md").is_file()

    rejected = client.post(
        f"/v1/admin/backups/{backup_id}/restore",
        headers=headers,
        json={"apply": True, "confirm": "yes"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "restore_confirmation_required"

    deleted = client.delete(f"/v1/admin/backups/{backup_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/v1/admin/backups", headers=headers).json()["items"] == []

    _promote(app, account_id, "support")
    assert client.get("/v1/admin/backups", headers=headers).status_code == 200
    assert client.post("/v1/admin/backups", headers=headers, json={}).status_code == 403
    assert client.post(
        f"/v1/admin/backups/{backup_id}/restore", headers=headers, json={"apply": False}
    ).status_code == 403


def test_backup_manifest_cannot_reference_arbitrary_file(client, headers, app, account, tmp_path):
    """清单中的 file 属不可信输入：路径穿越不得变成任意文件读取/恢复。"""
    app.state.settings.backup_dir = str(tmp_path / "backups")
    account_id = account["account"]["id"]
    _promote(app, account_id, "admin")
    created = client.post("/v1/admin/backups", headers=headers, json={})
    assert created.status_code == 201, created.text
    backup_id = created.json()["item"]["id"]

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    manifest_path = tmp_path / "backups" / backup_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["file"] = "../secret.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    downloaded = client.get(f"/v1/admin/backups/{backup_id}/download", headers=headers)
    assert downloaded.status_code == 422
    assert downloaded.json()["error"]["code"] == "backup_manifest_invalid"
    assert b"TOP-SECRET" not in downloaded.content

    staged = client.post(
        f"/v1/admin/backups/{backup_id}/restore", headers=headers, json={"apply": False}
    )
    assert staged.status_code == 422
    assert staged.json()["error"]["code"] == "backup_manifest_invalid"


def test_scheduled_backup_respects_interval(app, tmp_path):
    from app.db import Database
    from app.services.backup import run_scheduled

    from app.services.runtime_config import invalidate_backup_cache

    invalidate_backup_cache()
    settings = app.state.settings
    db = Database(settings)
    db.create_all()
    settings.backup_dir = str(tmp_path / "scheduled")
    settings.backup_schedule_enabled = False
    assert run_scheduled(settings, db)["status"] == "disabled"

    settings.backup_schedule_enabled = True
    settings.backup_interval_minutes = 720
    first = run_scheduled(settings, db)
    assert first["status"] == "created", first
    second = run_scheduled(settings, db)
    assert second["status"] == "skipped", second
    assert second["reason"] == "recent_backup_exists"


def test_libpq_url_strips_sqlalchemy_driver():
    """pg_dump/pg_restore 不认 `+psycopg` 驱动后缀，必须转成标准 libpq URI。"""
    from app.services.backup import _libpq_url

    url = "postgresql+psycopg://moxie:secret@postgres:5432/moxie"
    result = _libpq_url(url)
    assert result.startswith("postgresql://")
    assert "+psycopg" not in result
    assert "moxie:secret@postgres:5432/moxie" in result


def test_postgres_dump_uses_libpq_uri(monkeypatch, tmp_path):
    """PostgreSQL 备份调用 pg_dump 时，--dbname 必须是标准 libpq URI。"""
    from app.services import backup as backupsvc

    captured: dict = {}

    class FakeCompleted:
        returncode = 0
        stderr = b""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeCompleted()

    monkeypatch.setattr(backupsvc.shutil, "which", lambda name: "/usr/bin/pg_dump")
    monkeypatch.setattr(backupsvc.subprocess, "run", fake_run)

    class FakeSettings:
        database_url = "postgresql+psycopg://moxie:secret@postgres:5432/moxie"

    target = tmp_path / "dump.sql"
    backupsvc._postgres_dump(FakeSettings(), target)

    command = captured["command"]
    dbname_index = command.index("--dbname")
    dbname = command[dbname_index + 1]
    assert dbname.startswith("postgresql://")
    assert "+psycopg" not in dbname


def test_run_scheduled_disabled(monkeypatch):
    """定时备份开关关闭时不执行任何备份。"""
    from app.services import backup as backupsvc

    class FakeSettings:
        backup_schedule_enabled = False
        backup_interval_minutes = 720

    called = []
    monkeypatch.setattr(backupsvc, "create_backup", lambda *a, **k: called.append(1))
    result = backupsvc.run_scheduled(FakeSettings())
    assert result == {"status": "disabled"}
    assert called == []


def test_run_scheduled_creates_when_no_recent_backup(monkeypatch):
    """无近期备份时，定时任务创建 scheduled 备份。"""
    from app.services import backup as backupsvc

    class FakeSettings:
        backup_schedule_enabled = True
        backup_interval_minutes = 720

    monkeypatch.setattr(backupsvc, "list_backups", lambda s: [])
    monkeypatch.setattr(
        backupsvc,
        "create_backup",
        lambda s, *, trigger, db=None: {"id": "backup-x", "trigger": trigger, "email": {}},
    )
    result = backupsvc.run_scheduled(FakeSettings())
    assert result["status"] == "created"
    assert result["id"] == "backup-x"


def test_run_scheduled_skips_within_interval(monkeypatch):
    """间隔内已有备份时跳过，避免短时间内重复全量备份。"""
    from datetime import datetime, timedelta, timezone

    from app.services import backup as backupsvc

    class FakeSettings:
        backup_schedule_enabled = True
        backup_interval_minutes = 720

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(backupsvc, "list_backups", lambda s: [{"created_at": recent}])
    called = []
    monkeypatch.setattr(backupsvc, "create_backup", lambda *a, **k: called.append(1))
    result = backupsvc.run_scheduled(FakeSettings())
    assert result == {"status": "skipped", "reason": "recent_backup_exists"}
    assert called == []


def test_backup_config_get_put_and_permissions(client, headers, app, account):
    """定时备份配置可后台热改：默认来自环境变量，PUT 后写库并回读，support 只读。"""
    from app.services.runtime_config import invalidate_backup_cache

    invalidate_backup_cache()
    account_id = account["account"]["id"]
    _promote(app, account_id, "admin")

    current = client.get("/v1/admin/backup-config", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["source"] == "environment"

    payload = {
        "schedule_enabled": True,
        "interval_minutes": 15,
        "email_enabled": True,
        "notify_emails": "ops@example.com, bad-address ,ops@example.com",
        "retention_count": 5,
    }
    updated = client.put("/v1/admin/backup-config", headers=headers, json=payload)
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["source"] == "database"
    assert body["schedule_enabled"] is True
    assert body["interval_minutes"] == 15
    # 非法地址被过滤、重复被去重
    assert body["notify_emails"] == "ops@example.com"
    assert body["retention_count"] == 5

    reread = client.get("/v1/admin/backup-config", headers=headers)
    assert reread.json()["interval_minutes"] == 15
    assert reread.json()["source"] == "database"

    # 校验：间隔/份数越界返回 422
    bad = client.put(
        "/v1/admin/backup-config",
        headers=headers,
        json={**payload, "interval_minutes": 0, "retention_count": 999},
    )
    assert bad.status_code == 422

    # support 可读不可写
    _promote(app, account_id, "support")
    assert client.get("/v1/admin/backup-config", headers=headers).status_code == 200
    assert client.put("/v1/admin/backup-config", headers=headers, json=payload).status_code == 403


def test_backup_config_runtime_applies_to_scheduler(client, headers, app, account, tmp_path):
    """后台写入的配置生效于调度：关掉开关后 scheduled 返回 disabled。"""
    from app.db import Database
    from app.services import backup as backupsvc
    from app.services.runtime_config import invalidate_backup_cache

    invalidate_backup_cache()
    account_id = account["account"]["id"]
    _promote(app, account_id, "admin")
    settings = app.state.settings
    settings.backup_dir = str(tmp_path / "cfg-scheduled")

    resp = client.put(
        "/v1/admin/backup-config",
        headers=headers,
        json={
            "schedule_enabled": False,
            "interval_minutes": 720,
            "email_enabled": False,
            "notify_emails": "",
            "retention_count": 3,
        },
    )
    assert resp.status_code == 200, resp.text

    db = Database(settings)
    assert backupsvc.run_scheduled(settings, db) == {"status": "disabled"}


def test_backup_config_read_via_session(app, tmp_path):
    """scheduler 生产路径传 Session：运行时配置必须能被读到（曾因传 Database 静默降级）。"""
    from app.db import Database
    from app.services import backup as backupsvc
    from app.services import runtime_config
    from app.services.runtime_config import set_backup_config

    runtime_config.invalidate_backup_cache()
    settings = app.state.settings
    settings.backup_dir = str(tmp_path / "session-cfg")
    db = Database(settings)
    db.create_all()
    with db.session() as session:
        set_backup_config(
            session, settings, 1,
            schedule_enabled=False,
            interval_minutes=30,
            email_enabled=False,
            notify_emails="",
            retention_count=2,
        )
        # Session 传入：必须读到 database 配置并据此禁用
        result = backupsvc.run_scheduled(settings, session)
        assert result == {"status": "disabled"}, result
