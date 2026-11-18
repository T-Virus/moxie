# -*- coding: utf-8 -*-
"""运营期可热改配置：默认值、DB 持久化、缓存失效与后台权限。"""

from __future__ import annotations

import pytest

from app.models import Account, OperationalSetting
from app.services import runtime_config

from .helpers import db_session


@pytest.fixture(autouse=True)
def _clear_runtime_cache():
    runtime_config.invalidate_telemetry_cache()
    yield
    runtime_config.invalidate_telemetry_cache()


def _promote(app, account_id: int, role: str = "admin") -> None:
    with db_session(app) as session:
        session.get(Account, account_id).role = role
        session.commit()


def test_defaults_come_from_environment(client, app):
    settings = app.state.settings
    settings.client_error_sentry_sample_rate = 0.4
    settings.client_error_sentry_dedupe_window_seconds = 90
    settings.client_error_sentry_dedupe_max_entries = 32
    with db_session(app) as session:
        cfg = runtime_config.get_telemetry_config(session, settings)
    assert cfg["sample_rate"] == 0.4
    assert cfg["dedupe_window_seconds"] == 90
    assert cfg["dedupe_max_entries"] == 32
    assert cfg["source"] == "environment"


def test_set_persists_and_invalidates_cache(client, app):
    settings = app.state.settings
    with db_session(app) as session:
        before = runtime_config.get_telemetry_config(session, settings)
        assert before["source"] == "environment"

        saved = runtime_config.set_telemetry_config(
            session, settings, 1, sample_rate=0.25, dedupe_window_seconds=120,
            dedupe_max_entries=40,
        )
        assert saved["sample_rate"] == 0.25
        assert saved["dedupe_window_seconds"] == 120
        assert saved["dedupe_max_entries"] == 40

        # set 内部已失效缓存：下一次读取必须拿到新值
        after = runtime_config.get_telemetry_config(session, settings)
        assert after["source"] == "database"
        assert after["sample_rate"] == 0.25
        assert after["dedupe_window_seconds"] == 120
        assert after["dedupe_max_entries"] == 40


def test_out_of_range_values_fall_back_to_defaults(client, app):
    settings = app.state.settings
    settings.client_error_sentry_sample_rate = 0.8
    settings.client_error_sentry_dedupe_window_seconds = 60
    with db_session(app) as session:
        cfg = runtime_config.set_telemetry_config(
            session, settings, 1, sample_rate=5.0, dedupe_window_seconds=-1,
            dedupe_max_entries=99999,  # 越界 → 回退 env 默认 64
        )
    assert cfg["sample_rate"] == 0.8
    assert cfg["dedupe_window_seconds"] == 60
    assert cfg["dedupe_max_entries"] == 64


def test_db_failure_degrades_to_defaults(app):
    settings = app.state.settings

    class BrokenSession:
        def get(self, *args, **kwargs):
            raise RuntimeError("db down")

    cfg = runtime_config.get_telemetry_config(BrokenSession(), settings)
    assert cfg["source"] == "environment"
    assert cfg["sample_rate"] == settings.client_error_sentry_sample_rate


def test_admin_can_read_and_update(client, headers, app, account):
    _promote(app, account["account"]["id"])
    resp = client.put(
        "/v1/admin/telemetry-config",
        headers=headers,
        json={"sample_rate": 0.3, "dedupe_window_seconds": 45, "dedupe_max_entries": 24},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["sample_rate"] == 0.3
    assert data["dedupe_window_seconds"] == 45
    assert data["dedupe_max_entries"] == 24
    assert data["source"] == "database"

    got = client.get("/v1/admin/telemetry-config", headers=headers)
    assert got.status_code == 200
    assert got.json()["sample_rate"] == 0.3


def test_non_admin_cannot_update(client, headers):
    resp = client.put(
        "/v1/admin/telemetry-config",
        headers=headers,
        json={"sample_rate": 0, "dedupe_window_seconds": 0, "dedupe_max_entries": 1},
    )
    assert resp.status_code in (401, 403)


def test_legacy_row_without_max_entries_gets_default(client, app):
    """旧 DB 行（value 缺 dedupe_max_entries）读取时被默认值补齐，无需迁移。"""
    settings = app.state.settings
    with db_session(app) as session:
        session.add(
            OperationalSetting(
                key=runtime_config.TELEMETRY_KEY,
                value={"sample_rate": 0.5, "dedupe_window_seconds": 30},  # 无 max_entries
            )
        )
        session.commit()
        cfg = runtime_config.get_telemetry_config(session, settings)
    assert cfg["dedupe_max_entries"] == settings.client_error_sentry_dedupe_max_entries
    assert cfg["sample_rate"] == 0.5


def test_telemetry_cache_ttl_expires(client, app):
    """60s TTL：命中期内读旧值，过期后重新查库拿新值。"""
    settings = app.state.settings
    with db_session(app) as session:
        runtime_config.set_telemetry_config(
            session, settings, 1, sample_rate=0.1, dedupe_window_seconds=10,
            dedupe_max_entries=8,
        )
        session.commit()
        t0 = 1000.0
        first = runtime_config.get_telemetry_config(session, settings, now=t0)
        assert first["sample_rate"] == 0.1

        # 直接改库（绕过 set 的缓存失效），模拟另一 worker 写入
        row = session.get(OperationalSetting, runtime_config.TELEMETRY_KEY)
        row.value = {**row.value, "sample_rate": 0.9}
        session.commit()

        within = runtime_config.get_telemetry_config(session, settings, now=t0 + 59)
        assert within["sample_rate"] == 0.1  # TTL 内仍读缓存旧值
        expired = runtime_config.get_telemetry_config(session, settings, now=t0 + 61)
        assert expired["sample_rate"] == 0.9  # TTL 过期后读库新值
