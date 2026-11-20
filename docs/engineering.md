# 工程化说明（CI / E2E / 压测 / 备份 / 监控）

本文档说明新增的工程化能力与本地运行方式。无法在本机执行的条件单独标注。

> 范围约定（2026-11-18）：后续工程化建设仅覆盖 `/server`、`/client`、`/admin` 三个在线项目。离线桌面端及其构建、E2E、打包链路按存量保留，不再新增能力或扩展门禁；i18n 与站点地图继续跳过。

最近更新：2026-11-19（在线主链 E2E、P95/P99 与错误预算告警、环境配置治理、四账对账、注销申请可视化、租户限流与死信重放、体检报告产品化、法务与 SLA 交付包、用户自助退款申请入口、BYOK 自选模型/网关、账户设置六 tab（订阅额度/BYOK/安全/退款/导出/注销）与顶栏用户下拉、三模式 Agent 流程完成后自动出封面并在作品列表展示缩略图、管理端 UI 统一重做（可收起侧边栏、顶栏用户下拉、路由级高度自适应、公共选择器/分段控件统一封装）、管理端登录/忘记密码/重置密码三页统一重做（公共 AuthShell 左右分栏撑满视口、密码显隐、窄屏自适应）、管理端全站 UI 规格统一（品牌图标复用 client、全局强制统一层规范按钮/表单/表格尺寸、修复卡片高度适配、RowActions 合并多操作为下拉、统一分页、侧栏收起态适配）、修复概览页接口就绪表格被压成横幅（信息展示页改回自然高度 + 整页滚动）、模型消费统计页按统一设计系统重做（统一筛选控件、stat-card、data-table、表格撑满高度）、列表工具栏去掉 1px 横线）。此前于 2026-11-18 完成 CI 最小权限/超时/覆盖率门禁/产物归档/失败通知、release SBOM/签名/来源证明、用户数据权利闭环、BYOK 会话入口、弱网退避、端到端 trace 与告警 SLO。

## 1. CI/CD（GitHub Actions）

### `.github/workflows/ci.yml`

当前在线版（server + client + admin）+ 离线 E2E 的合并门禁：

| Job | 内容 | 失败定位 |
| --- | --- | --- |
| `server-tests` | Python 3.12，SQLite + fakeredis，`pytest -m "not live"`，JUnit XML + coverage XML，覆盖率低于 70% 失败（本地实测 79.44%） | 失败输出 + `server-pytest-report` / `server-coverage` |
| `migration-check` | 临时 SQLite `alembic upgrade head` + `alembic check`（迁移与模型零漂移） | 步骤日志 |
| `postgres-integration` | Postgres 16 service：`alembic upgrade head` + `alembic check` 在真实 PG 上执行，并跑 `pytest -m postgres`（SKIP LOCKED 租约回收、额度并发预占） | 步骤日志 |
| `web-apps` | Node 22，matrix=`client,admin`：`npm ci` → typecheck → lint → test → build，归档 `dist` | 按 app 区分步骤 + `<app>-dist` 制品 |
| `online-e2e` | Playwright 在线主链：注册→订阅→创作运行→顶栏用户下拉菜单→账户设置六 tab（订阅额度/BYOK/数据导出/退款申请/注销申请）→admin 立即清除；client/server/admin 三端联跑 | `online-e2e-report` 制品 |
| `dependency-audit` | `pip-audit -r server/requirements.txt --strict` + 三端 `npm audit --omit=dev --audit-level=high` | 步骤日志 |
| `e2e-desktop` | 存量 job：依赖 web-apps，构建 web/dist + Playwright Chromium 跑离线冒烟；后续不再新增用例或能力 | trace / 截图 / HTML 报告 |
| `ci-failure-notice` | 任一必需 job 失败时写 Job Summary；配置 `CI_FAILURE_WEBHOOK` 后推送值班机器人 | GitHub Actions run 摘要 / 群消息 |

所有 job 均设 `timeout-minutes`，workflow 顶层仅 `contents: read`；release 发布 job 才提升为 `contents: write` + `id-token: write`。缓存：pip 走 `server/requirements.txt`，npm 走各端 `package-lock.json`。

### Release（`.github/workflows/release.yml`）

