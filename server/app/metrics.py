# -*- coding: utf-8 -*-
"""轻量 Prometheus 指标（无第三方依赖）。

计数器默认进程内累加；`/metrics` 抓取时再补充数据库派生指标（队列深度）。
多 worker 部署时每个进程各自暴露，Prometheus 侧按实例聚合即可。
"""

from __future__ import annotations

import threading
from collections import defaultdict

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
    lines: list[str] = []
    names: dict[str, list[tuple[tuple[tuple[str, str], ...], float]]] = defaultdict(list)
    with _LOCK:
        snapshot = list(_COUNTERS.items())
    for (name, labels), value in snapshot:
        names[name].append((labels, value))
    for name in sorted(names):
        lines.append(f"# HELP {name} {HELP.get(name, name)}")
        lines.append(f"# TYPE {name} counter")
        for labels, value in sorted(names[name]):
            lines.append(f"{name}{_label_text(labels)} {_fmt(value)}")
    for name in sorted({key[0] for key in _HISTOGRAMS}):
        lines.append(f"# HELP {name} {HELP.get(name, name)}")
        lines.append(f"# TYPE {name} histogram")
        for (h_name, labels), (buckets, total, count) in sorted(
            ((key, value) for key, value in _HISTOGRAMS.items() if key[0] == name),
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
    with _LOCK:
        return [
            (dict(labels), list(buckets), total, count)
            for (metric_name, labels), (buckets, total, count) in _HISTOGRAMS.items()
            if metric_name == name
        ]


def reset() -> None:
    """仅供测试：清空进程内计数。"""
    with _LOCK:
        _COUNTERS.clear()
        _HISTOGRAMS.clear()
