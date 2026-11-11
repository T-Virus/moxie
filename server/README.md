# 墨写云端服务 · 骨架 + 拆解 / 改编 / 审查 + 真实支付 + 额度包/通知/管理端（第四期）

独立于桌面端（`src/`、`web/`、`admin/`）的云端服务，实现设计文档
[服务端架构与订阅计费设计](../docs/服务端架构与订阅计费设计-2026-11.md) 的「最小可收费闭环」：
账号 → 设备/License → 服务端权益 → 云端任务与额度 → 订阅/支付/对账，
以及完整任务链路（拆解 / 改编 / 审查）：提示词服务端化 → 分段执行 → 断点续跑 → 产物存储 → 计量结算。
本批新增：一次性额度包、通知通道、开票/退款自动化、管理端 13 组接口、相似度体检、备份恢复。

> 真实渠道（微信支付 v3 / 支付宝 / Stripe）已按官方规范实现；**mock/fake 仅 test/dev 且显式开启**，
> 生产环境开启或缺少 License 私钥会**启动失败**（见 [docs/legal-gates.md](docs/legal-gates.md)）。
> 支付接入、回调调试、沙箱/生产切换见 [docs/payments.md](docs/payments.md)。
> 管理端接口契约见 [docs/billing-admin.md](docs/billing-admin.md)；额度包见 [docs/credits.md](docs/credits.md)；
> 通知见 [docs/notifications.md](docs/notifications.md)；相似度见 [docs/similarity.md](docs/similarity.md)；
> 备份恢复见 [docs/backup.md](docs/backup.md)。桌面端 `src/` 行为未改动，`data/` 未被触碰。

## 目录

```
server/
├─ app/
│  ├─ main.py               # FastAPI 装配、request-id/trace_id、/metrics、可选 scheduler
│  ├─ config.py             # Pydantic Settings（读 .env）
│  ├─ db.py / models.py     # SQLAlchemy 2.x 模型（订单/退款/对账/发票/usage 等）
│  ├─ security.py           # scrypt 密码、JWT、Ed25519 License
│  ├─ deps.py / errors.py   # 鉴权依赖、统一错误响应（不泄露堆栈）
│  ├─ api/                  # auth/devices/license/tasks/artifacts/billing/credits/notifications/payments/gateway/admin
│  ├─ prompts/              # decompose / adapt / review 提示词服务（复用 src，版本化）
│  ├─ runners/              # decompose / adapt / review 执行器（断点/取消/产物/相似度）
│  ├─ payments/             # wechat / alipay / stripe / fake / mock
│  ├─ services/             # 额度/额度包、订阅、订单、支付流、退款、通知、对账、任务、存储、审计、Sentry
│  ├─ scheduler.py          # 定时与自愈（租约清扫/到期/提醒/告警/额度包/通知重试/对账）
│  ├─ metrics.py            # Prometheus 文本输出
│  ├─ worker/               # RQ 队列入口
│  └─ seed.py               # 套餐/权益/额度包种子
├─ alembic/                 # 初始迁移 + task_steps.meta + payments + credits/notifications
├─ docs/payments.md         # 支付接入与生产切换
├─ docs/uploads.md          # 源文件上传与客户端对接
├─ docs/credits.md          # 一次性额度包
├─ docs/notifications.md    # 站内信/邮件/短信
├─ docs/billing-admin.md    # 管理端 13 组接口与权限
├─ docs/similarity.md       # 相似度/改编幅度检查
├─ docs/legal-gates.md      # mock 支付/License/版权确认闸门
├─ docs/backup.md           # 备份/恢复/演练
├─ docs/invoicing.md        # 电子发票渠道、状态机、回调验签
├─ scripts/backup_restore.py
├─ tests/                   # 130 个用例（127 passed + 3 live skip；以实际运行为准）
├─ docker-compose.yml       # api / worker / scheduler / postgres / redis / minio
├─ Dockerfile
└─ .env.example
```

## 快速开始（本机，无需 Docker）

要求 Python 3.12+（本机验证用 3.14）。

```powershell
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 1) 建表（Alembic）
alembic upgrade head

# 2) 启动 API（产物全部落库 + 确定性假模型，无需真实 key）
$env:STORAGE_BACKEND="db"
$env:STORAGE_PUBLIC_BASE_URL="http://127.0.0.1:8000"
$env:REDIS_ENABLED="false"
$env:MODEL_STUB="true"
# 本地单进程：允许临时 License 私钥；生产必须配置固定私钥（见 docs/legal-gates.md）
$env:LICENSE_ALLOW_EPHEMERAL_KEY="true"
uvicorn app.main:app --reload --port 8000
```

- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：`GET /healthz`、`GET /readyz`
- 默认使用 `server/novel_server.db`（SQLite）+ fakeredis，**仅适合本地开发/测试**。

## 源文件上传（客户端接入）

客户端不需要把书稿放到服务端本机目录：先上传拿 `source_key`，再创建任务。

