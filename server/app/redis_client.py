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
    """固定窗口计数器，用于接口限流与登录失败锁定。

    key 由调用方给出（如 ``login:1.2.3.4``），内部统一加 ``rl:`` 前缀。
    TTL 只在首次计数时设置：若每次请求都刷新 EXPIRE，持续请求会让窗口
    无限延长、计数永不归零，反而造成"永久封禁"。缓存故障时 fail-open，
    避免 Redis 故障被放大成全站不可用。
    """

    def __init__(self, client):
        self.client = client

    def _incr(self, key: str, window_seconds: int) -> int:
        redis_key = f"rl:{key}"
        pipe = self.client.pipeline()
        pipe.incr(redis_key)
        pipe.ttl(redis_key)
        raw_count, raw_ttl = pipe.execute()
        count = int(raw_count)
        if int(raw_ttl if raw_ttl is not None else -1) < 0:
            self.client.expire(redis_key, window_seconds)
        return count

    def _ttl(self, key: str) -> int:
        try:
            return max(int(self.client.ttl(f"rl:{key}") or 0), 0)
        except Exception:  # noqa: BLE001
            return 0

    def check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """计数一次，返回 ``(是否允许, 超限时建议重试秒数)``。

        ``limit <= 0`` 表示关闭该维度限流；Redis 异常时默认放行。
        """
        if limit <= 0:
            return True, 0
        try:
            count = self._incr(key, window_seconds)
            if count <= limit:
                return True, 0
            return False, max(self._ttl(key), 1)
        except Exception:  # noqa: BLE001
            logger.warning("rate limiter unavailable, allow by default")
            return True, 0

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        """兼容既有调用点：只关心是否允许。"""
        return self.check(key, limit, window_seconds)[0]

    def status(self, key: str) -> tuple[int, int]:
        """只读查看 ``(当前计数, 剩余秒数)``，不增加计数。用于登录失败锁定判断。"""
        try:
            pipe = self.client.pipeline()
            pipe.get(f"rl:{key}")
            pipe.ttl(f"rl:{key}")
            raw_count, raw_ttl = pipe.execute()
            return int(raw_count or 0), max(int(raw_ttl or 0), 0)
        except Exception:  # noqa: BLE001
            return 0, 0

    def reset(self, key: str) -> None:
        """清除计数（登录成功等场景）。"""
        try:
            self.client.delete(f"rl:{key}")
        except Exception:  # noqa: BLE001
            logger.warning("rate limiter reset failed")
