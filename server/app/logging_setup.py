# -*- coding: utf-8 -*-
"""结构化日志 + request-id。日志中不打印请求体，敏感头统一脱敏。"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
import sys
import uuid
from datetime import datetime, timezone

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

_SENSITIVE_MARKERS = ("api_key", "apikey", "authorization", "password", "secret", "token", "byok")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
            "trace_id": trace_id_ctx.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 附加字段做敏感名过滤
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_") or key in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs", "message", "msg",
                "name", "pathname", "process", "processName", "relativeCreated", "stack_info",
                "thread", "threadName", "taskName",
            }:
                continue
            if any(marker in key.lower() for marker in _SENSITIVE_MARKERS):
                payload[key] = "[redacted]"
            else:
                try:
                    json.dumps(value)
                    payload[key] = value
                except TypeError:
                    payload[key] = str(value)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # 第三方库降噪
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_request_id(incoming: str | None = None) -> str:
    return incoming.strip()[:64] if incoming else uuid.uuid4().hex


_TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})(?:-.*)?$", re.IGNORECASE
)


def parse_traceparent(value: str | None) -> str | None:
    """解析 W3C traceparent，只取 32 位 trace-id；非法串一律忽略。"""
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip())
    if match is None or match.group(3).lower() == "00":
        return None
    return match.group(1).lower()


def new_trace_id() -> str:
    """生成 32 位十六进制 trace-id，格式与 W3C 对齐。"""
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def set_trace_id(value: str | None) -> str:
    """HTTP 请求优先复用上游 traceparent；worker / scheduler 用任务号作为 trace_id。"""
    trace_id = (value or "-").strip()[:64] or "-"
    trace_id_ctx.set(trace_id)
    return trace_id
