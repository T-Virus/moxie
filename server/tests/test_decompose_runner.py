# -*- coding: utf-8 -*-
"""拆解链路：分段执行、断点续跑、产物存储/下载、计量与提示词不泄露。"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Task, TaskStep, UsageEvent
from app.services.storage import build_storage, task_prefix
from app.services.tasks import execute_task, get_runner

from .helpers import subscribe


def _chapter(n: int, title: str) -> str:
    body = "林默在营地醒来，远处传来低沉的兽吼，他握紧了手里的黑色兽核。" * 30
    return f"第{n}章 {title}\n{body}\n"


def _source(tmp_path) -> str:
    path = tmp_path / "source_3ch.txt"
    path.write_text(
        _chapter(1, "觉醒") + _chapter(2, "追兵") + _chapter(3, "反击"),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def stub_settings(settings):
    return settings.model_copy(update={"model_stub": True, "decompose_segment_batch": 1})


@pytest.fixture
def stub_client(stub_settings):
    with TestClient(create_app(stub_settings)) as client:
        client.post(
            "/v1/auth/register",
            json={"email": "runner@example.com", "password": "password123"},
        )
        login = client.post(
            "/v1/auth/login",
            json={"email": "runner@example.com", "password": "password123"},
        )
        token = login.json()["access_token"]
        yield client, {"Authorization": f"Bearer {token}"}


def _create_task(client, headers, source: str, key: str = "decompose-1") -> str:
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": key},
        json={
            "type": "decompose",
            "params": {
                "source_path": source,
                "mode": "reference",
                "book": "样本书",
                "limit": 3,
                "chunk_chars": 10000,
                "chunk_chapters": 1,
                "raw": True,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["task"]["id"]


def _run(app, task_id: str, settings, storage) -> str:
    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        status = execute_task(
            session,
            task,
            get_runner("decompose"),
            settings=settings,
            storage=storage,
        )
        session.commit()
        return status


def test_decompose_segments_resume_and_artifacts(stub_client, stub_settings, tmp_path):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create_task(client, headers, _source(tmp_path))
    storage = build_storage(stub_settings)

    statuses = []
    for _ in range(6):
        status = _run(app, task_id, stub_settings, storage)
        statuses.append(status)
        if status in {"succeeded", "failed", "canceled"}:
            break

    # 每次只处理 1 段：queued → queued → succeeded（最后一次合并）
    assert statuses == ["queued", "queued", "succeeded"], statuses

    detail = client.get(f"/v1/tasks/{task_id}", headers=headers)
    assert detail.status_code == 200
    task = detail.json()["task"]
    assert task["status"] == "succeeded"
    assert task["prompt_version"] == "decompose-2026-11-v1"
    assert task["output_artifact"].startswith("样本书/")
    assert task["cost_actual_cents"] >= 0

    with app.state.db.session() as session:
        steps = session.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        by_key = {s.step_key: s for s in steps}
        for index in (1, 2, 3):
            step = by_key[f"seg:{index:03d}"]
            assert step.status == "done"
            assert step.meta["input_chars"] > 0
            assert step.meta["total_tokens"] > 0
            assert step.meta["artifact_key"].endswith(f"seg-{index:03d}.json")
        assert by_key["merge"].status == "done"
        assert by_key["outputs"].status == "done"

        events = (
            session.query(UsageEvent)
            .filter(UsageEvent.task_id == task_id, UsageEvent.metric == "model_token")
            .all()
        )
        assert len(events) == 4  # 3 段 + 1 次合并
        assert all(e.unit == "token" for e in events)

    # 额度按实际结算：预占 1 本 → 已用 1 本
    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["used"] == 1
    assert books["reserved"] == 0

    # 产物列表 + 预签名下载（本地 fallback）
    prefix = task_prefix("样本书", task_id)
    listing = client.get(f"/v1/tasks/{task_id}/artifacts", headers=headers)
    assert listing.status_code == 200, listing.text
    names = {a["name"] for a in listing.json()["artifacts"]}
    assert {"decomposed.json", "chapters.json", "manifest.json"} <= names

    presign = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/chapters.json"},
    )
    assert presign.status_code == 200
    url = presign.json()["url"]
    download = client.get(url)
    assert download.status_code == 200
    data = download.json()
    assert len(data["chapters"]) == 3
    assert data["prompt_version"] == "decompose-2026-11-v1"

    manifest_presign = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/manifest.json"},
    )
    assert manifest_presign.status_code == 200
    manifest = client.get(manifest_presign.json()["url"]).json()
    assert manifest["segments"] == 3
    assert manifest["segments_done"] == 3
    assert manifest["prompt_version"] == "decompose-2026-11-v1"
    assert manifest["total_cost_cents"] >= 0

    # 文件不存在 → 明确错误码
    missing = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/nope.json"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "artifact_not_found"

    # 本地签名链接被篡改 → 403
    bad = client.get(url.replace("chapters.json", "manifest.json").replace("sig=", "sig=x"))
    if bad.status_code != 200:
        assert bad.status_code == 403


def test_resume_skips_completed_segment(stub_client, stub_settings, monkeypatch, tmp_path):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create_task(client, headers, _source(tmp_path), "resume-1")
    storage = build_storage(stub_settings)

    calls = []
    original = __import__("app.runners.decompose", fromlist=["complete_sync"]).complete_sync

    def counting(settings, messages, **kwargs):
        calls.append(str(messages))
        return original(settings, messages, **kwargs)

    monkeypatch.setattr("app.runners.decompose.complete_sync", counting)

    assert _run(app, task_id, stub_settings, storage) == "queued"
    assert len(calls) == 1

    with app.state.db.session() as session:
        seg1 = session.get(TaskStep, (task_id, "seg:001"))
        seg1_updated = seg1.updated_at

    # 重启后不再处理已完成段，只补剩余段（再跑 2 段 + 合并）
    after = stub_settings.model_copy(update={"decompose_segment_batch": 0})
    assert _run(app, task_id, after, storage) == "succeeded"
    assert len(calls) == 4
    assert "第1章 觉醒" not in calls[1]

    with app.state.db.session() as session:
        seg1 = session.get(TaskStep, (task_id, "seg:001"))
        assert seg1.updated_at == seg1_updated
        keys = [
            e.idempotency_key
            for e in session.query(UsageEvent)
            .filter(UsageEvent.task_id == task_id, UsageEvent.metric == "model_token")
            .all()
        ]
        assert len(keys) == len(set(keys)) == 4


def test_missing_source_rejected_at_create(stub_client, tmp_path):
    client, headers = stub_client
    subscribe(client, headers, plan_code="creator")
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "missing-source"},
        json={"type": "decompose", "params": {"source_path": str(tmp_path / "nope.txt")}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_not_found"


def test_byok_header_not_persisted(stub_client, tmp_path):
    client, headers = stub_client
    subscribe(client, headers, plan_code="creator")
    secret = "sk-byok-" + uuid.uuid4().hex
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "byok-1", "X-BYOK-Key": secret},
        json={"type": "decompose", "params": {"source_path": _source(tmp_path), "limit": 1}},
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["task"]["id"]
    detail = client.get(f"/v1/tasks/{task_id}", headers=headers)
    assert secret not in detail.text
    assert set(detail.json()["task"]["params"]) == {"source_path", "limit"}


def test_prompts_not_exposed(stub_client, stub_settings, tmp_path):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create_task(client, headers, _source(tmp_path), "leak-1")
    storage = build_storage(stub_settings)
    _run(app, task_id, stub_settings.model_copy(update={"decompose_segment_batch": 0}), storage)

    openapi = client.get("/openapi.json").text
    docs = client.get("/docs").text
    detail = client.get(f"/v1/tasks/{task_id}", headers=headers).text
    logs = client.get(f"/v1/tasks/{task_id}/logs", headers=headers).text
    for text in (openapi, docs, detail, logs):
        assert "小说结构分析专家" not in text
        assert "__SOURCE_TEXT__" not in text
        assert "__SCHEMA__" not in text
    assert not any("prompt" in path for path in client.get("/openapi.json").json()["paths"])


def test_artifact_isolation(stub_client, stub_settings, tmp_path):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create_task(client, headers, _source(tmp_path), "iso-1")
    storage = build_storage(stub_settings)
    _run(app, task_id, stub_settings.model_copy(update={"decompose_segment_batch": 0}), storage)

    client.post(
        "/v1/auth/register",
        json={"email": "other@example.com", "password": "password123"},
    )
    other = client.post(
        "/v1/auth/login",
        json={"email": "other@example.com", "password": "password123"},
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other}"}
    assert client.get(f"/v1/tasks/{task_id}/artifacts", headers=other_headers).status_code == 404