Tag 形如 `v*` 触发：重新构建 client/admin 与 server 源码包 → 生成 SPDX SBOM → cosign keyless 签名 → 构建来源证明（provenance attestation）→ 发布 GitHub Release。预发布 tag（含 `-`）自动标记为 prerelease，发布说明取 `CHANGELOG.md` 并附带自动生成的 commit notes。

在线 E2E 使用冷门端口 `18000` 作为后端（`MOXIE_E2E_SERVER_PORT` 可覆盖），避免开发机上 Docker/WSL 占用的 8000 冲突；client/admin 的 Vite 代理在 E2E 启动时同步指向该端口。

本地等价的通过项（2026-11-19 第十七批回归实测）：

```
server pytest（全量）: 449 collected / 3 skipped，全绿，coverage 达标
alembic upgrade head + check: No new upgrade operations detected
client: typecheck OK · lint 0 error / 1 warning · test 56 passed · build OK
online-e2e: 1 passed（注册→订阅→运行→顶栏下拉菜单→账户设置六 tab 订阅额度/BYOK/导出/退款/注销→admin purge）
admin:  typecheck OK · lint 0 error · test 17 passed · build OK
scripts/check_skills.py: 硬校验 12 项通过，漂移 0
workflow / monitoring YAML: PyYAML 解析通过
```

封面闭环补测（2026-11-19）：

```
server pytest（全量）: 468 collected / 3 skipped / 0 failed
client: typecheck OK · lint 0 error / 1 warning · test 59 passed · build OK
online-e2e: 1 passed（E2E 显式关闭自动出图，避免外部图片服务影响主链）
```

说明：CI 本身未在 GitHub runner 上执行（本机无 runner）；workflow YAML 已用 PyYAML 解析校验。
client lint 仅剩 `BodyTab.vue` 一处已知 `v-html` 白名单提示，不阻断合并。后端全量有 2 条 SQLite `ResourceWarning`（测试进程 GC 阶段），不失败、不阻断发布；后续可补连接归属追踪。

### 依赖版本管理

- `server/requirements.txt`：每个依赖钉主版本上界（如 `>=2.0,<3`），避免破坏性升级。
- `server/requirements.lock.txt`：精确版本锁文件，Dockerfile 优先用它构建（`test -f` 时选用），
  缺失时回退到 requirements.txt。锁文件已于 2026-11-18 用 CPython 3.12.16 重新冻结，
  与生产镜像 `python:3.12-slim` 对齐；`pip check` 无冲突，并用 3.12 环境跑通定向测试。

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

- `prometheus.yml`：抓取 `api:8000/metrics`（compose）与 `host.docker.internal:8798`（本地），并通过 `rule_files` 引入 `alerts.yml`。
- `grafana-dashboard.json`：队列深度、任务速率、模型调用/成本、回调失败、额度拒绝、限流、上传、Token 用量等面板。
- `alerts.yml`：API 不可达、队列积压、租约回收、任务失败率、回调失败、模型成本突增、额度拒绝与认证限流告警。
- `SLO.md`：试点期 SLI/目标、错误预算、端到端 trace-id 串联与告警响应级别。
- 浏览器请求带 `X-Trace-Id` / W3C `Traceparent`，服务端回写并写入结构化日志；前端错误上报带 `trace_id`，以 `source_trace_id` 落日志，便于跨端串联。
- 指标名已与 `server/app/metrics.py` 和实际 `/metrics` 输出核对（详见 `ops/monitoring/README.md`）。
- 多进程聚合：api（多 uvicorn worker）、worker（多副本容器）与 scheduler 的计数按 10s 增量写入 Redis
  （`moxie:metrics:counters` / `moxie:metrics:histograms`），`/metrics` 渲染「Redis 汇总 + 本进程未刷新增量」，
  避免反代/负载均衡下抓取命中不同实例导致曲线回退。worker 入口改为 `python -m app.worker.rq_worker`，
  容器内额外提供 `:9101/metrics` 供排障直连；Prometheus 默认只抓 api（worker 指标已并入全局口径，
  避免多副本同服务名被重复累加）。

## 6. 安全与依赖报告

