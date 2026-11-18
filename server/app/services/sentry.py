# -*- coding: utf-8 -*-
"""可选 Sentry 接入：未配置 DSN 或未安装 SDK 时静默跳过。"""

from __future__ import annotations

import hashlib
import logging
import time

from ..config import Settings

logger = logging.getLogger("moxie.sentry")

# 进程内去重表：fingerprint -> 上次转发的时间戳（monotonic）。
# 多 worker 部署时每个进程各自去重，配合 Sentry 服务端去重再收敛一层，
# 目标是削掉「同一错误风暴」的绝大部分重复，不追求跨进程精确一次。
_REPORT_CACHE: dict[str, float] = {}
_REPORT_CACHE_MAX = 2048  # 上限保护：错误指纹无限增长会吃内存，超限时整体淘汰一半
_REPORT_CACHE_TTL = 300.0  # 缓存条目最长保留，防止长期不重的指纹永久占位


def init_sentry(settings: Settings) -> bool:
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.info("未安装 sentry-sdk，跳过 Sentry 初始化")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.env,
            traces_sample_rate=0.0,
            send_default_pii=False,
        )
        logger.info("Sentry 已启用（env=%s）", settings.env)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sentry 初始化失败，已跳过：%s", type(exc).__name__)
        return False


def error_fingerprint(*, code: str, message: str, path: str, source: str) -> str:
    """错误指纹：同一类错误（相同 code/脱敏 message/path/source）归一到同一 key。

    故意不含 request_id / ts，避免同一错误风暴因每次请求 id 不同而被当成新错误。
    """
    raw = f"{source}|{code}|{path}|{message}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _sample_by_fingerprint(fp: str, rate: float) -> bool:
    """按指纹哈希前 8 位做稳定抽样：同一错误恒定被采中或不采中，避免抖动式采样。"""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    bucket = int(fp[:8], 16) / 0xFFFFFFFF
    return bucket < rate


_DEDUPE_KEY_PREFIX = "moxie:sentry:dedupe:sw:"
# WATCH 乐观事务重试次数：冲突时重读窗口再判定，耗尽则回退本地缓存（宁可多报不阻断）。
_DEDUPE_MAX_RETRIES = 3
# 单个去重 key 的 zset 成员数上限：正常滑动窗口只留 1 条，此上限是防御时钟回拨 /
# 跨 worker 时间大幅偏差导致旧点堆积的保险丝。超限在同一事务内淘汰最旧条目。
_DEDUPE_MAX_ENTRIES = 64


def _dedupe_in_redis(
    client,
    fingerprint: str,
    window: int,
    epoch: float,
    max_entries: int = _DEDUPE_MAX_ENTRIES,
) -> bool | None:
    """用 Redis zset + WATCH/MULTI 乐观事务做跨进程滑动窗口去重。

    滑动窗口：zset 只记录最近一次「放行」的 epoch 秒。仅当窗口 [epoch-window, epoch]
    内没有任何记录时才放行并写入当前 epoch；窗口随放行时间平移，没有固定窗口的边界
    双发问题。WATCH/MULTI 把「读窗口 → 判定 → 占位」包进一个原子事务：期间任何 worker
    改了这个 key 都会触发 WatchError 并重读，彻底消除并发穿透。

    返回 True=放行（窗口内首次）、False=窗口内已上报；None=Redis 不可用或重试耗尽，
    调用方回退本地缓存。
    """
    from redis.exceptions import WatchError

    key = f"{_DEDUPE_KEY_PREFIX}{fingerprint}"
    member = f"{epoch:.6f}"
    cap = max(1, int(max_entries))
    for _ in range(_DEDUPE_MAX_RETRIES):
        try:
            with client.pipeline() as pipe:
                pipe.watch(key)
                # 清掉窗口之前的旧记录（<= 边界），避免时钟回拨时残留旧点
                pipe.zremrangebyscore(key, 0, epoch - window)
                seen = int(pipe.zcard(key))
                if seen > 0:
                    # 窗口内已有记录：命中去重。若历史数据已超限（如旧版本遗留的膨胀 key），
                    # 顺手裁剪到 cap —— 仅在超限时发写命令，正常路径仍是纯读。
                    if seen > cap:
                        pipe.zremrangebyrank(key, 0, -(cap + 1))
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.zadd(key, {member: epoch})
                # 容量上限：原子裁剪到最近 cap 条（按 score 排名从旧到新，删最旧的）。
                # zremrangebyrank 的 end 是负数索引且含端点，须用 -(cap+1) 才恰好保留 cap 条。
                pipe.zremrangebyrank(key, 0, -(cap + 1))
                # 兜底 TTL：时钟回拨导致 score 清理失效时，key 也会在 window+1 秒后消失
                pipe.expire(key, max(2, window + 1))
                pipe.execute()
                return True
        except WatchError:
            continue  # 其他 worker 抢先占位：重读窗口再判定
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis 去重不可用，回退进程内：%s", type(exc).__name__)
            return None
    return None


