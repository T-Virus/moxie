# -*- coding: utf-8 -*-
"""改编 / 审查 runner：断点、取消、产物入存储、提示词版本与用量归集。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Task, TaskStep, UsageEvent
from app.services.storage import build_storage, task_prefix
from app.services.tasks import execute_task, get_runner

from .helpers import subscribe


def _book_data() -> dict:
    return {
        "book_summary": "少年林默在异兽世界觉醒血脉，携带神秘兽核一路成长。",
        "story_bible": {"synopsis": "少年携带兽核成长。", "genre": "玄幻"},
        "chapters": [
            {
                "chapter": 1,
                "title": "第1章 觉醒",
                "summary": "林默在营地觉醒血脉。",
                "key_events": ["兽核发光"],
                "roles": ["林默"],
                "factions": [],
                "scene": "荒野营地",
            },
            {
                "chapter": 2,
                "title": "第2章 追兵",
                "summary": "追兵逼近营地。",
                "key_events": ["击退追兵"],
                "roles": ["林默", "苏晚"],
                "factions": ["御兽宗"],
                "scene": "山道",
            },
            {
                "chapter": 3,
                "title": "第3章 反击",
                "summary": "林默反击成功。",
                "key_events": ["兽核爆发"],
                "roles": ["林默"],
                "factions": [],
                "scene": "峡谷",
            },
        ],
    }


@pytest.fixture
def stub_settings(settings):
    return settings.model_copy(update={"model_stub": True, "decompose_segment_batch": 1})


@pytest.fixture
def stub_client(stub_settings):
    with TestClient(create_app(stub_settings)) as client:
        client.post(
            "/v1/auth/register",
            json={"email": "ext-runner@example.com", "password": "password123"},
        )
        token = client.post(
            "/v1/auth/login",
            json={"email": "ext-runner@example.com", "password": "password123"},
        ).json()["access_token"]
        yield client, {"Authorization": f"Bearer {token}"}


def _run(app, task_id: str, settings, storage):
    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        status = execute_task(
            session, task, get_runner(task.type), settings=settings, storage=storage
        )
        session.commit()
        return status


def _create(client, headers, payload: dict, key: str) -> str:
    response = client.post("/v1/tasks", headers={**headers, "Idempotency-Key": key}, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["task"]["id"]


def test_adapt_runner_resume_artifacts_and_usage(stub_client, stub_settings):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create(
        client,
        headers,
        {
            "type": "adapt",
            "params": {
                "book_data": _book_data(),
                "book": "样本书",
                "out_book": "新书",
                "chapters": 3,
                "chapters_per_call": 1,
            },
        },
        "adapt-1",
    )
    storage = build_storage(stub_settings)

    statuses = []
    for _ in range(8):
        status = _run(app, task_id, stub_settings, storage)
        statuses.append(status)
        if status in {"succeeded", "failed", "canceled"}:
            break
    assert statuses == ["queued", "queued", "succeeded"], statuses

    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        assert task.status == "succeeded"
        assert task.prompt_version == "adapt-2026-11-v1"
        assert task.output_artifact.endswith("/manifest.json")
        by_key = {
            s.step_key: s for s in session.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        }
        for key in ("book:meta", "seg:001", "seg:002", "seg:003", "outputs"):
            assert by_key[key].status == "done"
        events = (
            session.query(UsageEvent)
            .filter(UsageEvent.task_id == task_id, UsageEvent.metric == "model_token")
            .all()
        )
        # 书级 meta + 3 个章节段
        assert len(events) == 4
        keys = [e.idempotency_key for e in events]
        assert len(keys) == len(set(keys))

    prefix = task_prefix("样本书", task_id)
    listing = client.get(f"/v1/tasks/{task_id}/artifacts", headers=headers)
    names = {a["name"] for a in listing.json()["artifacts"]}
    assert {"decomposed.json", "chapters.json", "manifest.json", "seg-001.json"} <= names

    download = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/manifest.json"},
    )
    manifest = client.get(download.json()["url"]).json()
    assert manifest["prompt_version"] == "adapt-2026-11-v1"
    assert manifest["output_chapters"] == 3


def test_adapt_runner_cancel_between_segments(stub_client, stub_settings):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    task_id = _create(
        client,
        headers,
        {
            "type": "adapt",
            "params": {
                "book_data": _book_data(),
                "book": "取消样本",
                "chapters": 3,
                "chapters_per_call": 1,
            },
        },
        "adapt-cancel",
    )
    storage = build_storage(stub_settings)
    assert _run(app, task_id, stub_settings, storage) == "queued"
    response = client.post(f"/v1/tasks/{task_id}/cancel", headers=headers)
    assert response.status_code == 200, response.text
    assert _run(app, task_id, stub_settings, storage) == "canceled"

    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        assert task.status == "canceled"
        done = {
            s.step_key
            for s in session.query(TaskStep).filter(TaskStep.task_id == task_id).all()
            if s.status == "done"
        }
        assert "seg:001" in done
        assert "outputs" not in done


def test_review_runner_chapter_breakpoints(stub_client, stub_settings):
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    chapters = [
        {"chapter_no": 1, "text": "第1章 觉醒\n林默在营地醒来，远处传来低沉的兽吼，他握紧了兽核。" * 20},
        {"chapter_no": 2, "text": "第2章 追兵\n追兵压境，林默带着苏晚向山道撤退。" * 20},
    ]
    chapters_doc = {
        "book_summary": _book_data()["book_summary"],
        "chapters": _book_data()["chapters"],
    }
    task_id = _create(
        client,
        headers,
        {
            "type": "review",
            "params": {
                "book": "样本书",
                "chapters": chapters,
                "chapters_doc": chapters_doc,
                "checks": ["ai_taste"],
            },
        },
        "review-1",
    )
    storage = build_storage(stub_settings)

    statuses = []
    for _ in range(6):
        status = _run(app, task_id, stub_settings, storage)
        statuses.append(status)
        if status in {"succeeded", "failed", "canceled"}:
            break
    assert statuses == ["queued", "succeeded"], statuses

    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        assert task.status == "succeeded"
        assert task.prompt_version == "review-2026-11-v1"
        by_key = {
            s.step_key: s for s in session.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        }
        assert by_key["chapter:001"].status == "done"
        assert by_key["chapter:002"].status == "done"
        events = (
            session.query(UsageEvent)
            .filter(UsageEvent.task_id == task_id, UsageEvent.metric == "model_token")
            .all()
        )
        assert len(events) == 2

    prefix = task_prefix("样本书", task_id)
    listing = client.get(f"/v1/tasks/{task_id}/artifacts", headers=headers)
    names = {a["name"] for a in listing.json()["artifacts"]}
    assert {"chapter-001.json", "chapter-001.md", "manifest.json"} <= names

    download = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/review/manifest.json"},
    )
    manifest = client.get(download.json()["url"]).json()
    assert manifest["prompt_version"] == "review-2026-11-v1"
    assert manifest["reports"] == 2


def test_review_runner_similarity_gate(stub_client, stub_settings):
    """拆解源与改编产出高度重合时，体检结果写入 similarity 并标记 flagged。"""
    client, headers = stub_client
    app = client.app
    subscribe(client, headers, plan_code="creator")
    copied = "第1章 雨夜\n陆沉站在屋檐下，雨水顺着瓦片滴落，他握紧了手里的铜钥匙。" * 30
    chapters = [{"chapter_no": 1, "text": copied}]
    decomposed_doc = {
        "book_summary": "雨夜",
        "chapters": [{"chapter": 1, "content": copied}],
    }
    task_id = _create(
        client,
        headers,
        {
            "type": "review",
            "params": {
                "book": "相似度样本",
                "chapters": chapters,
                "decomposed_doc": decomposed_doc,
                "checks": ["ai_taste"],
            },
        },
        "review-similarity",
    )
    storage = build_storage(stub_settings)
    assert _run(app, task_id, stub_settings, storage) in {"queued", "succeeded"}
    assert _run(app, task_id, stub_settings, storage) == "succeeded"

    with app.state.db.session() as session:
        task = session.get(Task, task_id)
        assert task.output_artifact.endswith("/review/manifest.json")

    prefix = task_prefix("相似度样本", task_id)
    listing = client.get(f"/v1/tasks/{task_id}/artifacts", headers=headers)
    names = {a["name"] for a in listing.json()["artifacts"]}
    assert "similarity.json" in names

    download = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/review/similarity.json"},
    )
    similarity = client.get(download.json()["url"]).json()
    assert similarity["overall_overlap_ratio"] > 0.9

    download = client.get(
        f"/v1/tasks/{task_id}/artifacts/download",
        headers=headers,
        params={"key": f"{prefix}/review/manifest.json"},
    )
    manifest = client.get(download.json()["url"]).json()
    assert manifest["similarity"]["flagged"] is True
    assert manifest["similarity"]["artifact"].endswith("review/similarity.json")
