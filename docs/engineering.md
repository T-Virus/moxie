# 工程化说明（CI / E2E / 压测 / 备份 / 监控）

本文档说明新增的工程化能力与本地运行方式。所有命令均在 2026-11-04 本机实际执行，
无法执行的条件单独标注。

## 1. CI/CD（GitHub Actions）

### `.github/workflows/ci.yml`

| Job | 内容 | 失败定位 |
| --- | --- | --- |
| `server-tests` | Python 3.12 + `server/requirements.txt`，SQLite，`pytest -m "not live"` | 失败输出 + `server-pytest-report`（JUnit XML） |
| `desktop-unittest` | Python 3.12，Ubuntu + Windows 矩阵，`python -m unittest discover -s tests` | 按步骤/平台定位 |
| `web-build` | Node 22，`npm ci && npm run build`，上传 `web-dist` 产物 | 构建日志 + dist artifact |
| `e2e` | 依赖 `web-build`，安装 Playwright Chromium，`npm test` | 失败上传 trace / 截图 / html 报告 |

缓存：`actions/setup-python` 的 pip 缓存（`server/requirements.txt`、`tests/requirements-ci.txt`），
`actions/setup-node` 的 npm 缓存（`web/package-lock.json`、`e2e/package-lock.json`）。

### `.github/workflows/package.yml`（手动触发）

- 输入 `version`（写入 `dist/version.json` 与产物名）与 `build_exe`（默认 false）。
- `frontend` job：构建 `web/dist` + 版本清单，上传 `web-dist-<version>`。
- `windows-exe` job（可选）：Windows runner 上用 Nuitka 执行 `python src/build_app.py --target win --force-web`，
  上传 `dist/墨写.exe` + `version.json`。不要求真实代码签名。

本地等价的通过项（已实测）：

```
server pytest:   107 passed, 3 deselected in 137.17s
desktop unittest: Ran 16 tests in 11.228s — OK
web build:       ✓ built in 48.93s（vendor 1.59 MB，各页面按需分包）
```

说明：CI 本身未在 GitHub runner 上执行（本机无 runner）；两份 workflow YAML 已用 PyYAML 解析校验。

## 2. E2E（Playwright）

目录 `e2e/`（独立 `package.json`）：

- `playwright.config.ts`：单 worker、桌面 1440×900、失败保留 trace/截图、HTML 报告到 `e2e/artifacts/report`。
- `scripts/start-server.mjs`：在系统临时目录构造一次性 `MOBIT_ROOT`（复制 `web/dist` 与 `config/*`，
  写入一本最小测试书 + 首章正文），用 `python src/webapp.py` 启动本地模式服务（端口 8797）。
  桌面端没有独立 `--local` 参数；删除 `MOBIT_CLOUD_API` 并保持未登录即等价于本地/离线模式，
  云端页面会展示「当前为本地模式」。
- `scripts/global-teardown.mjs`：删除临时目录并清理遗留空目录。
- `tests/desktop.spec.ts`：6 条用例。

覆盖：

1. `#/overview`：作品详情卡 + 目录 + 章节标题
2. `#/chapters`：章节概括页
3. `#/characters`：角色卡页（`林舟`，共 1 张）
4. `#/factions`：势力表页（`青云宗`，共 1 个）
5. `#/cloud`：未登录时展示「当前为本地模式」提示，不依赖真实云端
6. 数据隔离：`/api/books` 只返回 E2E 临时书，真实 `data/` 未被写入

每条用例断言控制台 `error` 与 `pageerror` 为空。

本地运行：

```bash
cd e2e && npm ci
cd ../web && npm ci && npm run build
cd ../e2e && npm test
```

本机实测（Playwright 1.49 + 系统 Edge）：

```
Running 6 tests using 1 worker
✓ overview / chapters / characters / factions / cloud / 数据隔离
6 passed (58.3s)
临时目录 leftovers: 0
```

> 本机 `cdn.playwright.dev` 下载 Chromium 卡在 0%，改用系统 Edge 验证：
> `E2E_CHANNEL=msedge npm test`。CI 环境用 `npx playwright install --with-deps chromium`，不需要该变量。

## 3. 压测（ops/loadtest）

