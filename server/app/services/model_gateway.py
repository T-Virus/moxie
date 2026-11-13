# -*- coding: utf-8 -*-
"""模型调用核心：API 网关与 worker 共用同一套超时/重试/成本口径。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from ..config import Settings
from ..errors import ApiError
from .model_stub import stub_completion

logger = logging.getLogger("moxie.model")


@dataclass
class ModelResult:
    data: dict
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_cents: int
    byok: bool
    route: str


def _usage(data: dict) -> tuple[int, int, int]:
    usage = data.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return prompt, completion, total


def _text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):  # 多模态分片
        return "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content or "")


def _cost(settings: Settings, total_tokens: int) -> int:
    return int(round(total_tokens / 1000 * settings.model_price_cents_per_1k_tokens))


async def complete(
    settings: Settings,
    messages: list[dict],
    *,
    model: str | None = None,
    api_key: str = "",
    byok: bool = False,
    expect_json: bool = False,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> ModelResult:
    """调用上游 OpenAI 兼容接口；`model_stub=true` 时不访问外网。

    base_url 可覆盖默认网关（按工序切换供应商时使用），缺省用 settings.llm_base_url。
    """
    chosen = model or settings.llm_model
    if settings.model_stub:
        data, usage = stub_completion(messages, chosen, expect_json)
        prompt, completion, total = _usage(data)
        return ModelResult(
            data=data,
            text=_text(data),
            model=chosen,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost_cents=_cost(settings, total),
            byok=byok,
            route="stub",
        )

    if not api_key:
        raise ApiError(503, "model_not_configured", "服务端未配置模型 Key，请使用 BYOK 模式")

    body = {"model": chosen, "messages": messages, "stream": False}
    url = (base_url or settings.llm_base_url).rstrip("/") + "/chat/completions"
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
    attempts = max(1, settings.gateway_max_retries + 1)
    own_client = client is None
    http = client or httpx.AsyncClient()
    response: httpx.Response | None = None
    last_error = ""
    try:
        for attempt in range(attempts):
            try:
                response = await http.post(
                    url, json=body, headers=headers, timeout=settings.gateway_timeout_seconds
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
    finally:
        if own_client:
            await http.aclose()

    if response is None:
        raise ApiError(502, "upstream_error", f"上游模型服务不可用：{last_error or 'unknown'}")
    if response.status_code >= 400:
        raise ApiError(502, "upstream_error", f"上游返回 {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ApiError(502, "upstream_invalid_json", "上游返回不是合法 JSON") from exc

    prompt, completion, total = _usage(data)
    return ModelResult(
        data=data,
        text=_text(data),
        model=chosen,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost_cents=_cost(settings, total),
        byok=byok,
        route="byok" if byok else "managed",
    )


def complete_sync(settings: Settings, messages: list[dict], **kwargs) -> ModelResult:
    """worker（同步）入口；内部使用独立事件循环。"""
    return asyncio.run(complete(settings, messages, **kwargs))


def parse_json_text(text: str) -> dict:
    """从模型输出中提取 JSON；容忍 ```json 包裹与前后说明文字。"""
    import json

    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        return json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise
