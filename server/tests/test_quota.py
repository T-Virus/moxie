# -*- coding: utf-8 -*-
"""额度：预占 / 结算 / 释放 / 超限 / 幂等。"""

from __future__ import annotations

import pytest

from app.errors import ApiError
from app.models import Subscription, UsageEvent
from app.services.quota import QuotaService

from .helpers import db_session, subscribe


def test_create_tasks_until_quota_limit(client, headers, app):
    subscribe(client, headers)  # creator: 5 本/月

    created = []
    for index in range(5):
        response = client.post(
            "/v1/tasks",
            headers={**headers, "Idempotency-Key": f"book-{index}"},
            json={"type": "decompose", "params": {"title": f"book-{index}"}},
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["task"]["id"])

    fifth = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "book-5"},
        json={"type": "decompose", "params": {"title": "book-5"}},
    )
    assert fifth.status_code == 402
    assert fifth.json()["error"]["code"] == "quota_exceeded"

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["limit"] == 5
    assert books["used"] == 0
    assert books["reserved"] == 5
    assert books["remaining"] == 0


def test_cancel_releases_reservation(client, headers, app):
    subscribe(client, headers)
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "cancel-me"},
        json={"type": "decompose", "params": {}},
    )
    task_id = response.json()["task"]["id"]

    cancelled = client.post(f"/v1/tasks/{task_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["status"] == "canceled"

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 0
    assert books["used"] == 0


def test_adapt_reserves_requested_chapter_count(client, headers, app):
    subscribe(client, headers)
    response = client.post(
        "/v1/tasks",
        headers={**headers, "Idempotency-Key": "adapt-10"},
        json={"type": "adapt", "params": {"chapters": 10}},
    )
    assert response.status_code == 201
    summary = client.get("/v1/entitlements", headers=headers).json()
    chapters = next(m for m in summary["metrics"] if m["metric"] == "adapt_chapters")
    assert chapters["reserved"] == 10


def test_commit_is_idempotent(client, headers, app, account):
    subscribe(client, headers)
    account_id = account["account"]["id"]
    with db_session(app) as session:
        quota = QuotaService(session)
        reservation = quota.reserve(account_id, "review_month", 1)
        assert quota.commit(reservation, idempotency_key="review:task-1", task_id="task-1") is True
        assert quota.commit(reservation, idempotency_key="review:task-1", task_id="task-1") is False
        assert quota.release(reservation) is None  # 释放是幂等的，不会把 used 变成负数
        session.commit()

        events = session.query(UsageEvent).filter(UsageEvent.account_id == account_id).all()
        assert len(events) == 1
        assert events[0].quantity == 1
        assert events[0].unit == "call"

    summary = client.get("/v1/entitlements", headers=headers).json()
    reviews = next(m for m in summary["metrics"] if m["metric"] == "review_month")
    assert reviews["used"] == 1
    assert reviews["reserved"] == 0


def test_release_frees_reservation(client, headers, app, account):
    subscribe(client, headers)
    account_id = account["account"]["id"]
    with db_session(app) as session:
        quota = QuotaService(session)
        reservation = quota.reserve(account_id, "books_month", 2)
        quota.release(reservation)
        session.commit()

    summary = client.get("/v1/entitlements", headers=headers).json()
    books = next(m for m in summary["metrics"] if m["metric"] == "books_month")
    assert books["reserved"] == 0
    assert books["used"] == 0


def test_no_subscription_rejected(app, account):
    account_id = account["account"]["id"]
    with db_session(app) as session:
        with pytest.raises(ApiError) as exc:
            QuotaService(session).reserve(account_id, "books_month", 1)
        assert exc.value.code == "no_active_subscription"
        assert exc.value.status_code == 402


def test_entitlement_missing_metric(client, headers, app, account):
    subscribe(client, headers)
    account_id = account["account"]["id"]
    with db_session(app) as session:
        with pytest.raises(ApiError) as exc:
            QuotaService(session).reserve(account_id, "unknown_metric", 1)
        assert exc.value.code == "entitlement_missing"