```bash
# 1) 上传（multipart，字段名 file）
curl -sS -X POST http://127.0.0.1:8000/v1/uploads \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./样本.txt;type=text/plain"
# → {"source_key":"uploads/1/9f0c...-样本.txt","filename":"样本.txt","size":123456,...}

# 2) 创建任务时用 source_key（source_path 仍可用，但只允许 TASK_SOURCE_DIRS 白名单）
curl -sS -X POST http://127.0.0.1:8000/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: upload-demo-1" \
  -H "Content-Type: application/json" \
  -d '{"type":"decompose","params":{"source_key":"uploads/1/9f0c...-样本.txt","book":"样本"}}'

# 3) 可选：删除自己的上传源文件（任务产物不受影响）
curl -sS -X DELETE "http://127.0.0.1:8000/v1/uploads?key=uploads/1/9f0c...-样本.txt" \
  -H "Authorization: Bearer $TOKEN"
```

限制默认 30MB、扩展名 `.txt/.md/.markdown/.csv/.json`、每账号每分钟 10 次；
上传文件按 `uploads/<account_id>/...` 隔离，跨账号引用或删除一律 404。
任务失败/取消后源文件保留；显式删除或超过 `UPLOAD_RETENTION_DAYS`（默认 30 天）由 scheduler 清理。
完整说明与客户端最小改动见 [docs/uploads.md](docs/uploads.md)。

没有 Redis 时任务不会自动执行，可手动跑一条：

```powershell
python -m app.worker.worker --once
# 或持续轮询
python -m app.worker.worker --loop
```

## 拆解链路

### 1) 创建任务

```powershell
# 先注册/登录拿 token，再订阅（mock 支付）拿额度
curl -X POST http://127.0.0.1:8000/v1/tasks -H "Authorization: Bearer <token>" -H "Idempotency-Key: demo-1" -H "Content-Type: application/json" -d '{
  "type": "decompose",
  "book": "超级傀儡兽",
  "params": {
    "source_path": "input/超级傀儡兽.txt",
    "mode": "reference",
    "limit": 3,
    "chunk_chars": 6000,
    "chunk_chapters": 1,
    "raw": true
  }
}'
```

`params` 说明：

| 字段 | 说明 |
|---|---|
| `source_path` | 允许目录（`TASK_SOURCE_DIRS`，默认 `input,data`）下的源文件；UTF-8 失败自动按 GB18030 解码 |
| `source_key` | 也可直接传对象存储里的 key（已上传的源文件） |
| `mode` | `reference`（全本原文） / `outline`（已有大纲） |
| `book` | 书名，产物按 `<book>/<task_id>/` 组织 |
| `model` | 覆盖默认模型（仍走本服务网关） |
| `limit` | 只拆前 N 章（小样本验证用） |
| `chunk_chars` / `chunk_chapters` / `min_chapters` | 分段规模 |
| `local` | `true` 时用 `src/decompose.py` 的本地拆解，不调模型（离线验证用） |
| `raw` | `true` 时额外保存每段模型原始返回 `raw/seg-XXX.txt` |

密钥只能通过请求头 `X-BYOK-Key` 传；写进 `params` 会被 `422 secret_in_params_forbidden` 拒绝。

### 2) 执行 worker

```powershell
python -m app.worker.worker --once
```

### 3) 断点续跑（核心）

每段完成后写 `task_steps`（`seg:001` / `seg:002` / … / `merge` / `outputs`），
`meta` 里含段号、输入字数、token、成本、产物 key。worker 重启后：

- 已完成段且产物存在 → 直接跳过（日志：`第 N/M 段已完成，断点续跑跳过`）；
- 步骤存在但产物丢失 → 标记 `artifact_missing` 并只重跑该段；
- 段边界检查取消标志；取消后释放额度预占，已完成段保留。

本地验证断点最直观的方式是把 `DECOMPOSE_SEGMENT_BATCH=1`：每次都只做一个新段然后让出 worker
（任务回到 `queued`，预占保留），连续跑 3 次 `--once` 就能看到 3 段逐段补齐、最后合并完成：

```powershell
$env:DECOMPOSE_SEGMENT_BATCH="1"
python -m app.worker.worker --once   # run1: queued, progress≈31
python -m app.worker.worker --once   # run2: queued, progress≈58
python -m app.worker.worker --once   # run3: succeeded, progress=100
```

### 4) 产物与下载

产物写对象存储（S3/MinIO）或本地磁盘 fallback，key 形如 `超级傀儡兽/<task_id>/…`：

```
source.txt                  # 实际用于拆解的正文（已截断到 limit）
segments/seg-001.json       # 每段结构化结果（断点依据）
raw/seg-001.txt             # 可选：模型原始返回
merged.json                 # 合并结果
decomposed.json             # 全书梗概 / 分章摘要 / 人物卡
chapters.json               # 故事设定 + 逐章任务（含 signing_check、prompt_version、book）
manifest.json               # 段数、完成段数、章数、总成本、耗时、提示词版本
```

```powershell
# 产物列表（含预签名下载地址）
GET /v1/tasks/{task_id}/artifacts
# 直接下载（会校验 key 属于该任务前缀）
GET /v1/tasks/{task_id}/artifacts/download?key=超级傀儡兽/<task_id>/chapters.json
# 本地 fallback 的预签名 URL 由本服务校验 HMAC 后返回文件
GET /v1/artifacts/download?key=…&expires=…&sig=…
```

文件不存在返回 `404 artifact_not_found`；签名错误/过期返回 `403 artifact_signature_invalid`；
key 越权（不属于该任务）返回 `404 artifact_not_found`（不泄露其他任务是否存在）。

### 5) 存储配置

