# -*- coding: utf-8 -*-
"""源文件上传：成功链路、大小/扩展名/鉴权/跨账号/限频/清理。"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Task
from app.services.storage import build_storage
from app.services.tasks import execute_task, get_runner
from app.services.uploads import cleanup_expired_uploads

from .helpers import subscribe


def _chapter(n: int, title: str) -> str:
    body = "林默在营地醒来，远处传来低沉的兽吼，他握紧了手里的黑色兽核。" * 20
    return f"第{n}章 {title}\n{body}\n"


@pytest.fixture
def stub_client(settings, tmp_path):
    stub = settings.model_copy(
        update={
            "model_stub": True,
            "decompose_segment_batch": 0,
            "upload_max_bytes": 30 * 1024 * 1024,
        }
    )
    with TestClient(create_app(stub)) as client:
        reg = client.post(
            "/v1/auth/register",
            json={"email": "upload@example.com", "password": "password123"},
        )
        assert reg.status_code == 201, reg.text
        token = client.post(
            "/v1/auth/login",
            json={"email": "upload@example.com", "password": "password123"},
        ).json()["access_token"]
        yield client, {"Authorization": f"Bearer {token}"}, reg.json(), stub


def _upload(client, headers, name: str, content: str, mime: str = "text/plain"):
    return client.post(
        "/v1/uploads",
        headers=headers,
        files={"file": (name, content.encode("utf-8"), mime)},
    )


def test_upload_task_runner_roundtrip(stub_client, monkeypatch):
    client, headers, account, settings = stub_client
    subscribe(client, headers, plan_code="creator")
    source = _chapter(1, "觉醒") + _chapter(2, "追兵") + _chapter(3, "反击")
    response = _upload(client, headers, "样本 3章.txt", source)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_key"].startswith(f"uploads/{account['account']['id']}/")
    assert body["source_key"].endswith("-样本_3章.txt")
    assert body["size"] == len(source.encode("utf-8"))

    create = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "upload-task-1"},
        json={
            "type": "decompose",
            "params": {
                "source_key": body["source_key"],
                "mode": "reference",
                "book": "上传样本书",
                "limit": 3,
                "chunk_chars": 10000,
                "chunk_chapters": 1,
            },
        },
    )
    assert create.status_code == 201, create.text
    task_id = create.json()["task"]["id"]

    with client.app.state.db.session() as session:
        task = session.get(Task, task_id)
        status = execute_task(
            session,
            task,
            get_runner("decompose"),
            settings=settings,
            storage=build_storage(settings),
        )
        session.commit()
    assert status == "succeeded"

    detail = client.get(f"/v1/tasks/{task_id}", headers=headers).json()["task"]
    assert detail["status"] == "succeeded"
    listing = client.get(f"/v1/tasks/{task_id}/artifacts", headers=headers).json()
    names = {item["name"] for item in listing["artifacts"]}
    assert "source.txt" in names and "chapters.json" in names

    # 上传源文件的显式删除（任务产物保留）
    deleted = client.delete("/v1/uploads", headers=headers, params={"key": body["source_key"]})
    assert deleted.status_code == 200, deleted.text
    assert not build_storage(settings).exists(body["source_key"])


def test_upload_rejects_oversize(stub_client):
    client, headers, _account, _settings = stub_client
    client.app.state.settings.upload_max_bytes = 64
    response = _upload(client, headers, "big.txt", "x" * 100)
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "source_too_large"


def test_upload_rejects_bad_extension(stub_client):
    client, headers, _account, _settings = stub_client
    response = _upload(client, headers, "evil.exe", "not a text", "application/octet-stream")
    assert response.status_code == 415, response.text
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_upload_requires_auth(client):
    response = client.post(
        "/v1/uploads",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_upload_cross_account_isolation(stub_client):
    client, headers, _account, _settings = stub_client
    owned = _upload(client, headers, "mine.txt", _chapter(1, "私密")).json()["source_key"]

    client.post(
        "/v1/auth/register",
        json={"email": "other-upload@example.com", "password": "password123"},
    )
    other = client.post(
        "/v1/auth/login",
        json={"email": "other-upload@example.com", "password": "password123"},
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other}"}

    stolen = client.post(
        "/v1/tasks",
        headers={**other_headers, "Idempotency-Key": f"steal-{uuid.uuid4()}"},
        json={"type": "decompose", "params": {"source_key": owned}},
    )
    assert stolen.status_code == 404
    assert stolen.json()["error"]["code"] == "source_not_found"

    deleted = client.delete("/v1/uploads", headers=other_headers, params={"key": owned})
    assert deleted.status_code == 404
    assert deleted.json()["error"]["code"] == "upload_not_found"


def test_upload_rate_limit(stub_client):
    client, headers, _account, _settings = stub_client
    client.app.state.settings.upload_rate_limit_per_minute = 2
    for index in range(2):
        assert _upload(client, headers, f"ok{index}.txt", "hello").status_code == 201
    limited = _upload(client, headers, "blocked.txt", "hello")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


def test_upload_cleanup_respects_retention(stub_client):
    client, headers, _account, settings = stub_client
    key = _upload(client, headers, "old.txt", "hello").json()["source_key"]
    storage = build_storage(settings)
    with client.app.state.db.session() as session:
        old = time.time() - timedelta(days=40).total_seconds()
        os.utime(storage._path(key), (old, old))
        removed = cleanup_expired_uploads(
            storage, session, settings, datetime.now(timezone.utc)
        )
    assert removed == 1
    assert not storage.exists(key)
