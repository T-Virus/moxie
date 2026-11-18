# -*- coding: utf-8 -*-
"""运营期可热改配置：DB 持久化 + 短 TTL 进程内缓存。

写接口由 admin 更新 DB 并使本进程缓存失效；其它 worker 最多 TTL 秒后收敛，
避免为极低频率的配置变更引入跨进程读放大。DB 不可用时一律回退环境变量默认值，
绝不让配置读取把前端错误上报端点拖挂。
"""

from __future__ import annotations

import hashlib
import logging
import time

from sqlalchemy.orm import Session

from ..config import Settings
from ..db import utcnow
from ..models import OperationalSetting

logger = logging.getLogger("moxie.runtime_config")

TELEMETRY_KEY = "telemetry"
_TELEMETRY_TTL = 60.0
_TELEMETRY_CACHE: tuple[float, dict] | None = None
# 去重 zset 容量上限的合法范围（防止畸形值让单 key 无限膨胀或退化成全量放行）
_DEDUPE_MAX_ENTRIES_MIN = 1
_DEDUPE_MAX_ENTRIES_MAX = 1024


# 灰度档合法字段：只覆盖这三项，避免 canary 夹带未知键污染契约
_CANARY_FIELDS = ("sample_rate", "dedupe_window_seconds", "dedupe_max_entries")


def telemetry_defaults(settings: Settings) -> dict:
    """环境变量中的默认值（同时也是后台配置的合法范围）。

    canary_percent=0 表示不启用灰度（全量走基线值）；canary 为空表示未配置灰度档。
    """
    return {
        "sample_rate": min(1.0, max(0.0, settings.client_error_sentry_sample_rate)),
        "dedupe_window_seconds": min(
            86400, max(0, settings.client_error_sentry_dedupe_window_seconds)
        ),
        "dedupe_max_entries": min(
            _DEDUPE_MAX_ENTRIES_MAX,
            max(_DEDUPE_MAX_ENTRIES_MIN, settings.client_error_sentry_dedupe_max_entries),
        ),
        "canary_percent": 0,
        "canary": {},
    }


def _sanitize_canary(value: object) -> dict:
    """灰度档只保留合法字段且按各自范围校验，非法字段直接忽略并回退基线。"""
    if not isinstance(value, dict):
        return {}
    out: dict = {}
    for key in _CANARY_FIELDS:
        if key not in value:
            continue
        raw = value[key]
        if key == "sample_rate":
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0.0 <= raw <= 1.0:
                out[key] = float(raw)
        elif key == "dedupe_window_seconds":
            if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 86400:
                out[key] = raw
        else:
            if (
                isinstance(raw, int)
                and not isinstance(raw, bool)
                and _DEDUPE_MAX_ENTRIES_MIN <= raw <= _DEDUPE_MAX_ENTRIES_MAX
            ):
                out[key] = raw
    return out