| 场景 | 配置 |
|---|---|
| 数据库（默认） | `STORAGE_BACKEND=db`；产物与上传源文件写入 `stored_objects` 表，下载走本服务 HMAC 预签名 |
| 本地磁盘 fallback | `STORAGE_BACKEND=local`、`STORAGE_LOCAL_DIR=...`；下载走本服务 HMAC 预签名 |
| MinIO / S3 / OSS | `STORAGE_BACKEND=s3`、`S3_ENDPOINT_URL`、`S3_BUCKET`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`；boto3 生成原生预签名 URL |

三种后端接口行为一致（列表/下载/预签名/缺失错误码），测试全部跑在本地 fallback。
`STORAGE_BACKEND=db` 时 api / worker / scheduler 必须连同一个数据库（worker 复用当前事务会话写入，避免 SQLite 写锁）。
`STORAGE_BACKEND=s3` 需要 `requirements.txt` 中已声明的 `boto3`；缺依赖、缺 `S3_BUCKET`、
服务不可达都会在启动时抛出带修复提示的 `RuntimeError`（不会在首次上传时才崩溃）。

## 改编 / 审查 runner

与拆解同一套执行模型：`app/prompts/adapt.py`、`app/prompts/review.py` 只做 **薄封装**
（模板、常量、规范化函数全部来自 `src/adapt.py`、`src/review.py`），`app/runners/adapt.py`、
`app/runners/review.py` 负责服务端编排、断点、取消、产物与计量。

- 提示词版本写入 `tasks.prompt_version`（`adapt-2026-11-v1` / `review-2026-11-v1`）与产物 manifest；
- 每个书级阶段 / 章节段 / 审查章节均为独立 `task_steps`，重跑自动跳过；
- 取消在段边界生效；`DECOMPOSE_SEGMENT_BATCH` 同时控制改编/审查的让出粒度；
- 产物入对象存储（source/name_map/roster/book/segments/decomposed/chapters/manifest，
  审查为 `review/chapter-XXX.json|md|html`）。

### 改编任务示例

```json
{
  "type": "adapt",
  "params": {
    "book": "样本书",
    "source_key": "样本书/<decompose_task_id>/decomposed.json",
    "out_book": "新书",
    "chapters": 3,
    "chapters_per_call": 1,
    "style": "科幻悬疑",
    "sequel_chapters": 2
  }
}
```

也支持 `source_path` 或内联 `book_data`（小样本/测试）；`local=true` 走 `src` 的本地改编不调模型。

### 审查任务示例

```json
{
  "type": "review",
  "params": {
    "book": "样本书",
    "chapters": [{"chapter_no": 1, "text": "第1章 ..."}],
    "chapters_doc": {...},
    "decomposed_doc": {...},
    "checks": ["ai_taste", "stats"],
    "advice_scope": "ai"
  }
}
```

`chapters_doc`/`decomposed_doc` 可换成 `chapters_key`/`decomposed_key`（对象存储 key）；
不传时退回 `src` 的 `data/<book>/…`（只读挂载）。未配置模型 Key 时返回 422（审查必须有 AI 调用）。

## 网关流式 usage

`POST /v1/chat/completions` 支持 `stream=true`：

- 透传上游 SSE，同时在字节流上解析 `data:` 行；
- 优先使用上游 `usage`（`prompt_tokens/completion_tokens/total_tokens`）；
- 上游未返回 usage 时按字符估算（CJK≈1 字 1 token，其它≈4 字符 1 token），
  `usage_events.meta.estimated=true`，成本不会漏计；
- 归集在响应结束后的后台任务里用独立 DB session 写入，失败只记日志不影响输出。

## 定时与自愈

```powershell
python -m app.scheduler --once   # 手动跑一轮
python -m app.scheduler          # 常驻（SCHEDULER_INTERVAL_SECONDS）
# 或 SCHEDULER_ENABLED=true 随 API 启动（单实例部署）
```

每轮幂等执行：

| 任务 | 说明 |
|---|---|
| `sweep_leases` | `running` 且 `lease_until` 超时 → `queued`，写事件与审计 `task.lease_reclaim`（`FOR UPDATE SKIP LOCKED`，避免双跑） |
| `expire_due` | 订阅到期清扫（`active/trialing/canceled`） |
| `expire_grace_period` | `past_due` 超过 `SUBSCRIPTION_GRACE_DAYS` → `expired` |
| `send_renewal_reminders` | 到期前 `SUBSCRIPTION_REMINDER_DAYS` 写审计并发送续费提醒通知（按订阅/天幂等） |
| `notify_expired_subscriptions` | 订阅过期发送 `subscription_expired` 通知 |
| `sweep_credits` | 额度包过期清扫 + 7 天内到期提醒 |
| `retry_notifications` | 失败通知按退避重试 |
| `check_usage_alerts` | 当日用量 >「月额度/30 × 倍数」写 `usage.anomaly` 审计与告警通知，**不封禁** |
| `reconcile_daily` | 拉取前一日渠道账单并比对（单渠道失败不阻塞其它渠道） |

## 可观测

- `GET /metrics`（Prometheus 文本）：队列深度、任务成功/失败/取消、重新入队、模型调用数与成本/token、
  回调失败与重复、额度拒绝、限流、用量告警；
- 结构化 JSON 日志包含 `request_id` 与 `trace_id`（HTTP 复用 request_id，worker 用任务号）；
- 可选 Sentry：设置 `SENTRY_DSN` 即启用，未设置或未安装 SDK 时静默跳过。

## 防滥用

- 注册 / 登录按 IP + Redis 计数限频（`REGISTER_RATE_LIMIT_PER_MINUTE` / `LOGIN_RATE_LIMIT_PER_MINUTE`），
  超限返回 429 `rate_limited` 并计入 `moxie_rate_limited_total`；
- 支付回调先校验可选 IP 白名单，再做渠道签名验签；白名单外返回 403 `webhook_source_rejected` 并审计；
- 异常用量只写审计 + 指标告警，不自动封禁账号。

## 提示词与规则服务

- `app/prompts/decompose.py`：`PROMPT_VERSION = "decompose-2026-11-v1"`，薄封装 `src/decompose.py`
  的 `build_prompt` / `build_merge_prompt` / `split_text` / `slice_first_chapters` / `to_chapters_json` /
  `signing_check`（默认按 `SRC_PATH` 导入 `src/`），**不复制第二套提示词**；
- `app/prompts/adapt.py` / `app/prompts/review.py`：同模式封装 `src/adapt.py`、`src/review.py`，
  版本分别为 `adapt-2026-11-v1`、`review-2026-11-v1`；
- 提示词只在服务端运行时渲染，然后拼成 messages 发给模型；API 响应、`/openapi.json`、`/docs`、
  任务详情与日志都不含提示词明文（有测试断言）；
- `prompt_version` 写入任务记录与 `chapters.json` / `manifest.json`，便于回溯与灰度。

## Docker Compose（生产形态）

```powershell
cd server
copy .env.example .env
# 必须修改：JWT_SECRET、POSTGRES_PASSWORD、LICENSE_PRIVATE_KEY_PEM、LLM_API_KEY
docker compose up -d --build
```

服务：`postgres` / `redis` / `minio` / `minio-init` / `api` / `worker` / `scheduler`。
- `src/` 以只读卷挂到 `/src`（提示词服务用），`input/` 只读挂到 `/data/input`（拆解源文件）；
- `api` 启动前自动执行 `alembic upgrade head`；
- 默认 `STORAGE_BACKEND=db`，产物与上传源文件全部写入数据库，无需 MinIO；
- 需要对象存储时设 `STORAGE_BACKEND=s3` 写 MinIO 桶 `moxie`（`minio-init` 负责建桶，S3Storage 也会兜底建桶）；
- `STORAGE_BACKEND=s3` 的镜像必须包含 `requirements.txt` 中的 `boto3`；缺依赖、缺 `S3_BUCKET`、
  或 MinIO 不可达时，S3Storage 构造会抛出包含 `endpoint/bucket` 与修复建议的 `RuntimeError`，
  容器日志可直接定位，而不是在首次上传时崩溃；
- 也可把 `STORAGE_BACKEND=local`，api 与 worker 共享 `artifactdata` 卷，下载仍走 `/v1/artifacts/download`；
- `.env` 中 `LICENSE_PRIVATE_KEY_PEM` 缺失会导致 api/worker/scheduler 启动失败（多 worker 禁止临时密钥）；
  `PAYMENTS_MOCK_ENABLED/FAKE_ENABLED` 保持 `false`，否则生产启动失败。

- `S3_PUBLIC_ENDPOINT_URL` 用于预签名：容器内用 `S3_ENDPOINT_URL=http://minio:9000`，
  浏览器用公开地址（本机 `http://127.0.0.1:9000`）。预签名必须用公开 endpoint 计算 SigV4，
  只替换 URL 域名会 403，服务端已用独立 `presign_client` 处理；
