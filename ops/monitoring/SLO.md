# 墨写在线版 SLO（试点期基线）

适用范围：`server` API + worker + scheduler。指标来自 `/metrics`，告警规则见 `alerts.yml`。
灰度/回滚判定以自然周为窗口，每周五复盘；连续两周超错误预算则暂停新功能发布，优先稳定性。

## SLI 与目标

| SLI | 计算口径 | 目标 | 对应告警 |
| --- | --- | --- | --- |
| API 可用性 | `1 - (5xx 响应数 / 总响应数)`，由 `moxie_http_request_duration_seconds_count{status}` 统计 | ≥ 99.5% / 周 | `MoxieApiDown` / `MoxieErrorBudgetBurnRateHigh` |
| API 延迟 P95 | `histogram_quantile(0.95, rate(moxie_http_request_duration_seconds_bucket[5m]))` | ≤ 500ms / 5 分钟 | `MoxieApiLatencyHigh` |
| 任务成功率 | `1 - sum(rate(moxie_tasks_total{status="failed"})) / sum(rate(moxie_tasks_total))` | ≥ 95% / 周 | `MoxieTaskFailureRateHigh` |
| 队列健康 | `moxie_queue_depth` 与 `moxie_agent_queue_depth` 同时低于 100 | 持续满足 | `MoxieQueueBacklog`、`MoxieStuckTasksRequeued` |
| 支付回调可靠性 | `1 - webhook_failures / webhook_total`（渠道侧 + 本地审计） | ≥ 99.9% / 周 | `MoxieWebhookFailures` |
| 成本可控 | 模型成本 `increase(moxie_model_cost_cents_total[1h])` < 10000 分 | 常态满足 | `MoxieModelCostSpike` |
| 滥用防护 | 认证接口限流命中 `rate(moxie_rate_limited_total{scope="auth_global"})` < 5/s | 常态满足 | `MoxieAuthRateLimitSpike` |

错误预算：可用性 99.5%/周 ≈ 5 分钟不可用；任务成功率 95%/周 ≈ 5% 失败额度。预算耗尽后的发布需附带整改说明。

## 端到端追踪

- 客户端 `services/trace.ts` 在同一浏览器会话生成 32 位 trace-id，每次请求生成新 span-id，写入 `X-Trace-Id` 与 W3C `Traceparent`。
- 服务端 `request_context` 解析 `Traceparent`（兼容 `X-Trace-Id`），回写两个响应头；`JsonFormatter` 自动把 trace-id 写进每条结构化日志。
- 浏览器异常经 `/v1/telemetry/client-error` 上报时带 `trace_id` 与 `request_id`，服务端以 `source_trace_id` / `source_request_id` 落日志，可与同次业务请求对齐。
- 排查顺序：浏览器 Network 取 `X-Trace-Id` → 日志检索 `trace_id` → 结合 `request_id` 定位单请求 → 任务类问题再用 task/run id 关联 worker 日志。

## 告警分级与响应

| 级别 | 触发 | 响应 |
| --- | --- | --- |
| critical | `MoxieApiDown` | 立即值班响应；5 分钟内确认，30 分钟内给出止血或回滚动作 |
| warning | 队列、任务失败率、回调、成本、限流 | 当工作日处理；1 小时内确认，必要时降级/扩容 |
| info | 额度拒绝突增 | 纳入周复盘；结合套餐与加购数据判断是否产品信号 |

## 已知缺口

- P99 面板尚未单独拆出；当前按 P95 设门禁，P99 由 Grafana 直接从同一 histogram 查询，暂不单独告警。
- 告警投递通道当前通过 CI 失败 webhook 与运维值班群手工接入；生产建议接入 Alertmanager 并配置抑制/静默规则。
