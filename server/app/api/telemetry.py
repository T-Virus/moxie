# -*- coding: utf-8 -*-
"""前端错误上报（可观测性）：把浏览器端异常串进服务端结构化日志。

设计约束：
  · 匿名端点（未登录也要能上报），不做认证、不写库、不回传任何业务数据；
  · 只记录错误摘要与来源 request_id，用它与服务端 http_request 日志对齐；
  · 输入一律视为不可信：限长（schema）+ 正则脱敏（token/key/JWT），URL 去掉 query；
  · 独立限流，避免错误风暴挤占业务接口的全局配额，或被用作日志洪泛通道。
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import client_ip
from ..errors import ApiError
from ..metrics import increment
from ..redis_client import RateLimiter
from ..schemas import ClientErrorReport
from ..services import runtime_config

logger = logging.getLogger("moxie.client_error")

router = APIRouter(tags=["telemetry"])

# 形如 key=value / Bearer xxx / JWT，统一替换为 [redacted]，避免密钥随错误日志外泄
_SECRET_QUERY = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|signature|authorization|byok)\s*[=:]\s*[^\s&,\"']+")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")


def redact(text: str) -> str:
    """对错误摘要做保守脱敏：命中即替换为占位符，不尝试保留可用性。"""
    if not text:
        return ""
    out = _SECRET_QUERY.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    out = _BEARER.sub("Bearer [redacted]", out)
    out = _JWT.sub("[redacted]", out)
    return out[:1000]


def safe_path(url: str) -> str:
    """URL 只保留 path，丢弃可能含 token 的 query / fragment。"""
    if not url:
        return ""
    try:
        return (urlsplit(url).path or "")[:500]
    except ValueError:
        return ""


@router.post("/telemetry/client-error")
def report_client_error(
    payload: ClientErrorReport, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    settings = request.app.state.settings
    limiter: RateLimiter = request.app.state.limiter
    ip = client_ip(request) or "-"

    # 限流按 IP 独立计数；limit<=0 表示关闭（配置层 RateLimiter.check 已支持）
    allowed, retry_after = limiter.check(
        f"client_error:{ip}",
        settings.client_error_rate_limit_per_minute,
        60,
    )
    if not allowed:
        increment("moxie_client_error_reports_total", result="rate_limited")
        raise ApiError(429, "rate_limited", "上报过于频繁，请稍后再试", {"Retry-After": str(retry_after)})

    source_request_id = redact(payload.request_id)[:64]
    source_trace_id = redact(payload.trace_id)[:64]
    message = redact(payload.message)
    path = safe_path(payload.url)
    level = payload.level
    code = payload.code[:80]
    source = payload.source[:16]

    # 灰度命中档位：按错误指纹稳定分桶，判定结果与 effective_for_bucket 同一算法。
    # 需在写日志前算出，便于把「本次上报走基线还是灰度」落到结构化日志与指标。
    from ..services.sentry import (
        client_error_to_sentry,
        error_fingerprint,
        should_forward,
    )

    fingerprint = error_fingerprint(code=code, message=message, path=path, source=source)
    cfg = runtime_config.get_telemetry_config(db, settings)
    tier = runtime_config.bucket_tier(cfg, fingerprint)

    # request_id / trace_id 由 request_context 中间件写入 contextvars，
    # JsonFormatter 自动带上"本次上报请求"的 id；source_request_id 是"出错请求"的 id，
    # 两者并存便于跨端关联。
    log = logger.warning if level == "warn" else logger.error
    log(
        "client_error",
        extra={
            "source": source,
            "error_code": code,
            "error_message": message,
            "client_path": path,
            "source_request_id": source_request_id or "-",
            "source_trace_id": source_trace_id or "-",
            "client_ts": payload.ts[:40],
            "client_ip": ip,
            # 灰度命中档位（2026-11-18）：便于后台核对灰度是否生效、按档位统计
            "canary_tier": tier["tier"],
            "canary_percent": tier["percent"],
            "canary_bucket": tier["bucket"],
        },
    )
    # 转发到 Sentry（可选）：只传已脱敏字段，失败静默，绝不影响上报响应。
    # 先做稳定采样 + 时间窗去重，削掉错误风暴，避免打爆 Sentry 配额。
    # app.state.redis 由 build_redis 提供：生产为真实 Redis（跨 worker 精确去重），
    # 无 Redis 时为 fakeredis 或 None（自动回退进程内，不影响上报可用性）。
    redis_client = getattr(request.app.state, "redis", None)
    # 后台热改的采样率/窗口/zset 容量（DB + 60s 缓存）覆盖环境变量默认值；读取失败自动降级。
    effective = runtime_config.effective_for_bucket(cfg, fingerprint)
    decision = should_forward(
        settings,
        fingerprint=fingerprint,
        redis_client=redis_client,
        sample_rate=effective["sample_rate"],
        dedupe_window_seconds=effective["dedupe_window_seconds"],
        dedupe_max_entries=effective["dedupe_max_entries"],
    )
    forwarded = False
    if decision:
        forwarded = client_error_to_sentry(
            settings,
            level=level,
            code=code,
            message=message,
            path=path,
            source=source,
            source_request_id=source_request_id,
        )
    increment(
        "moxie_client_error_reports_total",
        result="accepted",
        source=source,
        # forwarded=yes 真转发 / no=采样或去重被拦 / error=SDK 失败
        forwarded="yes" if forwarded else ("error" if decision else "no"),
        # 灰度命中档位标签：可观测配置灰度是否真正生效
        canary_tier=tier["tier"],
    )
    # 永远返回 204 语义的空体，避免上报请求自身产生可被再次上报的错误
    return JSONResponse(status_code=202, content={"accepted": True})
