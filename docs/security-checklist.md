# 安全与合规检查清单

> 适用范围：`server/` 云端服务 + 桌面端云端接入。
> 状态：`[x]` 已核对（附证据） / `[ ]` 待办（附原因与建议）。
> 最后核对：2026-11-04。

## 1. 密钥管理

- [x] `.env` / `server/.env` 不入库：根 `.gitignore` 与 `server/.gitignore` 均已忽略 `.env`；仓库内只有 `server/.env.example`。
- [x] 配置项集中在 `.env.example`：数据库、JWT、License 私钥、微信/支付宝/Stripe、S3、Webhook 容差等均有占位说明。
- [x] JWT / 支付 / 对象存储密钥一律从环境变量读取，不写死在代码里；默认值仅用于开发并带 `change-me` 提示（`server/app/config.py`）。
- [x] BYOK 密钥只允许通过 `X-BYOK-Key` 请求头传入；任务参数中出现 `secret` 字段直接 422 拒绝（`server/app/runners/decompose.py`）。
- [x] 在线端 BYOK Key 仅存 `sessionStorage`（`mx_byok_key`），只在 `withByok` 请求注入请求头；不写 `localStorage`、不入 Vue store、不随业务参数落库（`client/src/services/byok.ts`）。
- [x] 支付回调日志与订单 payload 字段做脱敏（`key/secret/token/sign/password/cert/authorization` → `[redacted]`，`server/app/services/orders.py`）。
- [ ] 桌面端云端 token 加密存储尚未落地（此前记录的 `src/cloud.py` 不存在）；接入云端模式时需补 DPAPI（Windows）/ AES-GCM（非 Windows）存储，不写明文配置。
- [x] 生产启动 fail-fast：默认占位符/弱口令由 `app/main.py` 的 `Settings.is_production` 闸门拦截，
      `mock`/`fake` 渠道生产禁注册（`payments/__init__.py`），License 私钥、载荷签名密钥生产必填。
- [x] **已处理（2026-11-17）**：`server/requirements.txt` 每个依赖钉主版本上界（如 `>=2.0,<3`），
      新增 `server/requirements.lock.txt` 精确版本锁文件，Dockerfile 优先用 lock 构建。
      CI 增加 `migration-check`（`alembic upgrade head` + `alembic check`，零漂移）与
      `dependency-audit`（`pip-audit --strict` + 三端 `npm audit --omit=dev --audit-level=high`）。
      2026-11-18 已用 CPython 3.12.16 重新冻结 `requirements.lock.txt`，与生产镜像 `python:3.12-slim` 对齐，
      `pip check` 无冲突，并用 3.12 环境跑通安全/初始化定向测试。

## 2. 日志脱敏

- [x] 统一日志过滤器按字段名脱敏：`api_key/apikey/authorization/password/secret/token/byok`（`server/app/logging_setup.py`）。
- [x] 日志只记录 `request_id` / `trace_id` / 任务状态 / 用量，不记录提示词正文；提示词接口已下线。
- [x] 支付回调原始 body 只用于验签，不整体落库；订单 payload 入库前脱敏。
- [ ] 建议增加日志采样与保留策略（当前未配置轮转），避免任务日志无限增长；生产建议接入 Loki/ELK。

## 3. 回调验签与幂等

- [x] Mock / Fake 渠道：HMAC-SHA256 + `hmac.compare_digest` 常量时间比较（`server/app/payments/mock.py`、`server/app/security.py`）。
- [x] 微信支付 v3：平台证书验签 + APIv3 解密；支付宝：RSA2 验签 + 金额/卖家校验；Stripe：HMAC-SHA256 + 时间戳容差（默认 300s）。
- [x] 回调保留原始请求体，避免 JSON 重新序列化破坏签名。
- [x] 回调幂等：事件 ID 去重，重复回调返回已处理并计入 `moxie_webhook_duplicates_total`。
- [x] 单测覆盖伪造签名、篡改金额、过期时间戳、重复回调：
  `server/tests/test_billing.py`、`server/tests/test_payments.py`。
- [ ] 真实微信/支付宝/Stripe 沙箱凭据未提供，`pytest -m live` 用例仍未实际跑通（缺少凭据自动跳过）。

## 4. 越权与数据隔离

