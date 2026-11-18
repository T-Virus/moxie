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
