# -*- coding: utf-8 -*-
"""第十三批：可观测配置灰度生效（按错误指纹稳定分桶）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import runtime_config as rc


@pytest.fixture(autouse=True)
def _reset_telemetry_cache():
    """灰度比例写库后必须清掉 60s 运营配置缓存，避免污染后续用例的采样判定。"""
    rc.invalidate_telemetry_cache()
    yield
    rc.invalidate_telemetry_cache()


def _base_cfg(**overrides):
    cfg = {
        "sample_rate": 1.0,
        "dedupe_window_seconds": 60,
        "dedupe_max_entries": 64,
        "canary_percent": 0,
        "canary": {},
    }
    cfg.update(overrides)
    return cfg


def test_no_canary_always_base():
    cfg = _base_cfg()
    for key in ("a", "b", "whatever"):
        assert rc.effective_for_bucket(cfg, key)["sample_rate"] == 1.0


def test_canary_disabled_uses_base_even_with_canary_configured():
    cfg = _base_cfg(canary_percent=0, canary={"sample_rate": 0.0})
    assert rc.effective_for_bucket(cfg, "fp-1")["sample_rate"] == 1.0


def test_full_canary_applies_to_all_buckets():
    cfg = _base_cfg(canary_percent=100, canary={"sample_rate": 0.1})
    for key in ("a", "b", "c", "fp-123"):
        assert rc.effective_for_bucket(cfg, key)["sample_rate"] == 0.1


def test_partial_canary_only_overrides_configured_fields():
    cfg = _base_cfg(canary_percent=100, canary={"sample_rate": 0.2})
    eff = rc.effective_for_bucket(cfg, "x")
    assert eff["sample_rate"] == 0.2
    assert eff["dedupe_window_seconds"] == 60  # 回退基线
    assert eff["dedupe_max_entries"] == 64


def test_bucket_assignment_is_stable():
    """同一指纹永远同一档；100 个样本里既有基线也有灰度（50%）。"""
    cfg = _base_cfg(canary_percent=50, canary={"sample_rate": 0.0})
    results = {}
    for i in range(100):
        key = f"fingerprint-{i}"
        rate = rc.effective_for_bucket(cfg, key)["sample_rate"]
        assert rc.effective_for_bucket(cfg, key)["sample_rate"] == rate  # 重复调用稳定
        results[key] = rate
    assert any(v == 0.0 for v in results.values())
    assert any(v == 1.0 for v in results.values())


def test_empty_bucket_key_falls_back_to_base():
    cfg = _base_cfg(canary_percent=100, canary={"sample_rate": 0.0})
    assert rc.effective_for_bucket(cfg, "")["sample_rate"] == 1.0


def test_sanitize_canary_rejects_invalid_and_unknown_fields():
    defaults = rc.telemetry_defaults(type("S", (), {
        "client_error_sentry_sample_rate": 1.0,
        "client_error_sentry_dedupe_window_seconds": 60,
        "client_error_sentry_dedupe_max_entries": 64,
    })())
    cfg = rc._sanitize({
        "sample_rate": 0.5,
        "dedupe_window_seconds": 30,
        "dedupe_max_entries": 16,
        "canary_percent": 150,  # 非法 → 回退 0
        "canary": {"sample_rate": 2.0, "dedupe_window_seconds": 12, "evil": "x"},
    }, defaults)
    assert cfg["canary_percent"] == 0
    assert cfg["canary"] == {"dedupe_window_seconds": 12}  # 采样率非法剔除，未知键忽略


def test_admin_update_accepts_canary_and_api_reflects(client, headers, app, account):
    # 提权
    from app.models import Account
    from .helpers import db_session
    with db_session(app) as s:
        s.get(Account, account["account"]["id"]).role = "admin"
        s.commit()

    resp = client.put("/v1/admin/telemetry-config", headers=headers, json={
        "sample_rate": 0.8,
        "dedupe_window_seconds": 60,
        "dedupe_max_entries": 32,
        "canary_percent": 100,
        "canary": {"sample_rate": 0.1},
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["canary_percent"] == 100
    assert data["canary"]["sample_rate"] == 0.1


# —— 第十六批：灰度命中档位日志标签 -------------------------------------------

def test_bucket_tier_matches_effective_for_bucket():
    """bucket_tier 判定必须与 effective_for_bucket 同桶同档，日志标签才可信。"""
    cfg = _base_cfg(canary_percent=60, canary={"sample_rate": 0.1})
    for key in ("fp-a", "fp-b", "fp-c", "错误指纹-1", "错误指纹-2"):
        tier = rc.bucket_tier(cfg, key)
        effective = rc.effective_for_bucket(cfg, key)
        hit_canary = effective["sample_rate"] == 0.1
        assert (tier["tier"] == "canary") is hit_canary, key
        assert tier["percent"] == 60
        assert 0 <= tier["bucket"] < 100


def test_bucket_tier_baseline_when_canary_off():
    cfg = _base_cfg(canary_percent=0, canary={"sample_rate": 0.1})
    tier = rc.bucket_tier(cfg, "any")
    assert tier["tier"] == "baseline"
    assert tier["bucket"] == -1


def test_bucket_tier_stable_for_same_key():
    cfg = _base_cfg(canary_percent=50, canary={"sample_rate": 0.0})
    a = rc.bucket_tier(cfg, "stable-key")
    b = rc.bucket_tier(cfg, "stable-key")
    assert a == b
