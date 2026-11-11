# 压测（ops/loadtest）

对服务端四个核心接口做小规模基准：

| 场景 | 接口 |
| --- | --- |
| 鉴权 | `GET /v1/auth/me`（Bearer JWT 校验） |
| 额度 | `GET /v1/entitlements` |
| 任务查询 | `GET /v1/tasks/{id}` |
| 任务创建 | `POST /v1/tasks`（随后 `POST /v1/tasks/{id}/cancel` 释放排队预占） |

## 本地一键跑（无需 Docker）

```bash
python ops/loadtest/run_local.py --vus 10 --rate 2 --duration 30s
```

脚本会：

1. 在系统临时目录创建 SQLite 库、产物目录、源文件目录（**不写项目 `data/`**）；
2. 用 `server/.venv` 的 Python 启动 `uvicorn app.main:app`（默认端口 8798）；
3. 以 Locust headless 模式跑压测，CSV 输出到 `ops/reports/loadtest/`；
4. 退出时停止服务并删除临时目录。

前置：`pip install -r ops/loadtest/requirements.txt`（即 Locust；服务端依赖见 `server/requirements.txt`）。

## Locust 手动模式

```bash
MOXIE_BASE_URL=http://127.0.0.1:8798 LOADTEST_ACCOUNTS=10 \
python -m locust -f ops/loadtest/locustfile.py --headless -u 10 -r 2 -t 30s
```

## k6 版本

```bash
k6 run -e BASE_URL=http://127.0.0.1:8798 -e ACCOUNTS=10 ops/loadtest/k6.js
```

k6 未安装时可用 Locust 版本，两者场景一致。

## 建议阈值（本地 SQLite、单进程 Uvicorn、10 VU）

- 失败率 `http_req_failed < 1%`
- `GET /v1/auth/me` p95 < 150ms
- `GET /v1/entitlements` p95 < 200ms
- `GET /v1/tasks/{id}` p95 < 150ms
- `POST /v1/tasks` p95 < 400ms

生产（Postgres + Redis + 多 worker）建议在此基础上按实例水平扩展重新标定；
若 `POST /v1/tasks` p95 明显升高，优先排查数据库锁竞争与额度聚合行争用。
