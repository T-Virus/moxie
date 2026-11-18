# -*- coding: utf-8 -*-
"""Prometheus 指标输出回归：计数器、直方图与标签转义。"""

from __future__ import annotations

from app import metrics


def test_histogram_render_and_reset() -> None:
    metrics.reset()
    metrics.observe(
        "moxie_http_request_duration_seconds",
        0.12,
        method="GET",
        path="/v1/plans",
        status="200",
    )
    text = metrics.render()

    assert "# TYPE moxie_http_request_duration_seconds histogram" in text
    assert (
        'moxie_http_request_duration_seconds_bucket{le="0.1",method="GET",path="/v1/plans",'
        'status="200"} 0'
    ) in text
    assert (
        'moxie_http_request_duration_seconds_bucket{le="0.25",method="GET",path="/v1/plans",'
        'status="200"} 1'
    ) in text
    assert (
        'moxie_http_request_duration_seconds_sum{method="GET",path="/v1/plans",status="200"} 0.12'
    ) in text
    assert (
        'moxie_http_request_duration_seconds_count{method="GET",path="/v1/plans",status="200"} 1'
    ) in text

    metrics.reset()
    assert "moxie_http_request_duration_seconds_bucket" not in metrics.render()


def test_http_middleware_records_latency(client) -> None:
    metrics.reset()
    assert client.get("/healthz").status_code == 200
    text = client.get("/metrics").text
    assert "moxie_http_request_duration_seconds_bucket" in text
    assert "moxie_http_request_duration_seconds_count" in text