- api/worker/scheduler 为 `restart: unless-stopped`，postgres/redis/minio 同样；`minio-init` 是一次性任务；
- `pgdata` / `redisdata` / `miniodata` / `artifactdata` 四个命名卷持久化，`down` 默认保留。

> 2026-11-04 本机 Docker Desktop + WSL2 实测通过：`docker compose up -d --build` 后
> postgres/redis/minio/api/worker/scheduler 全部 healthy；`/healthz`、`/readyz`、`/metrics` 均 200；
> `alembic current` 为 `e5f6a7b8c9d0 (head)` 且 `alembic check` 无差异；
> 注册→登录→设备→mock 订阅→上传→拆解任务→worker→预签名下载→额度扣减全链路通过，CORS 预检 200。
> 数据库 `pg_dump/pg_restore` 与 MinIO `mc mirror` 恢复演练见 [docs/backup.md](docs/backup.md)。
> 该环境 Docker Hub 直连受限，镜像经国内镜像源拉取后重新 tag 为官方名称；属于网络环境差异，不影响仓库配置。

> 生产请把 `AUTO_CREATE_TABLES=false`，只通过 Alembic 建表。

生成 License 私钥：

```powershell
python -c "from app.security import LicenseSigner; print(LicenseSigner.generate_pem())"
```

把输出（含 `BEGIN/END` 行）写入 `.env` 的 `LICENSE_PRIVATE_KEY_PEM`，多行值用双引号包裹并把换行写成 `\n`。
未配置时会生成进程内临时密钥：重启后旧 License 失效（仅开发用）。

## 测试

```powershell
cd server
python -m pytest
```

当前结果：**127 passed, 3 skipped**（SQLite + fakeredis + 本地磁盘产物，不依赖 Docker/MinIO/真实 key）。
3 条 skip 均为 `live`（真实渠道凭据缺失自动跳过）。

覆盖范围：