- [x] 任务详情/取消/日志/产物列表均按 `account_id` 过滤，跨账号返回 404（`server/tests/test_tasks.py`、`server/tests/test_decompose_runner.py`）。
- [x] 源文件上传跨账号隔离：他人上传不可下载/删除（`server/tests/test_uploads.py::test_upload_cross_account_isolation`）。
- [x] 预签名产物 URL 带签名与有效期（默认 900s），签名错误/过期 403 `artifact_signature_invalid`。
- [x] 本地存储 key 做 `resolve()` + 根目录前缀校验，阻断路径穿越（`server/app/services/storage.py`）。
- [x] 拆解源文件只允许读取白名单根目录（`is_relative_to` 校验，`server/app/runners/decompose.py`）。
- [x] 设备绑定上限 2 台，超限返回明确错误码（`server/tests/test_devices.py`）。
- [ ] 建议补一组自动化「横向越权矩阵」测试（账号 A 对账号 B 的所有资源逐接口探测），当前为关键接口点覆盖。

## 5. 提示词与知识产权保护

- [x] `GET /api/prompts` 已下线；OpenAPI 中不存在任何 `prompt` 路径（`server/tests/test_security.py`、`server/tests/test_decompose_runner.py::test_prompts_not_exposed`）。
- [x] 任务详情、日志、产物 manifest 只返回 `prompt_version`，不返回提示词明文。
- [x] 桌面端 Nuitka 包只带 `web/dist` 与 `config/workflow.json`，不再打包提示词配置（`src/build_app.py`）。
- [x] **已处理（2026-11-04）**：删除根目录 `user_prompt_settings.txt`、`mobile/android/app/src/main/assets/seed/user_prompt_settings.txt` 及构建 intermediates 副本；`src/`、`mobile/` 已无代码引用（本地模式使用 `src/prompts.py` 内置提示词）；`.gitignore` 新增 `user_prompt_settings.txt` 全局忽略；`prepare_android.py` 只复制 config/fonts/certs，`MainActivity.java` 不再拷贝该文件。验证：全盘检索无残留；`build_app.py` 仅收集 `web/dist` 与 `config/workflow.json`，旧 exe/build 产物中无该文件名；重建 `墨写-手机端-v2.8.0.apk` 后 `assets/seed` 仅含 `certs/config/fonts`、zip 清单无 `user_prompt_settings`；`python src/selftest.py --no-net` 51 通过 / 0 失败；`npm run build` 通过。注：该文件曾入库（提交 `5b3cdbc`），Git 历史仍保留旧 blob；如需彻底清除须另行重写历史，本次未执行。
- [ ] 建议对云端提示词做版本化 + 访问审计（当前有 `prompt_version`，但无独立审计表）。

## 6. 打包与客户端加固

- [x] Windows exe（Nuitka）不包含 `node_modules`、提示词配置；仅包含前端产物与工作流配置。
- [x] 桌面端日志与导出文件不写入 `api-key` / `token` / License 私钥（云端 token 加密存储）。
- [x] 离线 License 使用 Ed25519 验签，支持 7 天刷新 / 14 天离线宽限；到期明确降级提示。
- [x] 本地模式完整保留：未登录/断网不影响拆解、改编、设定编辑。
- [ ] 建议增加 exe 签名（Authenticode）与安装包校验和发布；当前打包 workflow 不要求真实签名。
- [ ] `mobile/` 侧 Chaquopy `.pyc` 仍可反编译，建议云端精简包移除该模块或做字节码保护。

## 7. 依赖与供应链

- [x] `pip-audit -r server/requirements.txt`：**无已知漏洞**（42 个依赖；报告本地生成，不入库）。
- [x] `npm audit --omit=dev`（`web/`）：**0 漏洞**（prod 95 个依赖；报告本地生成，不入库）。
- [ ] 未接入自动化定时审计；建议增加每周 `pip-audit` / `npm audit` 的 scheduled workflow，并在高危时失败。
- [ ] 未启用 Dependabot/Renovate；建议开启以跟进安全更新。

## 8. 传输与 Web 安全头

