# -*- coding: utf-8 -*-
"""前端错误上报端点：匿名可达、脱敏、限流、requestId 关联。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.telemetry import redact, safe_path


@pytest.fixture(autouse=True)
def _clear_sentry_dedupe():
    """每个用例独立：清掉进程内 Sentry 去重缓存，避免用例间指纹互相干扰。"""
    from app.services import sentry

    sentry._REPORT_CACHE.clear()
    yield
    sentry._REPORT_CACHE.clear()


def test_redact_hides_tokens_and_jwt():
    text = (
        "failed token=abc123 api_key: sk-xyz Bearer eyJaaa.bbb.ccc "
        "GET /x?password=hunter2&page=1"
    )
    out = redact(text)
    assert "abc123" not in out
    assert "sk-xyz" not in out
    assert "hunter2" not in out
    assert "[redacted]" in out
    # Bearer 后的 JWT 不应残留
    assert "eyJaaa.bbb.ccc" not in out


def test_redact_empty_is_safe():
    assert redact("") == ""
    assert redact("普通错误消息") == "普通错误消息"


def test_safe_path_drops_query_and_fragment():
    assert safe_path("https://x.test/v1/runs?page=2&token=secret#frag") == "/v1/runs"
    assert safe_path("/v1/runs") == "/v1/runs"
    assert safe_path("") == ""


def test_report_endpoint_is_anonymous_and_records_request_id(client):
    # 用 mock patch 目标 logger 的方法：不受 caplog / root handler / logger level 等
    # 全局状态影响，全量运行时也稳定（其他测试可能改过 configure_logging）。
    with patch("app.api.telemetry.logger") as mock_logger:
        resp = _post_report(client)

    assert resp.status_code == 202, resp.text
    assert resp.json() == {"accepted": True}
    assert resp.headers.get("x-request-id")

    mock_logger.error.assert_called_once()
    call_kwargs = mock_logger.error.call_args.kwargs["extra"]
    assert call_kwargs["error_code"] == "js_error"
    assert call_kwargs["source_request_id"] == "req-source-123"
    assert call_kwargs["source_trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert call_kwargs["client_path"] == "/runs"
    assert "leakme" not in call_kwargs["error_message"]
    assert call_kwargs["source"] == "client"


def test_prometheus_label_values_are_escaped():
    """不可信 source 进入指标标签时不得破坏 Prometheus 文本格式。"""
    from app import metrics

    metrics.reset()
    try:
        metrics.increment("moxie_client_error_reports_total", source='evil"\\x\nnext')
        text = metrics.render()
        assert 'source="evil\\"\\\\x\\nnext"' in text
        assert len([line for line in text.splitlines() if line.startswith("moxie_client_error")]) == 1
    finally:
        metrics.reset()


def test_telemetry_rejects_unknown_source(client):
    resp = client.post(
        "/v1/telemetry/client-error",
        json={
            "level": "error",
            "code": "js_error",
            "message": "boom",
            "source": "webhook",
            "url": "/x",
            "request_id": "r1",
            "ts": "2026-11-18T00:00:00Z",
        },
    )
    assert resp.status_code == 422


def _post_report(client):
    return client.post(
        "/v1/telemetry/client-error",
        json={
            "level": "error",
            "code": "js_error",
            "message": "boom token=leakme",
            "source": "client",
            "url": "https://x.test/runs?token=leakme",
            "request_id": "req-source-123",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "ts": "2026-11-17T00:00:00Z",
        },
    )


def test_report_endpoint_validates_payload(client):
    # 超长 message 被 schema 拒绝
    resp = client.post(
        "/v1/telemetry/client-error",
        json={"message": "x" * 2000},
    )
    assert resp.status_code == 422


def test_report_endpoint_rate_limited(client, app):
    payload = {"code": "x", "message": "y"}
    # 把限流阈值调到 1，验证第二次被拒
    app.state.settings.client_error_rate_limit_per_minute = 1
    first = client.post("/v1/telemetry/client-error", json=payload)
    assert first.status_code == 202
    second = client.post("/v1/telemetry/client-error", json=payload)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in second.headers



def _fake_sentry():
    """测试环境未安装 sentry-sdk：注入假的 sys.modules['sentry_sdk']。"""
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    push_scope = MagicMock()
    capture_message = MagicMock()
    fake = SimpleNamespace(push_scope=push_scope, capture_message=capture_message)
    return patch.dict(sys.modules, {"sentry_sdk": fake}), push_scope, capture_message


def test_forward_to_sentry_when_configured(client, app):
    """配置了 DSN 且 SDK 可用时转发脱敏后的错误。"""
    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    modules, push_scope, capture = _fake_sentry()
    with modules, patch("app.api.telemetry.logger"):
        resp = _post_report(client)

    assert resp.status_code == 202
    capture.assert_called_once()
    sent = capture.call_args.args[0]
    assert "leakme" not in sent  # message 已脱敏
    scope = push_scope.return_value.__enter__.return_value
    tags = {c.args[0]: c.args[1] for c in scope.set_tag.call_args_list}
    assert tags.get("client_path") == "/runs"
    assert tags.get("source") == "client"


def test_no_forward_without_dsn(client, app):
    """未配置 DSN 时不调用 SDK，端点仍正常返回。"""
    app.state.settings.sentry_dsn = ""
    modules, _push, capture = _fake_sentry()
    with modules, patch("app.api.telemetry.logger"):
        resp = _post_report(client)
    assert resp.status_code == 202
    capture.assert_not_called()


def test_sentry_failure_does_not_break_endpoint(client, app):
    """SDK 抛异常时上报端点仍返回 202。"""
    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    modules, push_scope, _capture = _fake_sentry()
    push_scope.side_effect = RuntimeError("sentry down")
    with modules, patch("app.api.telemetry.logger"):
        resp = _post_report(client)
    assert resp.status_code == 202


def test_dedupe_blocks_same_error_within_window(client, app):
    """同一错误指纹在窗口内只转发一次（错误风暴去重）。"""
    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    modules, _push, capture = _fake_sentry()
    with modules, patch("app.api.telemetry.logger"):
        first = _post_report(client)
        second = _post_report(client)
    assert first.status_code == 202 and second.status_code == 202
    assert capture.call_count == 1, "窗口内相同错误被重复转发"


def test_dedupe_window_expiry_allows_reforward(client, app):
    """窗口过期后同一错误可再次转发（用注入 now 推进时钟，不 sleep）。"""
    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    fp = sentry.error_fingerprint(code="js_error", message="boom", path="/runs", source="client")
    assert sentry.should_forward(app.state.settings, fingerprint=fp, now=1000.0) is True
    assert sentry.should_forward(app.state.settings, fingerprint=fp, now=1030.0) is False
    assert sentry.should_forward(app.state.settings, fingerprint=fp, now=1061.0) is True


def test_sample_rate_zero_disables_forward(client, app):
    """采样率 0：不转发、不写去重缓存。"""
    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 0.0
    fp = sentry.error_fingerprint(code="x", message="y", path="/", source="client")
    assert sentry.should_forward(app.state.settings, fingerprint=fp, now=1000.0) is False
    assert sentry._REPORT_CACHE == {}


def test_sample_rate_is_stable_by_fingerprint(app):
    """采样按指纹哈希稳定：同一指纹恒定同结果，不同指纹在部分采样下有分化。"""
    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 0.5
    app.state.settings.client_error_sentry_dedupe_window_seconds = 0  # 关去重只测采样
    results = set()
    for i in range(50):
        fp = sentry.error_fingerprint(code="e", message=f"m{i}", path="/p", source="client")
        results.add(sentry.should_forward(app.state.settings, fingerprint=fp))
    assert len(results) == 2, "50 个不同指纹在 50% 采样下应同时出现采中/未采中"


def test_redis_dedupe_is_shared_and_atomic(app):
    """同一 Redis 实例（模拟多 worker 共享）中相同指纹在滑动窗口内只放行一次。"""
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = sentry.error_fingerprint(code="boom", message="x", path="/runs", source="client")
    key = sentry._DEDUPE_KEY_PREFIX + fp

    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=1000.0
    ) is True
    # 第二个 worker 用同指纹：被 Redis 滑动窗口拦下，与进程内缓存无关（epoch 仍在窗口内）
    sentry._REPORT_CACHE.clear()
    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=1030.0
    ) is False
    assert shared.zcard(key) == 1

    # 另一个错误指纹不受影响
    other = sentry.error_fingerprint(code="other", message="x", path="/runs", source="client")
    assert sentry.should_forward(
        app.state.settings, fingerprint=other, redis_client=shared, epoch=1030.0
    ) is True


def test_redis_dedupe_sliding_window_no_boundary_burst(app):
    """滑动窗口：固定窗口会在边界瞬时双发，滑动窗口按每次放行时间平移，窗口内始终只放行一次。"""
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = "sliding-window-fingerprint"
    fwd = lambda e: sentry.should_forward(  # noqa: E731 - 测试内简写
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=e
    )

    # t=1000 放行；t=1059 仍在同一窗口内被拦；t=1061 时 1000 滑出窗口，重新放行。
    assert fwd(1000.0) is True
    assert fwd(1059.0) is False
    assert fwd(1061.0) is True
    # 固定窗口若按自然分钟切分，59→61 分属两窗会双发；滑动窗口以 1000→1061 锚定，只放行两次。
    assert fwd(1062.0) is False


def test_redis_dedupe_expiry_allows_reforward(app):
    """窗口记录滑出/被清后同一错误可再次转发（不 sleep，推进 epoch 模拟）。"""
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = "expiry-fingerprint"

    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=1000.0
    ) is True
    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=1001.0
    ) is False
    # 推进到 1061：1000 已滑出窗口，可再次转发
    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared, epoch=1061.0
    ) is True


def test_redis_failure_falls_back_to_process_cache(app):
    """Redis 异常时回退进程内去重，既不放宽成全量也不阻断上报。"""
    from app.services import sentry

    class BrokenRedis:
        def pipeline(self, *args, **kwargs):
            raise RuntimeError("redis down")

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    fp = "fallback-fingerprint"
    broken = BrokenRedis()

    assert sentry.should_forward(app.state.settings, fingerprint=fp, redis_client=broken, now=1000.0) is True
    assert sentry.should_forward(app.state.settings, fingerprint=fp, redis_client=broken, now=1030.0) is False


def test_redis_dedupe_zset_capacity_trims_oldest(app):
    """命中去重时把膨胀的 zset 裁剪到 cap 条，保留最新的、淘汰最旧的，且 TTL 未被破坏。

    注：正常滑动窗口的 add 路径只会写入 1 条（score 清理已先删旧点），zset 超限只会
    来自时钟回拨 / 旧版本遗留数据，裁剪发生在 reject 路径。
    """
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = "capacity-fingerprint"
    key = sentry._DEDUPE_KEY_PREFIX + fp

    # 人为塞入 10 条全部落在窗口内的旧记录（score 单调递增），模拟异常膨胀
    for i in range(10):
        shared.zadd(key, {f"{990.0 + i:.6f}": 990.0 + i})
    shared.expire(key, 59)

    # epoch=1000 落在窗口内 → 去重拦截，但顺手裁剪到最新 3 条
    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared,
        epoch=1000.0, dedupe_max_entries=3,
    ) is False
    members = shared.zrange(key, 0, -1, withscores=True)
    assert len(members) == 3, members
    assert [s for _, s in members] == [997.0, 998.0, 999.0]  # 最旧的 990.. 被淘汰
    assert shared.ttl(key) > 0  # 裁剪后 TTL 仍在


def test_redis_dedupe_capacity_reject_path_self_heals(app):
    """命中去重的 reject 路径若遇到历史超限 key，也会顺手裁剪到 cap。"""
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = "capacity-reject-fingerprint"
    key = sentry._DEDUPE_KEY_PREFIX + fp

    for i in range(8):
        shared.zadd(key, {f"{1000.0 + i:.6f}": 1000.0 + i})  # 全部在窗口内

    # 窗口内已有记录 → 去重拦截（False），但超限 key 被裁剪到 2 条
    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared,
        epoch=1003.0, dedupe_max_entries=2,
    ) is False
    assert shared.zcard(key) == 2
    members = [s for _, s in shared.zrange(key, 0, -1, withscores=True)]
    assert members == [1006.0, 1007.0]  # 保留最新两条


@pytest.mark.parametrize("cap", [1, 5, 64])
def test_redis_dedupe_capacity_various_caps(app, cap):
    """cap=1/5/64 均能正确封顶；cap=1 只保留最新一条且不误删。"""
    import fakeredis

    from app.services import sentry

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    app.state.settings.client_error_sentry_sample_rate = 1.0
    app.state.settings.client_error_sentry_dedupe_window_seconds = 60
    shared = fakeredis.FakeRedis(decode_responses=True)
    fp = f"cap-{cap}-fingerprint"
    key = sentry._DEDUPE_KEY_PREFIX + fp

    # 塞入 20 条窗口内记录；cap=64 时不触顶，保持 20 条
    for i in range(20):
        shared.zadd(key, {f"{990.0 + i:.6f}": 990.0 + i})

    assert sentry.should_forward(
        app.state.settings, fingerprint=fp, redis_client=shared,
        epoch=1000.0, dedupe_max_entries=cap,
    ) is False
    assert shared.zcard(key) == min(20, cap)
    assert shared.zscore(key, f"{1009.0:.6f}") == 1009.0  # 最新一条一定保留


def test_endpoint_passes_runtime_config_to_should_forward(client, app):
    """后台配置的 dedupe_max_entries 必须透传到 should_forward（否则后台改了不生效）。"""
    from app.services import runtime_config, sentry
    from tests.helpers import db_session

    app.state.settings.sentry_dsn = "https://key@sentry.test/1"
    # 写入后台配置
    with db_session(app) as session:
        runtime_config.set_telemetry_config(
            session, app.state.settings, 1, sample_rate=0.5,
            dedupe_window_seconds=30, dedupe_max_entries=7,
        )

    with patch.object(sentry, "should_forward", return_value=False) as mocked:
        resp = _post_report(client)
    assert resp.status_code == 202
    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["sample_rate"] == 0.5
    assert kwargs["dedupe_window_seconds"] == 30
    assert kwargs["dedupe_max_entries"] == 7
