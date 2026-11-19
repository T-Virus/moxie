# -*- coding: utf-8 -*-
"""指标跨进程聚合与 worker /metrics 端点。"""

from __future__ import annotations

import urllib.request

import fakeredis

from app import metrics
from app.worker.metrics_server import start_metrics_server

COUNTERS_KEY = "moxie:metrics:counters"


def test_local_render_without_aggregation():
    metrics.reset()
    metrics.increment("moxie_tasks_total", status="succeeded")
    metrics.observe("moxie_http_request_duration_seconds", 0.02, method="GET", path="/x", status="200")
    text = metrics.render()
    assert 'moxie_tasks_total{status="succeeded"} 1' in text
    assert 'moxie_http_request_duration_seconds_count{method="GET",path="/x",status="200"} 1' in text
    metrics.reset()


def test_redis_aggregation_sums_peers_and_pending_delta():
    """Redis 汇总 + 本进程未刷新增量 = 全量；不会漏计或重复计。"""
    metrics.reset()
    client = fakeredis.FakeRedis(decode_responses=True)
    metrics.configure(client=client, interval=0)
    try:
        metrics.increment("moxie_tasks_total", status="succeeded")
        metrics.observe("moxie_http_request_duration_seconds", 0.02, method="GET", path="/x", status="200")
        assert metrics.flush_now() is True

        # 模拟另一个进程已汇总到 Redis 的增量
        fields = client.hkeys(COUNTERS_KEY)
        assert len(fields) == 1
        client.hincrbyfloat(COUNTERS_KEY, fields[0], 2)

        # 本进程再记一次（尚未 flush），应作为 pending 叠加
        metrics.increment("moxie_tasks_total", status="succeeded")
        metrics.observe("moxie_http_request_duration_seconds", 0.03, method="GET", path="/x", status="200")

        text = metrics.render()
        assert 'moxie_tasks_total{status="succeeded"} 4' in text
        count_line = next(
            line
            for line in text.splitlines()
            if line.startswith(
                'moxie_http_request_duration_seconds_count{method="GET",path="/x",status="200"}'
            )
        )
        assert count_line.endswith(" 2")
        snapshot = metrics.histogram_snapshot("moxie_http_request_duration_seconds")
        assert snapshot and snapshot[0][3] == 2
    finally:
        metrics.disable()
        metrics.reset()


def test_worker_metrics_endpoint_serves_text():
    metrics.reset()
    metrics.increment("moxie_tasks_total", status="failed")
    server = start_metrics_server(
        0,
        host="127.0.0.1",
        extra_samples={"moxie_worker_queue_depth": 3},
    )
    assert server is not None
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
        assert 'moxie_tasks_total{status="failed"} 1' in body
        assert "moxie_worker_queue_depth 3" in body
    finally:
        server.shutdown()
        server.server_close()
        metrics.reset()
