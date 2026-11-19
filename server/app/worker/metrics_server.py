# -*- coding: utf-8 -*-
"""Worker 指标端点（只读 HTTP）。

worker 不在 FastAPI 进程内，单独暴露 /metrics；多副本时每个副本渲染的内容
来自 Redis 汇总，因此 Prometheus 抓任意副本都能拿到全局口径。
"""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .. import metrics

logger = logging.getLogger("moxie.worker.metrics")

ExtraSamples = Callable[[], dict[str, float]] | dict[str, float] | None


def _handler(extra_samples: ExtraSamples):
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
            if self.path.split("?", 1)[0] not in ("/metrics", "/"):
                self.send_error(404, "not found")
                return
            samples = extra_samples() if callable(extra_samples) else extra_samples
            body = metrics.render(extra_samples=samples).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            logger.debug("worker metrics: " + fmt, *args)

    return MetricsHandler


def start_metrics_server(
    port: int,
    *,
    host: str = "0.0.0.0",
    extra_samples: ExtraSamples = None,
) -> ThreadingHTTPServer | None:
    """启动后台指标服务；端口被占用时只告警，不阻断 worker 消费。"""
    try:
        server = ThreadingHTTPServer((host, port), _handler(extra_samples))
    except OSError as exc:
        logger.warning("worker metrics 端口 %s 启动失败：%s", port, exc)
        return None
    threading.Thread(target=server.serve_forever, name="moxie-metrics-http", daemon=True).start()
    logger.info("worker metrics 已启动：http://%s:%s/metrics", host, port)
    return server