def should_forward(
    settings: Settings,
    *,
    fingerprint: str,
    now: float | None = None,
    epoch: float | None = None,
    redis_client=None,
    sample_rate: float | None = None,
    dedupe_window_seconds: int | None = None,
    dedupe_max_entries: int | None = None,
) -> bool:
    """采样 + 时间窗去重决策，决定是否把这条前端错误转发到 Sentry。

    - 采样：按指纹哈希稳定抽样，配置 client_error_sentry_sample_rate（本地确定性计算）。
    - 去重：同一指纹在 client_error_sentry_dedupe_window_seconds 内只放行一次。
      传入 Redis 客户端时用 zset 滑动窗口 + WATCH/MULTI 跨 worker 原子去重；未传或
      Redis 异常时回退进程内缓存（单进程仍有效，多进程退化为各自去重，不阻断上报）。
    - 时间基准：本地缓存用 monotonic（单调、不受系统时钟回拨影响）；Redis 滑动窗口用
      epoch 墙钟（跨 worker 共享同一把尺子）。测试可注入 now/epoch 推进时钟而不 sleep。
    - 未配置 DSN 时直接 False（连缓存都不写）。
    """
    if not (settings.sentry_dsn or "").strip():
        return False
    rate = (
        min(1.0, max(0.0, sample_rate))
        if sample_rate is not None
        else min(1.0, max(0.0, settings.client_error_sentry_sample_rate))
    )
    if not _sample_by_fingerprint(fingerprint, rate):
        return False

    now = now if now is not None else time.monotonic()
    window = (
        max(0, dedupe_window_seconds)
        if dedupe_window_seconds is not None
        else max(0, settings.client_error_sentry_dedupe_window_seconds)
    )
    if window <= 0:
        return True  # 窗口为 0 表示关闭去重，仅采样

    if redis_client is not None:
        decision = _dedupe_in_redis(
            redis_client, fingerprint, window,
            epoch if epoch is not None else time.time(),
            max_entries=(
                _DEDUPE_MAX_ENTRIES
                if dedupe_max_entries is None
                else dedupe_max_entries
            ),
        )
        if decision is not None:
            return decision

    last = _REPORT_CACHE.get(fingerprint)
    if last is not None and now - last < window:
        return False
    _REPORT_CACHE[fingerprint] = now

    # 容量与 TTL 清理：超限淘汰最早的一半，顺带清掉过期条目
    if len(_REPORT_CACHE) > _REPORT_CACHE_MAX:
        cutoff = now - max(window, _REPORT_CACHE_TTL)
        stale = [k for k, ts in _REPORT_CACHE.items() if ts < cutoff]
        for k in stale:
            _REPORT_CACHE.pop(k, None)
        if len(_REPORT_CACHE) > _REPORT_CACHE_MAX:
            for k, _ in sorted(_REPORT_CACHE.items(), key=lambda kv: kv[1])[: _REPORT_CACHE_MAX // 2]:
                _REPORT_CACHE.pop(k, None)
    return True


def client_error_to_sentry(settings: Settings, *, level: str, code: str, message: str,
                           path: str, source: str, source_request_id: str) -> bool:
    """把脱敏后的前端错误转发到 Sentry（匿名事件，不带 PII/用户身份）。

    只在配置了 DSN 且已安装 SDK 时生效；任何失败都吞掉，绝不影响上报端点返回。
    入参必须已由 telemetry.redact()/safe_path() 处理过，这里不再二次脱敏。
    """
    if not (settings.sentry_dsn or "").strip():
        return False
    try:
        import sentry_sdk
    except ImportError:
        return False
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_level("error" if level == "error" else "warning")
            scope.set_tag("source", source[:16])
            scope.set_tag("client_path", path[:500] or "-")
            scope.set_tag("error_code", code[:80])
            scope.set_extra("source_request_id", source_request_id[:64] or "-")
            sentry_sdk.capture_message(message[:1000] or code[:80])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("转发前端错误到 Sentry 失败：%s", type(exc).__name__)
        return False
