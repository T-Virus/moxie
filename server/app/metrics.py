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

HELP = {
    "moxie_tasks_total": "任务最终状态计数（succeeded/failed/canceled）",
    "moxie_tasks_requeued_total": "租约超时后重新入队的任务数",
    "moxie_model_calls_total": "模型调用次数（route=managed/byok/stub）",
    "moxie_model_cost_cents_total": "模型调用累计成本（分）",
    "moxie_model_tokens_total": "模型调用累计 token（含估算）",
    "moxie_webhook_failures_total": "支付回调失败次数（provider/code）",
    "moxie_webhook_duplicates_total": "支付回调重复投递（幂等命中）次数",
    "moxie_quota_rejections_total": "额度拒绝次数（metric）",
    "moxie_usage_alerts_total": "异常用量告警次数",
    "moxie_rate_limited_total": "被限流的请求次数（scope）",
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


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}"


def _label_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{v}"' for k, v in labels)
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
    for name, value in sorted((extra_samples or {}).items()):
        lines.append(f"# HELP {name} 数据库派生指标")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {_fmt(value)}")
    if not lines:
        lines.append("# no metrics yet")
    return "\n".join(lines) + "\n"


def reset() -> None:
    """仅供测试：清空进程内计数。"""
    with _LOCK:
        _COUNTERS.clear()
