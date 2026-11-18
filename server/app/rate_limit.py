# -*- coding: utf-8 -*-
"""租户级限流：与既有 IP / 接口维度并行，默认关闭。"""

from __future__ import annotations

from fastapi import Request

from .errors import ApiError
from .metrics import increment


def check_tenant_limit(request: Request, account_id: int) -> None:
    settings = request.app.state.settings
    limit = settings.tenant_rate_limit_per_minute
    if limit <= 0:
        return
    limiter = request.app.state.limiter
    allowed, retry_after = limiter.check(f"tenant:{account_id}", limit, 60)
    if not allowed:
        increment("moxie_rate_limited_total", scope="tenant")
        raise ApiError(
            429,
            "tenant_rate_limited",
            "当前账号操作过于频繁，请稍后再试",
            headers={"Retry-After": str(retry_after)},
        )