- 基础 51 条：登录/刷新/轮换、设备上限、License 签发与宽限、额度预占/结算/超限/幂等、
  任务幂等与取消、订阅状态流转/续费/到期、网关 key 与 BYOK 不落库、错误格式与鉴权、拆解链路；
- 支付 11 条（8 passed + 3 skip）：微信/支付宝/Stripe 验签与篡改/重放、金额不符、退款幂等、
  升级补差、对账分类、发票、未配置渠道 501；
- 上传 7 条（`test_uploads.py`）：上传→建任务→runner 读取→产物落盘、413 超大、415 扩展名、
  401 未鉴权、跨账号 404、429 限频、保留期清理；
- 第四期新增：
  - `test_credits.py`（4）：额度包购买/回调发放幂等、套餐优先、超额 402、过期与退款回收；
  - `test_notifications.py`（5）：emit 幂等、已读、SMTP 未配置降级、重试退避、管理员查询/重投；
  - `test_admin_ext.py`（10）：用户封禁/越权/support 只读/额度调整/退款审批幂等/审计分页过滤/任务看板与重试/发票 legacy 状态/退款别名；
  - `test_cors.py`（3）：管理端预检、普通请求回显来源与 credentials、未知来源 400；
  - `test_similarity.py`（3）：原文复制高重合、改写低重合、跨章节聚合；
  - `test_legal_gates.py`（9）：生产 mock 4xx 且不开通、mock 默认关闭、缺签名密钥、License 私钥、
    版权确认（body/header）；
  - `test_migrations.py`（2）：空库 `upgrade head` 建表、`AUTO_CREATE_TABLES=false` 启动；
  - `test_storage_s3.py`（4）：缺 boto3 / 缺 bucket / 端点不可达 / 预签名公开 endpoint；
  - `test_invoicing.py`（7）：stub 全流程、回调幂等、验签 403、缺凭据 501、非法流转 409、越权、管理端代开。

```powershell
python -m pytest -o addopts="" -q          # 127 passed, 3 skipped
python -m pytest -m live -q                # 有凭据时跑真实沙箱
```

新增 6 条拆解专项：

| 用例 | 覆盖 |
|---|---|
| `test_decompose_segments_resume_and_artifacts` | 分段执行 → 产物列表/下载/内容、逐段 meta、usage 归集、额度结算、缺失 404、签名错误 403 |
| `test_resume_skips_completed_segment` | `batch=1` 中断后续跑只补剩余段，已完成段 `updated_at` 不变 |
| `test_missing_source_rejected_at_create` | 源文件不存在 422 `source_not_found` |
| `test_byok_header_not_persisted` | BYOK 只走请求头，任务响应/参数不含密钥 |
| `test_prompts_not_exposed` | 详情/日志/openapi/docs 无提示词明文，无 prompt 路径 |
| `test_artifact_isolation` | 其他账号访问他人产物 404 |

超限仍由原有用例覆盖：`test_create_tasks_until_quota_limit` 返回 `402 quota_exceeded`。

## API 一览（完整定义见 `/docs`）

