# -*- coding: utf-8 -*-
"""Web Push 发送端：pywebpush 薄封装。

设计要点：
  · 延迟导入 pywebpush —— 未启用推送的生产环境无需安装该依赖即可启动；
  · 只接收订阅三元组与 payload，不接触数据库/配置，便于在上层注入与测试；
  · 异常原样上抛，由通知服务按渠道失败逻辑处理（写 failed + 退避重试）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..config import Settings

# 推送服务明确表示端点已不存在的状态码：命中即自动下线该订阅，避免反复重投无效端点。
# 404 Not Found / 410 Gone 语义来自 Web Push 规范；其余 4xx/5xx 视为可恢复，不清理订阅。
_EXPIRED_STATUS_CODES = frozenset({404, 410})


# 发送成功时的稳定 id：仅由 endpoint 派生，不含密钥，可安全落 provider_message_id。
def subscription_id(endpoint: str) -> str:
    return "push-" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:20]


def error_status_code(exc: BaseException) -> int | None:
    """从推送异常提取 HTTP 状态码；pywebpush.WebPushException 暴露 .status_code。

    非 HTTP 异常（连接超时、密钥配置错误等）没有该属性，返回 None —— 上层据此
    区分「端点失效需清理」与「可恢复失败需重试」。
    """
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def is_expired_subscription_error(exc: BaseException) -> bool:
    """是否应因该异常自动下线订阅（404/410）。"""
    return error_status_code(exc) in _EXPIRED_STATUS_CODES


def error_retry_after_seconds(
    exc: BaseException,
    *,
    cap_seconds: int = 3600,
    now: datetime | None = None,
) -> int | None:
    """从 429 异常的 Retry-After 头解析建议退避秒数，夹到 [0, cap_seconds]。

    pywebpush.WebPushException.retry_after 是字符串：纯秒数（"120"）或 HTTP-date
    （"Wed, 21 Oct 2015 07:28:00 GMT"）。解析失败/非 429/无该属性均返回 None，
    由上层回退到既有固定退避。cap 防止畸形或超大 header 把投递卡死数天。
    """
    if error_status_code(exc) != 429:
        return None
    raw = getattr(exc, "retry_after", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    seconds: float | None = None
    if raw.isdigit():
        seconds = float(raw)
    else:
        # HTTP-date：用 email.utils 解析，缺时区按 UTC 处理
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(raw)
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                ref = now or datetime.now(timezone.utc)
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                seconds = (parsed - ref).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds is None or seconds < 0:  # 负数/解析失败不采信
        return None
    return min(int(seconds), max(0, cap_seconds))


def push_configured(settings: Settings | None) -> bool:
    """私钥 + subject 齐全才算配置好；公钥仅用于自检，不参与发送。"""
    return bool(
        settings
        and settings.notification_push_enabled
        and settings.vapid_private_key.strip()
        and settings.vapid_subject.strip()
    )


def send_web_push(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict[str, Any],
    settings: Settings,
) -> str:
    """向单个订阅推送一条通知，返回稳定 provider id。pywebpush 异常原样上抛。"""
    from pywebpush import webpush  # 延迟导入：未安装依赖时只有真正发送才报错

    subscription_info = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
    webpush(
        subscription_info=subscription_info,
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=settings.vapid_private_key.strip(),
        vapid_claims={"sub": settings.vapid_subject.strip()},
        ttl=60,
    )
    return subscription_id(endpoint)
