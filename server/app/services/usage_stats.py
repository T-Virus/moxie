# -*- coding: utf-8 -*-
"""AI 模型消费统计：统一从 usage_events 聚合，避免跨平台翻日志对账。

meta 里的 provider 是 2026-11-18 起写入的新字段；历史数据缺失时归到 unknown，
不影响成本与 token 汇总。SQLite / Postgres 均走 Python 聚合，避免 JSON 方言分支。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Account, UsageEvent

GROUP_BY_VALUES = ("model", "provider", "account", "day")
MAX_ROWS = 20000


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def model_usage(
    db: Session,
    *,
    days: int = 30,
    group_by: str = "model",
    provider: str = "",
    model: str = "",
    route: str = "",
    account_id: int | None = None,
    max_rows: int = MAX_ROWS,
) -> dict:
    if group_by not in GROUP_BY_VALUES:
        group_by = "model"
    days = max(1, min(int(days or 30), 366))
    # 与接口层 Query(le=MAX_ROWS) 双保险：直接调用服务也不能一次拉爆内存。
    max_rows = max(1, min(int(max_rows or MAX_ROWS), MAX_ROWS))
    start = utcnow() - timedelta(days=days)

    stmt = (
        select(UsageEvent, Account.email)
        .outerjoin(Account, Account.id == UsageEvent.account_id)
        .where(UsageEvent.metric == "model_token", UsageEvent.occurred_at >= start)
        .order_by(UsageEvent.occurred_at.desc())
    )

    buckets: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_cost = 0
    total_calls = 0
    matched = 0
    truncated = False
    # 流式读取 + 命中上限即停：筛选条件在 Python 侧执行，不能先 limit 再过滤，
    # 否则「只查到大量无关事件」会被误报为完整结果。
    for event, email in db.execute(stmt).yield_per(500):
        meta = event.meta or {}
        event_provider = str(meta.get("provider") or "unknown")
        event_model = str(meta.get("model") or "unknown")
        event_route = str(meta.get("route") or "unknown")
        if provider and event_provider.lower() != provider.lower():
            continue
        if model and event_model.lower() != model.lower():
            continue
        if route and event_route.lower() != route.lower():
            continue
        if account_id is not None and int(event.account_id or 0) != account_id:
            continue
        if matched >= max_rows:
            truncated = True
            break
        matched += 1

        tokens = _as_int(event.quantity or meta.get("total_tokens"))
        cost = _as_int(meta.get("cost_cents"))
        calls = max(1, _as_int(meta.get("calls")))
        total_tokens += tokens
        total_cost += cost
        total_calls += calls

        occurred = event.occurred_at
        if isinstance(occurred, datetime):
            day_key = occurred.astimezone(timezone.utc).date().isoformat()
        else:
            day_key = str(occurred)[:10]
        if group_by == "provider":
            key, label = event_provider, event_provider
        elif group_by == "account":
            key = str(event.account_id or 0)
            label = str(email or f"账号#{key}")
        elif group_by == "day":
            key, label = day_key, day_key
        else:
            key, label = event_model, event_model
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "label": label,
                "provider": event_provider if group_by == "model" else "",
                "tokens": 0,
                "cost_cents": 0,
                "calls": 0,
                "accounts": set(),
                "models": set(),
            },
        )
        bucket["tokens"] += tokens
        bucket["cost_cents"] += cost
        bucket["calls"] += calls
        bucket["accounts"].add(int(event.account_id or 0))
        bucket["models"].add(event_model)

    items: list[dict[str, Any]] = []
    for bucket in buckets.values():
        accounts = bucket.pop("accounts")
        models = bucket.pop("models")
        bucket["account_count"] = len(accounts)
        bucket["model_count"] = len(models)
        items.append(bucket)
    items.sort(key=lambda row: (-row["cost_cents"], -row["tokens"], row["label"]))

    return {
        "generated_at": utcnow().isoformat(),
        "days": days,
        "group_by": group_by,
        "total_tokens": total_tokens,
        "total_cost_cents": total_cost,
        "total_calls": total_calls,
        "scanned_rows": matched,
        "truncated": truncated,
        "items": items,
    }
