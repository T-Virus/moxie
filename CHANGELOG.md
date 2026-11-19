# 更新日志

本项目使用语义化版本（MAJOR.MINOR.PATCH），Release Tag 形如 `v0.1.0`。

## Unreleased

### 在线主链与质量门禁
- 新增 client 在线版 Playwright E2E（注册→订阅→生成→导出→注销→管理端清除），纳入 CI `online-e2e` job；离线 `e2e-desktop` 保留为存量 job。
- 服务端 `/metrics` 新增 HTTP 延迟直方图，暴露 P95/P99；管理端概览新增性能卡片，告警补延迟与错误预算 burn-rate 规则。
- 新增租户级（账号维度）限流，覆盖网关、上传、运行与任务四个入口。

### 业务支撑
- 新增支付-订单-额度-发票四账对账接口与管理端视图。
- 管理端新增注销申请列表 / 撤销 / 立即清除页面；用户端新增账户设置页（`/account`），按「订阅与额度 / 自有模型 / 账号安全 / 订单与退款 / 数据与导出 / 注销账号」六个 tab 分区（支持 `?tab=` 深链），当前订阅/本月额度与自有模型 Key 从订阅页迁入，修改密码迁入安全 tab，支持个人数据导出与账号注销二次确认；顶栏改为用户名下拉菜单（账户设置 / 退出）。
- 用户端新增自助退款申请：账户设置页展示订单与退款记录，按已用量折算可退金额，提交后进入 pending 由管理端审核（不自动调渠道）；服务端新增 `GET /orders/{id}/refund-quote` 与 `POST /orders/{id}/refund-request`。
- BYOK（自有模型 Key）支持自选模型：账户设置「自有模型」tab 可填模型名与 OpenAI 兼容网关地址（含 OpenAI/DeepSeek/通义快捷选项），随 `X-BYOK-Model`/`X-BYOK-Base-URL` 下发；服务端 `resolve_step_model` 集中覆盖 model/base_url（带 SSRF 校验，兼容旧裸 Key），任务与网关链均生效。
- 新增任务死信队列与管理端单条 / 批量重放中心，操作写审计。
- 修复管理端「备份管理」在 PostgreSQL 环境完全不可用：镜像补装 `postgresql-client`（pg_dump/pg_restore），并把 SQLAlchemy 的 `postgresql+psycopg://` URI 转成 pg 工具识别的标准 libpq URI；备份文件通过 `backupdata` 卷持久化（api/scheduler 共用），容器重建不丢备份。
- 启用定时备份：`.env` 打开 `BACKUP_SCHEDULE_ENABLED`（间隔 720 分钟），重建独立 scheduler 镜像使 pg 工具与新代码生效；修复 `backupdata` 卷首次挂载被创建为 root:root 导致 appuser 无法写备份的权限问题（Dockerfile 预建 `/app/backups`）；定时备份产物 trigger=scheduled，api/scheduler 共享可见。
- 管理端「备份管理」新增可视化「定时备份策略」：开关、备份间隔（预设 6/12 小时/每天/每周 + 自定义 5–10080 分钟）、通知邮箱（逗号分隔、白名单校验去重）、保留份数，写库热改（`operational_settings` + TTL 缓存，DB 覆盖环境变量）并写审计；修复 scheduler 传 Database 而非 Session 导致后台配置静默降级到环境变量的 bug。
- 新增运行体检报告接口与客户端可读报告页；报告页重做卡片化视觉：评分环 + 关键指标条 + 风险分级 / 建议 / 一致性问题等分区卡片。
- 热门 / 参考 / 自定义三种 Agent 流程共用 `cover_plan` 产出，完成后自动按方案出图并写入作品封面；用户端作品列表直接展示真实封面缩略图，作品信息页保留手动重生成 / 上传 / 删除入口（`AGENT_COVER_AUTO_GENERATE` 可关闭自动出图）。
- 补齐法务与 SLA 交付包（用户协议、隐私政策、AIGC 标识、授权链声明、退款/发票、子处理者清单、DPA、试点 SLA）；法律文本版本升级至 `2026-11-18` 并加三端版本一致性硬校验。

### 配置与文档
- 新增 dev/staging/prod 环境配置治理文档（配置基线、敏感项清单、变更审计、回滚）。
- 忘记密码 / 重置密码页面重做样式；首页移除新手引导区块；用户端导航移除技能入口（能力保留）。
- 管理端密码重置链路独立于用户端：重置请求带 `channel=admin`，服务端按来源用 `APP_ADMIN_BASE_URL` 拼 `/admin/#/reset-password` 链接（用户端仍是 history 路由 `/reset-password`），admin 补齐重置页与 public 路由，管理员无需跳到用户端即可完成重置。

### 工程与发布
- CI 增加最小权限、作业超时、后端覆盖率门禁、client/admin 构建产物归档与失败汇总通知。
- 新增 tag 触发的 release workflow：打包前后端资产、生成 SPDX SBOM、cosign 签名与构建来源证明。

### 安全与运维
- 管理员初始化改为白名单幂等提升已注册账号，不自动创建弱口令管理员，写审计日志；初始管理员邮箱白名单设为 `18021524721@163.com`。
- 用户端与管理端账号硬隔离：登录请求带 `source=client|admin`，服务端在密码校验后按角色拒绝跨端登录（普通用户不能登录管理后台、admin/support 不能登录用户端），拒绝时写 `account.login_portal_denied` 审计且不签发 token；两端前端分别携带来源，管理端保留前端角色检查作二次防护。
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