- [x] 生产部署文档要求 HTTPS 反向代理；支付回调使用公网 HTTPS 地址。
- [x] **已处理（2026-11-17）**：在线版统一安全头。FastAPI 中间件对普通 API 下发严格 CSP
      （`default-src 'self'` / `script-src 'self'` / `object-src 'none'`），对 `/docs`、`/redoc`、
      `/openapi.json` 用宽松策略以兼容 Swagger 内联脚本（见 `app/main.py` + `tests/test_security.py`）；
      nginx 两份配置（HTTP/HTTPS）用 `map $uri` 对前端 HTML/静态资源下发严格 CSP、对 API 路径留空交
      由后端决定，并补齐 X-Content-Type-Options / X-Frame-Options / Referrer-Policy / Permissions-Policy /
      HSTS（含静态资源 location，规避 add_header 不继承陷阱）。
- [ ] 本地 `webapp.py`（离线桌面端）仍未统一设置 CSP 等安全头；本地回环、非在线版，优先级低。
- [ ] 未做 CSRF 风险评估（当前桌面端本地 API 无跨站调用面，云端为 Bearer Token）；建议在网关层限制来源。

## 9. 备份与可恢复性

- [x] 提供 Postgres 逻辑备份、MinIO 镜像、SQLite 恢复演练脚本（`ops/backup/`）。
- [x] 本机完成 SQLite + 本地存储演练：行数与文件 SHA-256 全部一致，PASS。
- [ ] 生产恢复演练需具备 `pg_dump` / `mc` / Docker 环境；本机缺失，未执行 Postgres/MinIO 实链路。
- [ ] 备份文件默认未强制加密；生产建议强制设置 `GPG_RECIPIENT` 并限制备份目录权限。

## 10. 待办汇总（按优先级）

1. ~~**高**：移除/加密 Android 侧明文提示词 seed 资源~~ **已处理（2026-11-04）**。
2. **高**：提供真实支付沙箱凭据，跑通 `pytest -m live` 并留存回调验签记录。
3. ~~**中**：生产环境强制替换默认密钥（启动时校验）~~ **已处理**（`is_production` 闸门）。
4. ~~**中**：补齐 Web 安全响应头（CSP / nosniff / frame-options）~~ **已处理（2026-11-17）**，见 §8。
5. ~~**中**：依赖审计接入 CI~~ **已处理（2026-11-17）**：CI 含 pip-audit/npm audit + 迁移漂移检查。
   **仍待**：启用 Dependabot/Renovate 定时自动升级。
6. ~~**中**：refresh 会话归属校验、审计/回调 IP 口径统一~~ **已处理（2026-11-17）**：
   `auth.py` refresh 校验 `RefreshSession.account_id` 与 token `sub` 一致（防弱/泄露密钥下横向换发，
   见 `tests/test_auth.py`）；`services/audit.py` 与 `api/billing.py` 统一走 `deps.client_ip()`，
   反代下审计 IP 与支付回调白名单不再失效。
7. **中**：合规闸门目前仍是客户端自声明 `X-Rights-Confirmed`，缺服务端内容安全/授权留痕闭环；
   上传缺内容嗅探与病毒扫描。
8. **中**：容器资源限额已加到 `docker-compose.yml`（CPU/内存/pids），仍需实机 Docker 验证。
9. **低**：越权矩阵自动化、日志轮转与保留策略、备份强加密、前端监控/埋点、i18n/SEO/PWA。

## 11. 本轮变更记录（2026-11-17）

- **CI 重建**：新增 `.github/workflows/ci.yml`，5 个 job（server-tests / migration-check / web-apps / dependency-audit / e2e-desktop）。
- **迁移漂移修复**：新增 `alembic/versions/m2e3f4a5b6c7_...py`，把 `model_provider_configs.step_key`
  的唯一约束形态对齐 ORM 模型；SQLite 用 batch 模式，`alembic check` 现在零漂移。
- **前端质量防线**：client/admin 引入 Vitest + ESLint（flat config），补单测（http 4 / roles 4）；
  client 新增路由守卫与 404 页、路由懒加载（首屏 chunk 365KB→165KB）、请求默认 60s 超时
  （上传关闭）；admin 开启 TS strict（typecheck 仍通过）。
- **安全头 / IP / 会话**：严格 CSP、refresh 归属校验、审计/回调 IP 口径统一（见上）。
- **依赖治理**：requirements 主版本上界 + lock 文件 + Dockerfile 优先用 lock。
- **回归**：后端全量 247 passed / 3 skip；两端 typecheck、lint（0 error）、test、build 全通过；
  `alembic check` 零漂移；生产依赖 npm audit 0 漏洞。
