# -*- coding: utf-8 -*-
"""租户级限流：默认关闭，开启后按 account_id 独立计数。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.errors import ApiError
from app.rate_limit import check_tenant_limit


class _Limiter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self, key: str, limit: int, window: int):
        self.calls.append(key)
        return (len(self.calls) == 1, 0 if len(self.calls) == 1 else 30)


def _request(limit: int, limiter: _Limiter):
    state = SimpleNamespace(
        settings=SimpleNamespace(tenant_rate_limit_per_minute=limit),
        limiter=limiter,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_tenant_rate_limit_disabled_by_default() -> None:
    limiter = _Limiter()
    check_tenant_limit(_request(0, limiter), 7)
    assert limiter.calls == []


def test_tenant_rate_limit_uses_account_scope() -> None:
    limiter = _Limiter()
    request = _request(1, limiter)
    check_tenant_limit(request, 7)
    with pytest.raises(ApiError) as exc:
        check_tenant_limit(request, 7)
    assert exc.value.status_code == 429
    assert exc.value.code == "tenant_rate_limited"
    assert limiter.calls == ["tenant:7", "tenant:7"]
