# 本地压测实测结果（2026-11-04）

## 环境

- 机器：Windows（DESKTOP-I5M6BLM），本机回环 `127.0.0.1:8798`
- 服务端：单进程 `uvicorn app.main:app`，SQLite 临时库，本地存储 fallback，无 Redis / 无 Docker
- 压测工具：Locust 2.47.0，headless
- 场景：10 虚拟用户，每秒启动 2 个，持续 30 秒
- 数据隔离：数据库/产物/源文件均在系统临时目录，运行结束已删除；项目 `data/` 未被写入

复现：

```bash
python ops/loadtest/run_local.py --vus 10 --rate 2 --duration 30s
```

## 结果（`ops/reports/loadtest/local_stats.csv`）

| 接口 | 请求数 | 失败 | 中位数 | 平均 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `GET /v1/auth/me`（鉴权） | 226 | 0 | 13 ms | 25 ms | 45 ms | 580 ms |
| `GET /v1/entitlements`（额度） | 215 | 0 | 31 ms | 51 ms | 120 ms | 650 ms |
| `GET /v1/tasks/{id}`（任务查询） | 195 | 0 | 16 ms | 26 ms | 50 ms | 350 ms |
| `POST /v1/tasks`（创建任务） | 126 | 0 | 50 ms | 74 ms | 160 ms | 580 ms |
| `POST /v1/tasks/{id}/cancel` | 126 | 0 | 56 ms | 70 ms | 130 ms | 270 ms |
| **合计** | **888** | **0** | 28 ms | 45 ms | 110 ms | 580 ms |

- 吞吐：约 **31.6 req/s**（10 VU、本机回环，含 SQLite 写入）
- 失败率：**0%**（`local_failures.csv` 为空）
- 账号准备：10 个账号（注册 + 模拟支付订阅 + 预置任务）全部成功

说明：p99 偶发 600ms 来自 SQLite 单写锁与 Python GC；SQLite 模式只用于本地/小规模验证，
生产使用 Postgres + Redis + 多 worker，应按部署规格重新标定。

## 结论与建议阈值（本地 SQLite、10 VU）

| 指标 | 建议阈值 | 实测 | 结论 |
| --- | --- | --- | --- |
| 失败率 | < 1% | 0% | PASS |
| `GET /v1/auth/me` p95 | < 150 ms | 45 ms | PASS |
| `GET /v1/entitlements` p95 | < 200 ms | 120 ms | PASS |
| `GET /v1/tasks/{id}` p95 | < 150 ms | 50 ms | PASS |
| `POST /v1/tasks` p95 | < 400 ms | 160 ms | PASS |
| 合计 p95 | < 250 ms | 110 ms | PASS |

扩容建议：

- 写路径（创建任务、取消、额度预占）是瓶颈；Postgres 下关注额度聚合行争用与事务隔离级别。
- 若 `entitlements` p95 随 VU 明显上升，优先加缓存/聚合表（当前每次实时汇总 usage）。
- 生产压测请用独立库与独立 bucket，并在 50/100/200 VU 阶梯下复测。
