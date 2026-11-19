# -*- coding: utf-8 -*-
"""轻量 Prometheus 指标（无第三方依赖）。

计数器默认进程内累加；`/metrics` 抓取时再补充数据库派生指标（队列深度）。
多 worker 部署时每个进程各自暴露，Prometheus 侧按实例聚合即可。
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from collections import defaultdict

logger = logging.getLogger("moxie.metrics")

_LOCK = threading.Lock()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
HISTOGRAM_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
_HISTOGRAMS: dict[
    tuple[str, tuple[tuple[str, str], ...]],
    tuple[list[int], float, int],
] = {}

HELP = {
    "moxie_http_request_duration_seconds": "HTTP 请求耗时（method/path/status）",
    "moxie_tasks_total": "任务最终状态计数（succeeded/failed/canceled）",
    "moxie_tasks_requeued_total": "租约超时后重新入队的任务数",
    "moxie_task_retries_total": "任务执行失败后回到队列重试的次数",
    "moxie_model_calls_total": "模型调用次数（route=managed/byok/stub）",
    "moxie_model_cost_cents_total": "模型调用累计成本（分）",
    "moxie_model_tokens_total": "模型调用累计 token（含估算）",
    "moxie_webhook_failures_total": "支付回调失败次数（provider/code）",
    "moxie_webhook_duplicates_total": "支付回调重复投递（幂等命中）次数",
    "moxie_quota_rejections_total": "额度拒绝次数（metric）",
    "moxie_usage_alerts_total": "异常用量告警次数",
    "moxie_rate_limited_total": "被限流的请求次数（scope）",
    "moxie_client_error_reports_total": "前端错误上报计数（result/source）",
    "moxie_agent_runs_started_total": "Agent 运行启动次数（mode）",
    "moxie_agent_runs_total": "Agent 运行最终状态计数（status/mode）",
    "moxie_agent_run_duration_seconds_total": "Agent 运行累计耗时（秒，mode）",
    "moxie_agent_run_tokens_total": "Agent 运行累计 token",
    "moxie_skill_calls_total": "Skill 节点调用次数（skill/status）",
    "moxie_skill_duration_seconds_total": "Skill 节点累计耗时（秒，skill）",
    "moxie_agent_chapters_total": "Agent 逐章写作完成章数（mode）",
    "moxie_agent_chapter_chars_total": "Agent 逐章写作累计字数（mode）",
}


def increment(name: str, value: float = 1.0, **labels: str) -> None:
    key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
    with _LOCK:
        _COUNTERS[key] += value


def observe(name: str, value: float, **labels: str) -> None:
    """记录直方图观测值；桶边界固定，避免动态标签造成时间序列爆炸。"""
    key = (name, tuple(sorted((k, str(v)) for k, v in labels.items())))
    with _LOCK:
        buckets, total, count = _HISTOGRAMS.setdefault(
            key, ([0] * len(HISTOGRAM_BUCKETS), 0.0, 0)
        )
        for index, bound in enumerate(HISTOGRAM_BUCKETS):
            if value <= bound:
                buckets[index] += 1
        _HISTOGRAMS[key] = (buckets, total + value, count + 1)


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}"


def _escape_label(value: str) -> str:
    """Prometheus 文本格式：标签值中的反斜杠、引号、换行必须转义。"""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace('"', '\\"')
    )


def _label_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels)
    return "{" + body + "}"


def render(extra_samples: dict[str, float] | None = None) -> str:
    """输出 Prometheus 文本格式；extra_samples 用于数据库派生指标。"""
    counters, histograms = _aggregated()
    lines: list[str] = []
    names: dict[str, list[tuple[tuple[tuple[str, str], ...], float]]] = defaultdict(list)
    for (name, labels), value in counters.items():
        names[name].append((labels, value))
    for name in sorted(names):
        lines.append(f"# HELP {name} {HELP.get(name, name)}")
        lines.append(f"# TYPE {name} counter")
        for labels, value in sorted(names[name]):
            lines.append(f"{name}{_label_text(labels)} {_fmt(value)}")
    for name in sorted({key[0] for key in histograms}):
        lines.append(f"# HELP {name} {HELP.get(name, name)}")
        lines.append(f"# TYPE {name} histogram")
        for (h_name, labels), (buckets, total, count) in sorted(
            ((key, value) for key, value in histograms.items() if key[0] == name),
            key=lambda item: item[0],
        ):
            for bound, bucket_count in zip(HISTOGRAM_BUCKETS, buckets):
                le_labels = tuple(sorted((*labels, ("le", str(bound)))))
                lines.append(f"{h_name}_bucket{_label_text(le_labels)} {bucket_count}")
            inf_labels = tuple(sorted((*labels, ("le", "+Inf"))))
            lines.append(f"{h_name}_bucket{_label_text(inf_labels)} {count}")
            lines.append(f"{h_name}_sum{_label_text(labels)} {_fmt(total)}")
            lines.append(f"{h_name}_count{_label_text(labels)} {count}")
    for name, value in sorted((extra_samples or {}).items()):
        lines.append(f"# HELP {name} 数据库派生指标")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {_fmt(value)}")
    if not lines:
        lines.append("# no metrics yet")
    return "\n".join(lines) + "\n"


def histogram_snapshot(name: str) -> list[tuple[dict[str, str], list[int], float, int]]:
    """返回直方图快照，供管理端做 P95/P99 汇总；调用方不得修改返回值。"""
    _, histograms = _aggregated()
    return [
        (dict(labels), list(buckets), total, count)
        for (metric_name, labels), (buckets, total, count) in histograms.items()
        if metric_name == name
    ]


def reset() -> None:
    """仅供测试：清空进程内计数与增量基线。"""
    with _LOCK:
        _COUNTERS.clear()
        _HISTOGRAMS.clear()
    with _AGG_LOCK:
        _agg_last_counters.clear()
        _agg_last_hist.clear()


# ---------------------------------------------------------------------------
# 跨进程聚合（Redis）
#
# 默认仍是纯进程内计数：单进程 / 测试 / 无 Redis 时行为完全不变。
# 多 uvicorn worker、多个 worker 容器时，每个进程只把「自上次刷新后的增量」
# 写入 Redis，/metrics 渲染时用「Redis 汇总 + 本进程未刷新增量」得出全量，
# 避免反代/负载均衡下每次抓取命中不同实例导致曲线抖动。
# ---------------------------------------------------------------------------

_AGG_COUNTERS_KEY = "moxie:metrics:counters"
_AGG_HIST_KEY = "moxie:metrics:histograms"
_AGG_SEP = "\x1f"

_AGG_LOCK = threading.Lock()
_agg_client = None
_agg_interval = 10.0
_agg_thread: threading.Thread | None = None
_agg_stop = threading.Event()
_agg_last_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_agg_last_hist: dict[
    tuple[str, tuple[tuple[str, str], ...]], tuple[list[int], float, int]
] = {}


def _encode(name: str, labels: tuple[tuple[str, str], ...]) -> str:
    return json.dumps([name, dict(labels)], ensure_ascii=False, sort_keys=True)


def _decode(field: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    name, labels = json.loads(field)
    return str(name), tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))


def configure(redis_url: str | None = None, *, client=None, interval: float = 10.0) -> None:
    """启用跨进程聚合。

    - ``redis_url``：生产传入真实 Redis；为 None 且未注入 client 时保持纯进程内。
    - ``client``：测试注入 fakeredis 等实现。
    - ``interval`` <= 0 时不启动后台线程，只允许手动 flush_now()（测试用）。
    """
    global _agg_client, _agg_interval, _agg_thread
    disable()
    if client is None:
        if not redis_url:
            return
        try:
            import redis

            client = redis.Redis.from_url(redis_url, decode_responses=True)
        except Exception as exc:  # noqa: BLE001 - 指标不可用不能阻断启动
            logger.warning("metrics 聚合初始化失败，回退进程内计数：%s", type(exc).__name__)
            return
    _agg_client = client
    _agg_interval = max(0.5, float(interval))
    if interval > 0:
        _agg_thread = threading.Thread(target=_flush_loop, name="moxie-metrics-flush", daemon=True)
        _agg_thread.start()
        atexit.register(disable)


def disable() -> None:
    global _agg_client, _agg_thread
    _agg_stop.set()
    thread = _agg_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=1)
    _agg_thread = None
    _agg_client = None
    _agg_stop.clear()
    with _AGG_LOCK:
        _agg_last_counters.clear()
        _agg_last_hist.clear()


def _flush_loop() -> None:
    while not _agg_stop.wait(_agg_interval):
        flush_now()


def _local_snapshot():
    with _LOCK:
        counters = dict(_COUNTERS)
        histograms = {
            key: (list(buckets), total, count)
            for key, (buckets, total, count) in _HISTOGRAMS.items()
        }
    return counters, histograms


def flush_now() -> bool:
    """把本进程自上次刷新后的增量写入 Redis；无聚合或没有增量时返回 False。"""
    global _agg_last_counters, _agg_last_hist
    client = _agg_client
    if client is None:
        return False
    counters, histograms = _local_snapshot()
    with _AGG_LOCK:
        counter_delta = {}
        for key, value in counters.items():
            delta = value - _agg_last_counters.get(key, 0.0)
            if delta:
                counter_delta[key] = delta
        hist_delta = {}
        for key, (buckets, total, count) in histograms.items():
            prev = _agg_last_hist.get(key)
            if prev is None:
                prev = ([0] * len(buckets), 0.0, 0)
            bucket_delta = [now - old for now, old in zip(buckets, prev[0])]
            if any(bucket_delta) or total - prev[1] or count - prev[2]:
                hist_delta[key] = (bucket_delta, total - prev[1], count - prev[2])
        if not counter_delta and not hist_delta:
            return False
        pipe = client.pipeline()
        for (name, labels), delta in counter_delta.items():
            pipe.hincrbyfloat(_AGG_COUNTERS_KEY, _encode(name, labels), delta)
        for (name, labels), (bucket_delta, total_delta, count_delta) in hist_delta.items():
            base = _encode(name, labels) + _AGG_SEP
            for index, delta in enumerate(bucket_delta):
                if delta:
                    pipe.hincrby(_AGG_HIST_KEY, f"{base}b{index}", delta)
            if count_delta:
                pipe.hincrby(_AGG_HIST_KEY, f"{base}count", count_delta)
            if total_delta:
                pipe.hincrbyfloat(_AGG_HIST_KEY, f"{base}sum", total_delta)
        try:
            pipe.execute()
        except Exception as exc:  # noqa: BLE001 - Redis 抖动时保留本地增量，下轮重试
            logger.debug("metrics 增量写入失败：%s", type(exc).__name__)
            return False
        _agg_last_counters = counters
        _agg_last_hist = histograms
        return True


def _aggregated():
    """返回（计数, 直方图）：Redis 汇总 + 本进程尚未刷新的增量。"""
    counters, histograms = _local_snapshot()
    client = _agg_client
    if client is None:
        return counters, histograms
    try:
        raw_counters = client.hgetall(_AGG_COUNTERS_KEY)
        raw_hist = client.hgetall(_AGG_HIST_KEY)
    except Exception:  # noqa: BLE001 - Redis 不可用则退回本进程
        return counters, histograms
    merged: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for field, value in raw_counters.items():
        try:
            merged[_decode(field)] = float(value)
        except Exception:
            continue
    merged_hist: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[list[int], float, int]] = {}
    series: dict[str, dict[str, str]] = {}
    for field, value in raw_hist.items():
        base, sep, suffix = field.partition(_AGG_SEP)
        if not sep:
            continue
        series.setdefault(base, {})[suffix] = value
    for base, fields in series.items():
        try:
            name, labels = _decode(base)
        except Exception:
            continue
        buckets = [
            int(float(fields.get(f"b{index}", 0))) for index in range(len(HISTOGRAM_BUCKETS))
        ]
        merged_hist[(name, labels)] = (
            buckets,
            float(fields.get("sum", 0.0)),
            int(float(fields.get("count", 0))),
        )
    with _AGG_LOCK:
        for key, value in counters.items():
            pending = value - _agg_last_counters.get(key, 0.0)
            if pending:
                merged[key] = merged.get(key, 0.0) + pending
        for key, (buckets, total, count) in histograms.items():
            prev = _agg_last_hist.get(key)
            if prev is None:
                prev = ([0] * len(buckets), 0.0, 0)
            current = merged_hist.get(key, ([0] * len(buckets), 0.0, 0))
            merged_hist[key] = (
                [
                    value + (now - old)
                    for value, now, old in zip(current[0], buckets, prev[0])
                ],
                current[1] + (total - prev[1]),
                current[2] + (count - prev[2]),
            )
    return merged, merged_hist
