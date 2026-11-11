# -*- coding: utf-8 -*-
"""模型代理网关：统一 key、超时、重试、限流、成本归集。

安全约定：
  · BYOK key 只从请求头 X-BYOK-Key 读取，仅用于本次上游请求；
  · 不写数据库、不写日志、不进入错误消息；
  · 请求体（含书稿/提示词）不落日志。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..db import get_db, utcnow
from ..deps import AuthContext, get_auth
from ..errors import ApiError
from ..metrics import increment
from ..models import UsageEvent
from ..services.usage_stream import StreamUsageCollector

logger = logging.getLogger("moxie.gateway")

router = APIRouter(tags=["gateway"])


def _cost(settings, total_tokens: int) -> int:
    return int(round(total_tokens / 1000 * settings.model_price_cents_per_1k_tokens))


def _persist_usage(
    db: Session,
    settings,
    *,
    account_id: int,
    model: str,
    usage: dict,
    byok: bool,
    route: str,
) -> None:
    total = int(usage.get("total_tokens") or 0)
    cost = _cost(settings, total)
    db.add(
        UsageEvent(
            account_id=account_id,
            task_id=None,
            metric="model_token",
            quantity=total,
            unit="token",
            idempotency_key=f"gw:{uuid.uuid4()}",
            occurred_at=utcnow(),
            meta={
                "model": model,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": total,
                "cost_cents": cost,
                "estimated": bool(usage.get("estimated")),
                "byok": byok,
                "route": route,
            },
        )
    )
    db.commit()
    increment("moxie_model_calls_total", route=route)
    increment("moxie_model_tokens_total", total)
    increment("moxie_model_cost_cents_total", cost)


def _usage_from(body: dict) -> tuple[int, int, int]:
    usage = body.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return prompt, completion, total


@router.post("/chat/completions")
async def chat_completions(
    payload: dict,
    request: Request,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    if not limiter.allow(
        f"gateway:{auth.account.id}", settings.gateway_rate_limit_per_minute, 60
    ):
        raise ApiError(429, "rate_limited", "模型调用过于频繁，请稍后再试")

    byok_key = (request.headers.get("x-byok-key") or "").strip()

    body = dict(payload)
    body.setdefault("model", settings.llm_model)

    if settings.model_stub:
        from ..services.model_gateway import complete

        result = await complete(
            settings,
            body.get("messages") or [],
            model=body.get("model"),
            api_key=byok_key or settings.llm_api_key,
            byok=bool(byok_key),
            expect_json=False,
            client=request.app.state.http_client,
        )
        _persist_usage(
            db,
            settings,
            account_id=auth.account.id,
            model=result.model,
            usage={
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "estimated": False,
            },
            byok=bool(byok_key),
            route="stub",
        )
        return JSONResponse(content=result.data, headers={"x-request-id": getattr(request.state, "request_id", "")})

    api_key = byok_key or settings.llm_api_key
    if not api_key:
        raise ApiError(503, "model_not_configured", "服务端未配置模型 Key，请使用 BYOK 模式")

    stream = bool(body.get("stream"))

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
    client: httpx.AsyncClient = request.app.state.http_client

    attempts = max(1, settings.gateway_max_retries + 1)
    last_error: str | None = None

    if stream:
        upstream = None
        for attempt in range(attempts):
            try:
                http_request = client.build_request(
                    "POST", url, json=body, headers=headers,
                    timeout=settings.gateway_timeout_seconds,
                )
                upstream = await client.send(http_request, stream=True)
                if upstream.status_code < 500:
                    break
                last_error = f"upstream status {upstream.status_code}"
                await upstream.aclose()
                upstream = None
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            if attempt < attempts - 1:
                await asyncio.sleep(0.4 * (attempt + 1))
        if upstream is None:
            raise ApiError(502, "upstream_error", f"上游模型服务不可用：{last_error or 'unknown'}")

        if upstream.status_code >= 400:
            detail = (await upstream.aread()).decode("utf-8", "replace")[:300]
            await upstream.aclose()
            raise ApiError(502, "upstream_error", f"上游返回 {upstream.status_code}: {detail}")

        prompt_text = "\n".join(str(m.get("content") or "") for m in body.get("messages") or [])
        collector = StreamUsageCollector(prompt_text)
        db_factory = request.app.state.db
        account_id = auth.account.id
        chosen_model = body.get("model") or settings.llm_model
        route = "byok" if byok_key else "managed"

        async def iterator():
            try:
                async for chunk in upstream.aiter_raw():
                    collector.feed(chunk)
                    yield chunk
            finally:
                collector.finish()

        async def finalize():
            await upstream.aclose()
            usage = collector.result()
            session = db_factory.session()
            try:
                _persist_usage(
                    session,
                    settings,
                    account_id=account_id,
                    model=chosen_model,
                    usage=usage,
                    byok=bool(byok_key),
                    route=route,
                )
            except Exception:  # noqa: BLE001 - 成本归集失败不影响已输出的内容
                logger.exception("gateway stream usage attribution failed account=%s", account_id)
                session.rollback()
            finally:
                session.close()

        return StreamingResponse(
            iterator(),
            media_type=upstream.headers.get("content-type", "text/event-stream"),
            background=BackgroundTask(finalize),
            headers={"x-request-id": getattr(request.state, "request_id", "")},
        )

    response: httpx.Response | None = None
    for attempt in range(attempts):
        try:
            response = await client.post(
                url, json=body, headers=headers,
                timeout=settings.gateway_timeout_seconds,
            )
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        else:
            if response.status_code < 500:
                break
            last_error = f"upstream status {response.status_code}"
        if attempt < attempts - 1:
            await asyncio.sleep(0.4 * (attempt + 1))

    if response is None:
        raise ApiError(502, "upstream_error", f"上游模型服务不可用：{last_error or 'unknown'}")
    if response.status_code >= 400:
        detail = response.text[:300]
        raise ApiError(502, "upstream_error", f"上游返回 {response.status_code}: {detail}")

    try:
        data = response.json()
    except ValueError:
        raise ApiError(502, "upstream_invalid_json", "上游返回不是合法 JSON")

    prompt_tokens, completion_tokens, total_tokens = _usage_from(data)
    try:
        _persist_usage(
            db,
            settings,
            account_id=auth.account.id,
            model=body.get("model") or settings.llm_model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated": False,
            },
            byok=bool(byok_key),
            route="byok" if byok_key else "managed",
        )
    except Exception:  # noqa: BLE001
        # 成本归集失败不能影响用户拿结果
        logger.exception("gateway usage attribution failed account=%s", auth.account.id)
        db.rollback()

    return JSONResponse(
        content=data,
        status_code=response.status_code,
        headers={"x-request-id": getattr(request.state, "request_id", "")},
    )