| 方法 | 路径 | 鉴权 | 幂等 | 说明 |
|---|---|---|---|---|
| POST | `/v1/auth/register` | 否 | 邮箱/手机号唯一 | 注册并返回 access+refresh |
| POST | `/v1/auth/login` | 否 | - | 登录 |
| POST | `/v1/auth/refresh` | 否 | Refresh Token 轮换 | 旧 Refresh 立即失效 |
| POST | `/v1/auth/logout` | 是 | 是 | 吊销当前会话 |
| GET | `/v1/auth/me` | 是 | - | 当前账号 |
| POST | `/v1/devices` | 是 | `device_hash` 幂等 | 注册设备；超过 2 台返回 `device_limit_reached` |
| GET | `/v1/devices` | 是 | - | 设备列表 |
| DELETE | `/v1/devices/{id}` | 是 | 是 | 解绑设备并吊销其 License |
| GET | `/v1/license?device_id=` | 是 | - | 签发 Ed25519 License（7 天刷新 / 14 天宽限） |
| GET | `/v1/license/public-key` | 否 | - | 客户端内置公钥 |
| POST | `/v1/license/verify` | 否 | - | 离线校验（ok / refresh_required / grace / expired / invalid） |
| POST | `/v1/uploads` | 是 | - | 上传源文件（multipart `file`），返回 `source_key`；30MB/扩展名/限频 |
| DELETE | `/v1/uploads?key=` | 是 | 是 | 删除自己的上传源文件（跨账号 404） |
| POST | `/v1/tasks` | 是 | `Idempotency-Key` | 创建拆解/改编/体检任务（预占额度；校验源文件/归属） |
| GET | `/v1/tasks/{id}` | 是 | - | 状态与进度（含 `cost_actual_cents`、`prompt_version`） |
| GET | `/v1/tasks/{id}/logs?after=` | 是 | - | 轮询日志（按 seq 增量） |
| POST | `/v1/tasks/{id}/cancel` | 是 | 是 | 排队任务立即释放；运行任务段边界生效 |
| GET | `/v1/tasks/{id}/artifacts` | 是 | - | 产物列表 + 预签名下载地址 |
| GET | `/v1/tasks/{id}/artifacts/download?key=` | 是 | - | 任务内产物下载；缺失 404 |
| GET | `/v1/artifacts/download?key=&expires=&sig=` | 签名 | - | 本地 fallback 的签名下载 |
| GET | `/v1/plans` | 否 | - | 套餐与权益 |
| GET | `/v1/payments/providers` | 否 | - | 当前可下单的支付渠道（生产不含 mock/fake） |
| POST | `/v1/subscriptions` | 是 | `Idempotency-Key` | 下单（trialing），返回支付参数 |
| GET | `/v1/subscriptions/current` | 是 | - | 当前订阅、剩余天数、续费提醒 |
| POST | `/v1/subscriptions/{id}/cancel` | 是 | 是 | 到期取消 / 立即取消 |
| POST | `/v1/subscriptions/{id}/resume` | 是 | 是 | 撤销到期取消或恢复暂停 |
| POST | `/v1/subscriptions/{id}/renew` | 是 | `Idempotency-Key` | 手动续费下单 |
| GET | `/v1/orders` | 是 | - | 订单列表 |
| GET | `/v1/entitlements` | 是 | - | 当月额度：上限/已用/预占/剩余 |
| GET | `/v1/usage`、`/v1/usage/summary` | 是 | - | 用量明细与汇总（含模型 token/成本） |
| POST | `/v1/subscriptions/{id}/upgrade` | 是 | `Idempotency-Key` | 手动升级（按剩余天数补差） |
| POST | `/v1/subscriptions/{id}/portal` | 是 | - | Stripe Customer Portal |
| GET | `/v1/orders/{id}` | 是 | - | 订单详情（含退款金额、渠道单号） |
| GET | `/v1/refunds` | 是 | - | 退款列表 |
| POST | `/v1/orders/{id}/invoice` | 是 | 是 | 申请发票记录 |
| GET | `/v1/invoices` | 是 | - | 我的发票记录 |
| GET | `/v1/invoices/{id}` | 是 | - | 发票详情 |
| POST | `/v1/invoices/{id}/apply`、`/void` | 是 | - | 提交渠道开票 / 作废 |
| POST | `/v1/payments/invoices/callback` | 否（HMAC 验签） | `event_id` 幂等 | 开票渠道异步回调 |
| GET | `/v1/webhooks/{provider}` | 否（验签） | `(provider, event_id)` 唯一 | 支付回调（原始 body 验签） |
| POST | `/v1/chat/completions` | 是 | - | OpenAI 兼容网关（`stream=true` 解析 usage；`X-BYOK-Key`） |
| GET | `/v1/credit-packs` | 否 | - | 可售额度包列表 |
| POST | `/v1/credit-packs/{code}/purchase` | 是 | `Idempotency-Key` | 购买额度包（`provider` 必填；生产禁用 mock/fake） |
| GET | `/v1/notifications` | 是 | - | 我的站内信 |
| POST | `/v1/notifications/{id}/read`、`/read-all` | 是 | - | 标记已读 |
| GET/POST/PATCH | `/v1/admin/users`、`/users/{id}`、`/users/{id}/ban|unban` | admin/support | 用户查询、详情、封禁/解封（写操作审计） |
| GET/PATCH | `/v1/admin/subscriptions`、`/subscriptions/{id}` | admin/support | 订阅列表与套餐/到期调整 |
| GET/POST | `/v1/admin/accounts/{id}/quota-adjustments` | admin/support | 额度手工调整与历史 |
| GET | `/v1/admin/orders`、`/orders/{id}` | admin/support | 订单列表与详情 |
| GET | `/v1/admin/refunds` | admin/support | 退款列表，返回 `items` + `refunds` 别名 |
| POST | `/v1/admin/refunds/{id}/approve|reject` | admin | 退款审批（备注必填、幂等） |
| GET | `/v1/admin/tasks/dashboard` | admin/support | 队列深度、运行/失败/可重试数 |
| POST | `/v1/admin/tasks/{id}/retry` | admin | 失败/取消任务重试 |
| GET | `/v1/admin/alerts`、`/notifications` | admin/support | 告警与发送记录 |
| POST | `/v1/admin/notifications/{id}/retry` | admin | 失败通知重投 |
| POST | `/v1/admin/orders/{id}/refund` | admin | 手动退款 |
| GET | `/v1/admin/payments/reconcile` | admin/support | 对账报告查询 |
| POST | `/v1/admin/payments/reconcile` | admin | 手动对账 |
| GET | `/v1/admin/payments/reconcile/export` | admin/support | 对账差异 CSV |
| GET/POST | `/v1/admin/invoices`、`/invoices/{id}` | admin/support | 发票列表（`status=rejected` 映射 `voided`，返回 `status` + `legacy_status`）/ 详情 |
| POST | `/v1/admin/invoices/{id}/issue|void` | admin | 提交渠道开票 / 作废（原因必填） |
| GET | `/v1/admin/audit-logs` | admin/support | 审计日志分页 + 过滤 |
| GET | `/v1/admin/renewal-reminders` | admin/support | 7 天内到期订阅 |
| POST | `/v1/admin/subscriptions/expire-due` | admin | 到期清扫（供 cron 调用） |
| GET | `/metrics` | 否 | - | Prometheus 指标（`METRICS_ENABLED=false` 时 404） |

## 关键机制

### 额度账本
- `usage_aggregates`（账号 + 指标 + 月份，`used/reserved`）是实时校验口径；
- `usage_events` 是权威明细，`(account_id, idempotency_key)` 唯一，重放不重复扣费；
- 流程：`reserve`（检查 `used+reserved+qty ≤ limit`）→ `commit`（失败/取消则 `release`）；
- 拆解按 `books_month` 每本预占 1；批量让出（`TaskReschedule`）时**保留预占**、任务回到 `queued`；
- 超限统一返回 `402 quota_exceeded`，没有订阅返回 `402 no_active_subscription`。

