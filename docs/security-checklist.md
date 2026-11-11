# 安全与合规检查清单

> 适用范围：`server/` 云端服务 + 桌面端云端接入。
> 状态：`[x]` 已核对（附证据） / `[ ]` 待办（附原因与建议）。
> 最后核对：2026-11-04。

## 1. 密钥管理

- [x] `.env` / `server/.env` 不入库：根 `.gitignore` 与 `server/.gitignore` 均已忽略 `.env`；仓库内只有 `server/.env.example`。
- [x] 配置项集中在 `.env.example`：数据库、JWT、License 私钥、微信/支付宝/Stripe、S3、Webhook 容差等均有占位说明。
- [x] JWT / 支付 / 对象存储密钥一律从环境变量读取，不写死在代码里；默认值仅用于开发并带 `change-me` 提示（`server/app/config.py`）。
- [x] BYOK 密钥只允许通过 `X-BYOK-Key` 请求头传入；任务参数中出现 `secret` 字段直接 422 拒绝（`server/app/runners/decompose.py`）。
- [x] 支付回调日志与订单 payload 字段做脱敏（`key/secret/token/sign/password/cert/authorization` → `[redacted]`，`server/app/services/orders.py`）。
- [x] 桌面端云端 token 使用系统 DPAPI（Windows）/ AES-GCM（非 Windows）加密存储，不写明文配置（`src/cloud.py`）。
- [ ] 生产必须替换的默认值：`JWT_SECRET`、`MOCK_PAYMENT_SECRET`、`S3_SECRET_KEY`、`LICENSE_PRIVATE_KEY_PEM`。建议在启动时对 `ENV=production` 做强制校验（当前仅告警）。
- [ ] `server/requirements.txt` 为版本区间而非哈希锁定；建议增加 `pip-compile --generate-hashes` 的锁文件供生产镜像使用。

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

- [x] `pip-audit -r server/requirements.txt`：**无已知漏洞**（42 个依赖，报告 `ops/reports/pip-audit-report.json`）。
- [x] `npm audit --omit=dev`（`web/`）：**0 漏洞**（prod 95 个依赖，报告 `ops/reports/npm-audit-report.json`）。
- [ ] 未接入自动化定时审计；建议增加每周 `pip-audit` / `npm audit` 的 scheduled workflow，并在高危时失败。
- [ ] 未启用 Dependabot/Renovate；建议开启以跟进安全更新。

## 8. 传输与 Web 安全头

- [x] 生产部署文档要求 HTTPS 反向代理；支付回调使用公网 HTTPS 地址。
- [ ] 本地 `webapp.py` 未统一设置 `Content-Security-Policy` / `X-Content-Type-Options` / `X-Frame-Options`；建议在服务端响应头或反向代理层补齐。
- [ ] 未做 CSRF 风险评估（当前桌面端本地 API 无跨站调用面，云端为 Bearer Token）；建议在网关层限制来源。

## 9. 备份与可恢复性

- [x] 提供 Postgres 逻辑备份、MinIO 镜像、SQLite 恢复演练脚本（`ops/backup/`）。
- [x] 本机完成 SQLite + 本地存储演练：行数与文件 SHA-256 全部一致，PASS。
- [ ] 生产恢复演练需具备 `pg_dump` / `mc` / Docker 环境；本机缺失，未执行 Postgres/MinIO 实链路。
- [ ] 备份文件默认未强制加密；生产建议强制设置 `GPG_RECIPIENT` 并限制备份目录权限。

## 10. 待办汇总（按优先级）

1. ~~**高**：移除/加密 Android 侧明文提示词 seed 资源；确认发布包不含 `user_prompt_settings.txt`。~~ **已处理（2026-11-04）**：明文 seed 与根目录文件已删除，APK 重建验证不含该资源。
2. **高**：提供真实支付沙箱凭据，跑通 `pytest -m live` 并留存回调验签记录。
3. **中**：生产环境强制替换默认密钥（启动时校验）。
4. **中**：补齐 Web 安全响应头（CSP / nosniff / frame-options）。
5. **中**：依赖审计接入 CI 定时任务，启用 Dependabot。
6. **低**：越权矩阵自动化、日志轮转与保留策略、备份强加密。
