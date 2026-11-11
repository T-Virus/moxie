# -*- coding: utf-8 -*-
"""Redis：队列、限流。没有 Redis（开发机 / 测试）时自动退回 fakeredis。"""

from __future__ import annotations

import logging
import time

import fakeredis
import redis

from .config import Settings

logger = logging.getLogger("moxie.redis")

# Redis 不可用时的冷却窗口：期间直接跳过，避免每次调用都等 0.5s 超时并刷日志
_UNAVAILABLE_UNTIL = 0.0
_UNAVAILABLE_COOLDOWN_SECONDS = 30.0


def try_redis(settings: Settings, *, decode_responses: bool = False):
    """返回已 ping 通的真实 Redis；不可用时冷却期内直接返回 None。"""
    global _UNAVAILABLE_UNTIL
    if not settings.redis_enabled:
        return None
    if time.monotonic() < _UNAVAILABLE_UNTIL:
        return None
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=decode_responses,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    try:
        client.ping()
    except Exception:  # noqa: BLE001 - 开发机无 Redis 属可预期状态
        _UNAVAILABLE_UNTIL = time.monotonic() + _UNAVAILABLE_COOLDOWN_SECONDS
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
        return None
    return client


def build_redis(settings: Settings):
    """返回 (client, backend_name)。生产应为真实 Redis；测试允许 fakeredis。"""
    if settings.redis_enabled:
        try:
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            return client, "redis"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 不可用，退回 fakeredis：%s", exc)
    return fakeredis.FakeRedis(decode_responses=True), "fakeredis"


class RateLimiter:
    def __init__(self, client):
        self.client = client

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        redis_key = f"rl:{key}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds)
            count, _ = pipe.execute()
            return int(count) <= limit
        except Exception:  # noqa: BLE001
            # 缓存故障不阻断主流程，但会在指标上体现日志
            logger.warning("rate limiter unavailable, allow by default")
            return True