### 三层幂等
1. 任务：`(account_id, idempotency_key)` 唯一；
2. 步骤：`task_steps(task_id, step_key)` 主键，重跑跳过已完成步骤（拆解段级断点）；
3. 用量：`usage_events(account_id, idempotency_key)` 唯一（每段/每次合并一个唯一键）。

### 计量与成本
- 每段记录 `prompt_tokens / completion_tokens / total_tokens / cost_cents`（`task_steps.meta` + `usage_events`）；
- `tasks.cost_estimate_cents` 为预估，`cost_actual_cents` 按实际 token 累加；
- 任务结束写 `manifest.json` 的 `total_cost_cents / duration_seconds / segments`，并写审计 `task.execute`。

### 额度包与套餐优先级
- 一次性额度包 `credit_packs / credit_grants`，12 个月有效（`CREDIT_PACK_VALIDITY_DAYS`），不随月度清零；
- 扣减顺序：套餐额度优先，不足部分按 `expires_at` 升序从额度包预占；包也不足才返回 `402 credit_pack_insufficient`；
- 任务记录 `reserved_plan_quantity / reserved_pack_items`，取消/失败/断点恢复都会同时释放套餐与包；
- `GET /v1/entitlements` 合并展示 `limit/used/reserved/pack_remaining/total_remaining` 与 `credits` 明细；
- 退款按未用量比例回收额度包（全额吊销 / 部分缩减 `quantity_granted`）。

### 通知
- 统一 `notifications.emit`：站内信落库 + `notification_deliveries` 投递；业务 dedupe_key 保证幂等；
- 邮件 SMTP、短信 no-op；失败按 `next_retry_at` 退避，scheduler 与管理员都可重试；
- 覆盖续费提醒、到期、支付成功/失败、额度不足、异常用量、额度包到期。

### 管理端权限与 CORS
- `admin` 可读写，`support` 只读（`require_staff`）；写操作一律 `require_admin` 并写审计；
- 分页统一 `{items,total,page,page_size}`；错误码 `admin_required` / `staff_required` / `*_not_found`；
- CORS 白名单 `CORS_ALLOW_ORIGINS`（默认 `http://127.0.0.1:5180,http://localhost:5180`），
  允许 `Authorization`、`X-Rights-Confirmed` 等必要头，不使用 `*` 搭配 credentials；
- 完整接口清单见 [docs/billing-admin.md](docs/billing-admin.md)。

### 订阅状态机
`trialing → active → past_due → paused → canceled → expired`，服务端用 `TRANSITIONS` 表强校验；
支付成功才从 `trialing` 变为 `active`；取消可「到期取消」或「立即取消」；续费从周期末尾顺延。

### 支付与对账
- 统一订单/订阅领域层：状态机 `created→pending→paid→refunded/closed/failed`、金额与币种校验、
  plan/entitlement 映射、订单一号唯一（`external_order_no`）、升级按剩余天数补差；
- `mock`：本地同步返回回调参数；`fake`：无凭据时的全流程演示；`wechat` / `alipay` / `stripe`
  已按官方签名/验签/解密/退款/对账单实现，凭据缺失返回 `501 provider_not_configured`；
- 回调：原始 body 验签 → 幂等 `(provider, event_id)` → 金额/商户号校验 → 开通/退款；失败返回规范错误码并审计；
- 对账：每日拉取渠道账单，差异分类 `amount_mismatch/channel_only/local_only/duplicate_payment`，
  结果落 `reconcile_reports`，支持管理端查询与 CSV 导出；
- 发票：`InvoiceProvider` 抽象（`stub` 本地模拟 / `nuonuo` 真实适配位），状态机
  `requested→issuing→issued→voided/failed`，回调验签 + `event_id` 幂等，全程审计；
  真实渠道缺凭据返回 `501 invoice_provider_not_configured`，详见 [docs/invoicing.md](docs/invoicing.md)。
- 详见 [docs/payments.md](docs/payments.md)。

### 安全
- 不提供任何提示词接口；OpenAPI 中无 prompt 路径；提示词只在服务端渲染后发模型；
- BYOK key 只经请求头进入内存/Redis（TTL 1h，仅当次任务），**不落库、不写日志**；写进 `params` 直接拒绝；
- 源文件只能读 `TASK_SOURCE_DIRS` 白名单内、且限制大小；
- 所有写接口要求 JWT；资源按 `account_id` 隔离；产物 key 必须属于当前任务前缀；
- 错误统一 `{"error":{"code","message","request_id"}}`，500 不回显堆栈；
- 日志为 JSON 行，`Authorization` / `api_key` / `token` 等字段名自动脱敏。

## 生产 vs 测试差异（重要）

