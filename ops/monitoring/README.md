# 监控看板（ops/monitoring）

对接服务端 `GET /metrics`（`server/app/metrics.py`，Prometheus 文本格式）。

## 指标核对

实际暴露的指标名（已用本地服务 `curl /metrics` + 代码检索核对）：

| 指标 | 类型 | 标签 |
| --- | --- | --- |
| `moxie_queue_depth` | gauge | — |
| `moxie_tasks_total` | counter | `status`（succeeded/failed/canceled） |
| `moxie_tasks_requeued_total` | counter | — |
| `moxie_model_calls_total` | counter | `route`（managed/byok/stub） |
| `moxie_model_tokens_total` | counter | — |
| `moxie_model_cost_cents_total` | counter | — |
| `moxie_webhook_failures_total` | counter | `provider`, `code` |
| `moxie_webhook_duplicates_total` | counter | `provider` |
| `moxie_quota_rejections_total` | counter | `metric` |
| `moxie_rate_limited_total` | counter | `scope` |
| `moxie_usage_alerts_total` | counter | — |
| `moxie_uploads_total` / `moxie_upload_bytes_total` | counter | — |
| `moxie_upload_rejected_total` | counter | `reason` |
| `moxie_uploads_deleted_total` | counter | — |

计数器为进程内累加（多 worker 各自暴露，Prometheus 按实例聚合）；看板一律用 `rate()/increase()`。

## 接入方式

```bash
# 1) Prometheus
cp ops/monitoring/prometheus.yml /etc/prometheus/prometheus.yml   # 或在 compose 中挂载
docker run -p 9090:9090 -v "$PWD/ops/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml" prom/prometheus

# 2) Grafana：导入 ops/monitoring/grafana-dashboard.json
#    Import -> Upload JSON -> 选择 Prometheus 数据源（变量 DS_PROMETHEUS）
```

本机验证 `/metrics`：

```bash
python ops/loadtest/run_local.py --duration 5s   # 启动临时服务端（8798）
curl -s http://127.0.0.1:8798/metrics | head -n 40
```

## 面板

- 队列深度、任务完成速率、模型调用速率、模型成本（近 1h）
- 任务状态分布、模型路由分布
- 支付回调失败、额度拒绝、限流命中
- 源文件上传/拒绝、Token 用量与异常告警、租约重排与回调重复