def _sanitize(value: object, defaults: dict) -> dict:
    """库里是被信任的 admin 写入，但仍按范围二次校验，防手工改库注入异常值。"""
    result = dict(defaults)
    if not isinstance(value, dict):
        return result
    rate = value.get("sample_rate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0.0 <= rate <= 1.0:
        result["sample_rate"] = float(rate)
    window = value.get("dedupe_window_seconds")
    if isinstance(window, int) and not isinstance(window, bool) and 0 <= window <= 86400:
        result["dedupe_window_seconds"] = window
    cap = value.get("dedupe_max_entries")
    if (
        isinstance(cap, int)
        and not isinstance(cap, bool)
        and _DEDUPE_MAX_ENTRIES_MIN <= cap <= _DEDUPE_MAX_ENTRIES_MAX
    ):
        result["dedupe_max_entries"] = cap
    # 灰度：比例 0..100，灰度档按字段范围二次校验
    percent = value.get("canary_percent")
    if isinstance(percent, int) and not isinstance(percent, bool) and 0 <= percent <= 100:
        result["canary_percent"] = percent
    result["canary"] = _sanitize_canary(value.get("canary"))
    return result


def _bucket(cfg: dict, bucket_key: str) -> tuple[int, int, dict]:
    """灰度分桶的唯一实现：返回 (桶号, 生效比例, 灰度档)。

    未启用（比例为 0 / 灰度档为空 / 无键）时桶号为 -1。
    effective_for_bucket 与 bucket_tier 共用本函数，避免判定与日志标注漂移。
    """
    percent = cfg.get("canary_percent") or 0
    canary = cfg.get("canary") or {}
    if not isinstance(percent, int) or percent <= 0 or not canary or not bucket_key:
        return -1, percent if isinstance(percent, int) else 0, canary if isinstance(canary, dict) else {}
    digest = hashlib.sha256(bucket_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100, percent, canary if isinstance(canary, dict) else {}


def effective_for_bucket(cfg: dict, bucket_key: str) -> dict:
    """按 bucket_key 稳定哈希决定该样本走基线还是灰度档。

    · 同一 bucket_key 永远得到同一结果（sha256 前 8 字节取模），不会在基线/灰度间抖动；
    · canary_percent=0 或灰度档为空时全部走基线；
    · 灰度档只覆盖已配置的字段，其余回退基线值。
    返回仅含业务字段（不含 source/canary_percent 等元信息），供 should_forward 直接消费。
    """
    base = {key: cfg[key] for key in _CANARY_FIELDS if key in cfg}
    bucket, percent, canary = _bucket(cfg, bucket_key)
    if bucket < 0 or bucket >= percent:
        return base
    effective = dict(base)
    effective.update({k: v for k, v in canary.items() if k in _CANARY_FIELDS})
    return effective


def bucket_tier(cfg: dict, bucket_key: str) -> dict:
    """返回某 bucket_key 的灰度命中档位（不改动生效配置）。

    供遥测日志/指标标注「这次请求命中基线还是灰度、当时灰度比例多少」，
    与 effective_for_bucket 共用 _bucket，保证判定一致。
    """
    bucket, percent, _ = _bucket(cfg, bucket_key)
    return {
        "tier": "canary" if 0 <= bucket < percent else "baseline",
        "percent": percent,
        "bucket": bucket,
    }


def invalidate_telemetry_cache() -> None:
    global _TELEMETRY_CACHE
    _TELEMETRY_CACHE = None


def get_telemetry_config(
    db: Session, settings: Settings, *, now: float | None = None
) -> dict:
    """读取当前生效配置；缓存命中不查库，DB 异常降级默认值。"""
    global _TELEMETRY_CACHE
    now = time.monotonic() if now is None else now
    defaults = telemetry_defaults(settings)
    if _TELEMETRY_CACHE is not None and now - _TELEMETRY_CACHE[0] < _TELEMETRY_TTL:
        return dict(_TELEMETRY_CACHE[1])
    try:
        row = db.get(OperationalSetting, TELEMETRY_KEY)
        cfg = _sanitize(row.value if row else None, defaults)
        cfg.update(
            source="database" if row else "environment",
            updated_at=row.updated_at.isoformat() if row and row.updated_at else None,
            updated_by=row.updated_by if row else None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取运营配置失败，使用默认值：%s", type(exc).__name__)
        cfg = {**defaults, "source": "environment", "updated_at": None, "updated_by": None}
    _TELEMETRY_CACHE = (now, cfg)
    return dict(cfg)


def set_telemetry_config(
    db: Session,
    settings: Settings,
    admin_id: int,
    *,
    sample_rate: float,
    dedupe_window_seconds: int,
    dedupe_max_entries: int,
    canary_percent: int = 0,
    canary: dict | None = None,
) -> dict:
    """写入并立即对本进程生效；返回最终落库值。支持灰度档（比例 + 覆盖字段）。"""
    cfg = _sanitize(
        {
            "sample_rate": sample_rate,
            "dedupe_window_seconds": dedupe_window_seconds,
            "dedupe_max_entries": dedupe_max_entries,
            "canary_percent": canary_percent,
            "canary": canary or {},
        },
        telemetry_defaults(settings),
    )
    row = db.get(OperationalSetting, TELEMETRY_KEY)
    if row is None:
        row = OperationalSetting(key=TELEMETRY_KEY, value=cfg)
        db.add(row)
    else:
        row.value = cfg
    row.updated_at = utcnow()
    row.updated_by = admin_id
    db.commit()
    invalidate_telemetry_cache()
    return dict(cfg)
