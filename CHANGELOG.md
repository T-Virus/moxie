# 更新日志

本项目使用语义化版本（MAJOR.MINOR.PATCH），Release Tag 形如 `v0.1.0`。

## Unreleased

### 工程与发布
- CI 增加最小权限、作业超时、后端覆盖率门禁、client/admin 构建产物归档与失败汇总通知。
- 新增 tag 触发的 release workflow：打包前后端资产、生成 SPDX SBOM、cosign 签名与构建来源证明。

### 安全与运维
- 管理员初始化改为白名单幂等提升已注册账号，不自动创建弱口令管理员，写审计日志。
- 反代场景统一 `TRUST_PROXY` 与 nginx `X-Forwarded-For` 口径；nginx 用 `$remote_addr` 覆盖客户端伪造头。
- 请求体限制前置到载荷解密层，阻断 chunked body 绕过；新增 413 回归测试。

### 用户数据权利
- 新增 `GET /v1/me/export`：导出账号、任务、运行、订单、同意留痕等结构化数据与对象存储内容/下载链接，密码与令牌哈希脱敏。
- 新增 `POST /v1/me/delete`：密码 + 显式确认串提交注销申请，立即撤销全部会话，宽限期后由 scheduler 清除。
- 新增管理端注销申请列表、撤销、立即清除接口；用户注销与管理端硬删除共用同一套级联与对象存储清理逻辑。

### 端到端追踪与稳定性
- 前端生成会话级 trace-id，每次请求写入 `X-Trace-Id` 与 W3C `Traceparent`；服务端解析、回写并落到结构化日志，浏览器异常上报同步带 `trace_id`。
- client HTTP 层新增网络错误 / 502 / 503 / 504 重试：指数退避、25% 抖动、`Retry-After` 优先，仅对幂等请求或带 `Idempotency-Key` 的请求自动重试。
- 新增 `ops/monitoring/alerts.yml` 与试点期 `SLO.md`，覆盖 API 可用性、队列、任务失败率、回调、成本、额度拒绝与认证限流。

### BYOK
- 用户端新增会话级自有模型 Key 设置入口：仅存 `sessionStorage`，不写 `localStorage`、不进业务参数、不落日志；模型消费请求通过 `X-BYOK-Key` 请求头注入。