```bash
# 报告为本地生成物，不入库
python -m pip_audit -r server/requirements.txt --format json --output ops/reports/pip-audit-report.json
cd web && npm audit --omit=dev --json > ../ops/reports/npm-audit-report.json
```

实测：

- `pip-audit`：42 个依赖，**无已知漏洞**。
- `npm audit --omit=dev`：prod 95 个依赖，**0 漏洞**（info/low/moderate/high/critical 均为 0）。

- BYOK：在线端配置仅存 `sessionStorage`（兼容旧键 `mx_byok_key`，新结构 `{key, model, baseUrl}`），关闭标签页即失效；不写 `localStorage`、不进 Vue store、不随任务参数落库。仅 `withByok` 的模型消费请求注入 `X-BYOK-Key` / `X-BYOK-Model` / `X-BYOK-Base-URL`；服务端 Redis 临时缓存 JSON（TTL 1h），base_url 走 SSRF 校验，`resolve_step_model` 集中覆盖 model/base_url。
- 弱网：client HTTP 层对网络错误与 502/503/504 自动重试，默认最多 2 次；指数退避（300ms 起、5s 上限）+ 25% 抖动，尊重 `Retry-After`，仅 GET/HEAD/OPTIONS 或带 `Idempotency-Key` 的请求重试。

清单与待办见 [`docs/security-checklist.md`](security-checklist.md)。

## 7. 用户数据权利

- `GET /v1/me/export`：导出账号、设备、订阅、用量、订单、任务、Agent 运行、法律同意与审计留痕等结构化数据；对象存储内容按上限内联，超限项给临时下载链接。密码哈希、令牌哈希、Web Push 密钥不出库。
- `POST /v1/me/delete`：需密码 + 显式确认串 `DELETE_MY_ACCOUNT`；写注销申请、账号置 `closing`、撤销全部刷新会话，宽限期（默认 7 天）后由 scheduler 清除。
- 管理端：`GET /v1/admin/account-deletions` 查看申请，`POST .../{id}/cancel` 撤销并恢复登录，`POST .../{id}/purge` 立即清除。
- 清除逻辑集中在 `app/services/data_rights.py`，管理端硬删除与注销到期清除共用；会删除上传源文件、任务产物、Agent 产物、封面，并按外键拓扑清理全部业务子表。

## 8. 目录速览

```
.github/workflows/ci.yml        CI（pytest / unittest / web build / e2e）
.github/workflows/package.yml   手动打包（前端产物 + 可选 exe + 版本号）
tests/requirements-ci.txt       桌面端 unittest 的 CI 依赖
e2e/                            Playwright 配置、临时服务启动器、6 条用例
ops/loadtest/                   Locust / k6 / 本地一键压测 / 实测结果
ops/backup/                     Postgres / MinIO / SQLite 演练与恢复文档
ops/monitoring/                 Prometheus 抓取 + 告警规则 + SLO + Grafana 看板
ops/reports/                    压测报告（本地生成，原始 CSV 不入库）
docs/security-checklist.md      安全核对项与待办
docs/环境配置治理.md            dev/staging/prod 配置基线、密钥清单与回滚约定
docs/法务与SLA交付包-2026-11.md 用户协议 / 隐私 / AIGC / 授权链 / 退款发票 / 子处理者 / DPA / 试点 SLA
docs/engineering.md             本文档
```

## 9. 仍需条件

| 项 | 原因 | 下一步 |
| --- | --- | --- |
| GitHub Actions 实跑 | 本机无 runner | 推送到仓库后观察 CI；失败看 JUnit / Playwright artifacts |
| exe 构建 workflow | Nuitka 体积大，未在本地跑手动 workflow | 在 GitHub `windows-latest` 上触发 `build_exe=true` 验证 |
| Postgres / MinIO 恢复演练 | 本机无 `pg_dump` / `mc` / Docker | 在具备工具的环境按 `restore-drill.md` 执行 |
| k6 压测 | 本机未安装 k6 | 安装后运行 `ops/loadtest/k6.js`，或继续用 Locust |
| 真实支付 live 测试 | 缺少商户沙箱凭据 | 配置凭据后 `pytest -m live` |
| Chromium 下载 | `cdn.playwright.dev` 本机不可达 | CI 正常；本机用系统 Edge（`E2E_CHANNEL=msedge`） |
