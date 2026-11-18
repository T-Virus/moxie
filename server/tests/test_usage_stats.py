# -*- coding: utf-8 -*-
"""管理端模型消费统计：聚合口径、筛选与权限。"""

from __future__ import annotations

import uuid

from app.db import utcnow
from app.models import UsageEvent

from .test_admin_ext import _promote


def _add_usage(app, account_id: int, *, model: str, provider: str, tokens: int, cost: int) -> None:
    with app.state.db.session() as session:
        session.add(
            UsageEvent(
                account_id=account_id,
                task_id=None,
                metric="model_token",
                quantity=tokens,
                unit="token",
                idempotency_key=f"usage-stat-test-{uuid.uuid4().hex}",
                occurred_at=utcnow(),
                meta={
                    "model": model,
                    "provider": provider,
                    "route": "managed",
                    "total_tokens": tokens,
                    "cost_cents": cost,
                },
            )
        )
        session.commit()


def test_model_usage_caps_matched_rows(app, account):
    """服务层直接调用也必须限制命中行数，不能被大表拖垮。"""
    from app.services.usage_stats import model_usage

    aid = account["account"]["id"]
    for i in range(3):
        _add_usage(app, aid, model=f"model-{i}", provider="P", tokens=100, cost=1)
    with app.state.db.session() as session:
        data = model_usage(session, days=7, max_rows=2)
    assert data["scanned_rows"] == 2
    assert data["total_calls"] == 2
    assert data["truncated"] is True


def test_model_usage_aggregates_by_provider_and_filters(client, headers, app, account):
    account_id = account["account"]["id"]
    _promote(app, account_id, "admin")
    _add_usage(app, account_id, model="deepseek-chat", provider="DeepSeek", tokens=1000, cost=12)
    _add_usage(app, account_id, model="gpt-4o", provider="OpenAI", tokens=500, cost=25)
    _add_usage(app, account_id, model="deepseek-chat", provider="DeepSeek", tokens=200, cost=3)

    resp = client.get(
        "/v1/admin/usage/models", headers=headers, params={"days": 7, "group_by": "provider"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_tokens"] == 1700
    assert data["total_cost_cents"] == 40
    assert data["total_calls"] == 3
    rows = {row["key"]: row for row in data["items"]}
    assert rows["DeepSeek"]["tokens"] == 1200
    assert rows["DeepSeek"]["cost_cents"] == 15
    assert rows["OpenAI"]["cost_cents"] == 25

    filtered = client.get(
        "/v1/admin/usage/models",
        headers=headers,
        params={"days": 7, "group_by": "model", "provider": "deepseek"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total_tokens"] == 1200
    assert [row["key"] for row in filtered.json()["items"]] == ["deepseek-chat"]

    _promote(app, account_id, "support")
    assert client.get("/v1/admin/usage/models", headers=headers).status_code == 200