| 项 | 测试 / 本地 | 生产 |
|---|---|---|
| 数据库 | SQLite（`FOR UPDATE` 被忽略） | **PostgreSQL 16**，额度校验用行锁 |
| Redis | fakeredis（进程内） | Redis 7（RQ 队列、限流、BYOK 临时存储） |
| 队列 | `enqueue=False`，任务保持 `queued` | RQ worker 自动消费 |
| 产物存储 | 数据库 `stored_objects`（`STORAGE_BACKEND=db`） | 同左，或 MinIO / S3（`STORAGE_BACKEND=s3`） |
| 模型 | `MODEL_STUB=true` 假模型 | 真实上游（经本服务网关） |
| 源文件 | 本地 `input/` | 只读挂载 `/data/input` |
| License 私钥 | 可显式允许进程内临时密钥（`LICENSE_ALLOW_EPHEMERAL_KEY=true`） | `.env` 固定私钥；缺失即启动失败 |
| 支付 | `mock` / `fake`（默认关闭；test/dev 显式开启） | 微信/支付宝/Stripe；`PAYMENTS_MOCK_ENABLED=false`、`PAYMENTS_FAKE_ENABLED=false`，开启则启动失败 |
| 定时任务 | 手动 `python -m app.scheduler --once` | 独立 `scheduler` 容器或 `SCHEDULER_ENABLED=true` |
| 可观测 | `/metrics` + 本地日志 | Prometheus 抓取 + 可选 Sentry |
| 建表 | `AUTO_CREATE_TABLES=true` 或 Alembic | 仅 Alembic（`AUTO_CREATE_TABLES=false`） |

> SQLite 下并发预占不是原子的，**不能**用于生产；测试只验证业务规则。

## 迁移

```powershell
alembic upgrade head
alembic current
# 修改模型后
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

迁移历史：`48def3cadb5b_initial_schema.py` → `a1b2c3d4e5f6_task_step_meta.py`（`task_steps.meta`）
→ `d4e5f6a7b8c9_payments.py`（订单列、`refunds`、`reconcile_reports`、`invoice_requests`）
→ `e5f6a7b8c9d0_credits_notifications.py`（`credit_packs/credit_grants/notifications/notification_deliveries`、
`orders.pack_id`、`tasks` 预占拆分列）。

一致性校验：

```powershell
$env:DATABASE_URL="sqlite:///./tmp_alembic.db"
$env:AUTO_CREATE_TABLES="false"
python -m alembic upgrade head
python -m alembic check   # 输出 "No new upgrade operations detected."
```

`tests/test_migrations.py` 会在空库上跑 `upgrade head`，断言 `credit_packs` 等表存在，
并在 `AUTO_CREATE_TABLES=false` 下启动应用、`/readyz` 通过、额度包种子已写入。

## 第四期剩余说明

1. **真实渠道冒烟**：本机无微信/支付宝/Stripe 凭据，未做真实沙箱扣款；`pytest -m live` 已隔离，
   凭据齐全后自动生效（需要哪些变量见 [docs/payments.md](docs/payments.md) 第 2 节）。
2. **Compose 实测**：Postgres / Redis / MinIO / api / worker / scheduler 已在 Docker Desktop + WSL2
   实跑；修复了双 worker 启动竞态（种子数据改用 `pg_advisory_xact_lock`）、多 worker 临时 License
   密钥不一致（固定 PEM）、预签名 host 不可达（新增 `S3_PUBLIC_ENDPOINT_URL`）、缺少重启策略。
   注意本机 Docker Hub 直连受限，镜像需经镜像源拉取，详见上节。
3. **自动开票**：已抽象 `InvoiceProvider`，`stub` 可全流程模拟，`nuonuo` 为真实渠道适配位
   （缺凭据 501），支持申请/查询/作废/回调验签与幂等，详见 [docs/invoicing.md](docs/invoicing.md)；
   真实商户凭据联调仍未进行。
4. **退款自动化**：已支持按已用量/剩余时长比例报价、审批/驳回与权益回收；
   真实渠道退款仍需商户凭据，测试使用 mock/fake 与手工退款接口。
5. **管理端前端差异**：审计日志前端仍用 `limit`（服务端已兼容）；发票作废前端传 `rejected`
   （服务端归一为 `voided` 并返回 `legacy_status`）；退款/发票列表提供 `items` 与旧别名。
   CORS 已支持，跨域只需配置 `CORS_ALLOW_ORIGINS`，详见 [docs/billing-admin.md](docs/billing-admin.md) 第 4 节。

## 常见问题

- **启动报 `no such table`**：先 `alembic upgrade head`；或本地临时设 `AUTO_CREATE_TABLES=true`。
- **任务一直 `queued`**：没有 Redis 时属预期；用 `python -m app.worker.worker --once` 或启动 Redis + RQ worker。
- **拆解报 `source_not_found` / `source_not_allowed`**：检查 `TASK_SOURCE_DIRS` 白名单与文件是否存在。
- **产物下载 403 `artifact_signature_invalid`**：本地 fallback 的预签名 URL 有时效（默认 900s），过期请重新调列表接口。
- **启用 S3 报缺少 boto3 / 连接失败**：先 `pip install -r requirements.txt`；再检查 `S3_ENDPOINT_URL/S3_BUCKET/凭据`。
  启动阶段会抛出带 endpoint/bucket 的 `RuntimeError`，不会静默降级。
- **支付回调 409/400**：检查 `X-Mock-Signature` 是否按 `HMAC(secret, "event_id:order_id:amount_cents")` 生成。
- **License 重启后失效**：未配置固定 `LICENSE_PRIVATE_KEY_PEM`；多 worker 禁止临时密钥，缺失会启动失败。
- **设备上限**：默认 2 台，`MAX_DEVICES` 可调；先在旧设备 `DELETE /v1/devices/{id}`。
