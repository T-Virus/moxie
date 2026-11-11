# -*- coding: utf-8 -*-
"""结构化日志 + request-id。日志中不打印请求体，敏感头统一脱敏。"""

from __future__ import annotations

import contextvars
import json
import logging
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


def set_trace_id(value: str | None) -> str:
    """HTTP 请求复用 request_id；worker / scheduler 用任务号作为 trace_id。"""
    trace_id = (value or "-").strip()[:64] or "-"
    trace_id_ctx.set(trace_id)
    return trace_id
