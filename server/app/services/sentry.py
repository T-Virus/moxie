# -*- coding: utf-8 -*-
"""可选 Sentry 接入：未配置 DSN 或未安装 SDK 时静默跳过。"""

from __future__ import annotations

import logging

from ..config import Settings

logger = logging.getLogger("moxie.sentry")


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