- `locustfile.py`：鉴权 `/v1/auth/me`、额度 `/v1/entitlements`、任务查询、任务创建+取消。
- `k6.js`：同场景 k6 版本（未安装 k6 时用 Locust）。
- `run_local.py`：临时 SQLite + 本地存储启动服务 → Locust headless → 清理临时目录。

```bash
python ops/loadtest/run_local.py --vus 10 --rate 2 --duration 30s
```

本机实测（10 VU / 30s）：888 请求、0 失败、约 31.6 req/s；
p95：鉴权 45ms、额度 120ms、任务查询 50ms、创建 160ms、取消 130ms。
完整数据见 [`ops/loadtest/RESULTS.md`](../ops/loadtest/RESULTS.md) 与 `ops/reports/loadtest/*.csv`。
压测数据全部在系统临时目录，未写入项目 `data/`。

## 4. 备份与恢复（ops/backup）

| 文件 | 用途 |
| --- | --- |
| `pg_dump.sh` | Postgres 逻辑备份（custom + gzip + 可选 GPG + 保留策略） |
| `minio_sync.sh` | MinIO/S3 产物镜像到本地 |
| `sqlite_drill.py` | SQLite + 本地存储备份/恢复演练，自动校验 |
| `restore-drill.md` | 完整恢复步骤、验收清单、RTO/RPO 记录模板 |

本机演练：

```
python ops/backup/sqlite_drill.py
[1/6] … 行数 {'accounts': 3, 'tasks': 6, 'usage_events': 6}，产物文件 2
[6/6] PASS：SQLite + 本地存储备份/恢复演练通过
```

本机未安装 `pg_dump` / `mc` / Docker，Postgres/MinIO 实链路未执行；恢复步骤见 `restore-drill.md`。

## 5. 监控（ops/monitoring）

- `prometheus.yml`：抓取 `api:8000/metrics`（compose）与 `host.docker.internal:8798`（本地）。
- `grafana-dashboard.json`：队列深度、任务速率、模型调用/成本、回调失败、额度拒绝、限流、上传、Token 用量等面板。
- 指标名已与 `server/app/metrics.py` 和实际 `/metrics` 输出核对（详见 `ops/monitoring/README.md`）。

## 6. 安全与依赖报告

```bash
python -m pip_audit -r server/requirements.txt --format json --output ops/reports/pip-audit-report.json
cd web && npm audit --omit=dev --json > ../ops/reports/npm-audit-report.json
```

实测：

- `pip-audit`：42 个依赖，**无已知漏洞**。
- `npm audit --omit=dev`：prod 95 个依赖，**0 漏洞**（info/low/moderate/high/critical 均为 0）。

清单与待办见 [`docs/security-checklist.md`](security-checklist.md)。

## 7. 目录速览

```
.github/workflows/ci.yml        CI（pytest / unittest / web build / e2e）
.github/workflows/package.yml   手动打包（前端产物 + 可选 exe + 版本号）
tests/requirements-ci.txt       桌面端 unittest 的 CI 依赖
e2e/                            Playwright 配置、临时服务启动器、6 条用例
ops/loadtest/                   Locust / k6 / 本地一键压测 / 实测结果
ops/backup/                     Postgres / MinIO / SQLite 演练与恢复文档
ops/monitoring/                 Prometheus 抓取 + Grafana 看板
ops/reports/                    依赖审计报告、压测 CSV
docs/security-checklist.md      安全核对项与待办
docs/engineering.md             本文档
```

## 8. 仍需条件

| 项 | 原因 | 下一步 |
| --- | --- | --- |
| GitHub Actions 实跑 | 本机无 runner | 推送到仓库后观察 CI；失败看 JUnit / Playwright artifacts |
| exe 构建 workflow | Nuitka 体积大，未在本地跑手动 workflow | 在 GitHub `windows-latest` 上触发 `build_exe=true` 验证 |
| Postgres / MinIO 恢复演练 | 本机无 `pg_dump` / `mc` / Docker | 在具备工具的环境按 `restore-drill.md` 执行 |
| k6 压测 | 本机未安装 k6 | 安装后运行 `ops/loadtest/k6.js`，或继续用 Locust |
| 真实支付 live 测试 | 缺少商户沙箱凭据 | 配置凭据后 `pytest -m live` |
| Chromium 下载 | `cdn.playwright.dev` 本机不可达 | CI 正常；本机用系统 Edge（`E2E_CHANNEL=msedge`） |
