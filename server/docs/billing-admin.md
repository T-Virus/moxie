# 管理端 API（admin / support）

管理端 `admin/` 只需要 `/v1` 前缀 + Bearer Token；服务端已内置 CORS 白名单（默认
`http://127.0.0.1:5180`、`http://localhost:5180`），跨域部署时把前端域名加入
`CORS_ALLOW_ORIGINS` 即可。本文件是服务端实现与前端约定的对齐说明。

## 0. CORS

| 配置 | 默认值 | 说明 |
|---|---|---|
| `CORS_ALLOW_ORIGINS` | `http://127.0.0.1:5180,http://localhost:5180` | 逗号分隔的**精确来源**；禁止 `*`（启动失败） |
| `CORS_ALLOW_METHODS` | `GET,POST,PATCH,DELETE,OPTIONS` | 管理端所需方法 |
| `CORS_ALLOW_HEADERS` | `Authorization,Content-Type,Idempotency-Key,X-Request-Id,X-Rights-Confirmed,X-BYOK-Key` | 预检放行的请求头 |
| `CORS_MAX_AGE_SECONDS` | `600` | 预检缓存 |

- 允许 `credentials`（Bearer Token），因为来源是明确白名单，不使用 `*` 搭配凭证；
- 响应暴露 `X-Request-Id` 便于前端排障；
- 未知来源预检返回 400 且不带 `Access-Control-Allow-Origin`。

## 1. 权限模型

| 角色 | 读接口 | 写接口 |
|---|---|---|
| `admin` | 允许 | 允许 |
| `support` | 允许（`require_staff`） | **拒绝**（`require_admin` → 403 `admin_required`） |
| 其他角色 | 403 `staff_required` | 403 |

所有写操作都写 `audit_logs`（`actor_id`、`action`、`target_type/target_id`、`meta`）。

## 2. 接口清单（13 组）

分页统一 `{items, total, page, page_size}`（部分兼容接口只返回 `items`）；列表默认 `page_size=50`，上限 200。

### 套餐

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/plans` | 公开 | 仅返回 `active=true` 的套餐，按 `price_month_cents` **升序** |
| GET | `/v1/admin/plans` | staff | 返回全部套餐（上架优先、价格升序）；每项含 `active` 与 `status`（`上架` / `已下架`）及 `entitlements` |
| POST | `/v1/subscriptions` | 登录 | 只允许当前 `active=true` 的套餐；引用已下架套餐返回 `409 plan_unavailable`，不存在返回 `404 plan_not_found` |

套餐矩阵（价格以「分」存储，币种 `CNY`；年付按十个月折算）：

| code | 名称 | 月付（分 / 元） | 年付（分 / 元） | `books_month` | `adapt_chapters` | `managed_chars` | `concurrency` | `review_month` | `seats` | `storage_gb` |
|---|---|---|---|---|---|---|---|---|---|---|
| `experience` | 体验版 | 990 / ¥9.9 | 9900 / ¥99 | 1 | 20 | 50,000 | 1 | 1 | 1 | 2 |
| `creator` | 创作版 | 2990 / ¥29.9 | 29900 / ¥299 | 5 | 120 | 500,000 | 2 | 5 | 1 | 5 |
| `professional` | 专业版 | 6990 / ¥69.9 | 69900 / ¥699 | 15 | 400 | 2,000,000 | 4 | 15 | 3 | 20 |

**下架规则**

- 只保留上述三档；`studio_managed` 等工作室版及任何非三档套餐一律**下架**（`plans.active=false`），
  不删除 `plans` / `subscriptions` / `orders` 行，避免历史订阅与订单失去外键。
- `server/app/seed.py::ensure_plans` 幂等：按 `code` 新增或就地更新名称、价格、币种、权益与
  `active=true`；不在种子清单内的套餐统一 `active=false`；重复执行结果一致，不会出现两套价格。
- 已下架套餐：`GET /v1/plans` 不可见、不可新下单；管理端列表可见并标注「已下架」。
- **存量订阅不受影响**：订阅继续使用原 `plan_id` 的权益、续费提醒与状态机；查询
  `GET /v1/subscriptions/current` 仍返回原套餐 code，只是该套餐不再对外出售。

### 用户

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/admin/users?q=&status=&role=&page=&page_size=` | staff | email/phone 模糊搜索；`items` 含 `subscription`、`devices_count` |
| GET | `/v1/admin/users/{id}` | staff | `account / devices / subscription / recent_tasks / usage` 聚合 |
| POST | `/v1/admin/users/{id}/ban` | admin | body `{reason}`（≥2 字符）；吊销全部 RefreshSession；审计 `user.ban` |
| POST | `/v1/admin/users/{id}/unban` | admin | body `{reason}`；审计 `user.unban` |
| POST | `/v1/admin/users/{id}/status` | admin | 兼容旧前端，`active/banned`；审计 `user.ban`/`user.unban` |

- 封禁管理员返回 409 `cannot_ban_admin`；用户不存在 404 `user_not_found`。
- 封禁后：`get_auth` 校验 `account.status != "active"` → 401 `account_disabled`，因此登录态立即失效、任务提交/查询均被拒。

### 订阅与额度

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/admin/subscriptions?q=&status=&page=&page_size=` | staff | `q` 按账号邮箱过滤 |
| PATCH | `/v1/admin/subscriptions/{id}` | admin | `plan_code / current_end_at / extend_days / status / note`（note 必填）；审计 `subscription.adjust` |
| POST | `/v1/admin/subscriptions/{id}/adjust` | admin | 同上（兼容别名） |
| POST | `/v1/admin/accounts/{id}/quota-adjustments` | admin | `{metric, quantity, reason, idempotency_key?}`；写 `usage_events.meta.manual=true` 并同步 `usage_aggregates.used`；审计 `quota.adjust` |
| GET | `/v1/admin/accounts/{id}/quota-adjustments?limit=` | staff | 手工调整历史（`reason/actor_id/before/after`） |

- 额度调整可为负数（下限 0）；`Idempotency-Key` 或 body `idempotency_key` 重复时返回 `duplicate=true`，不重复扣加。
- 订阅不存在 404 `subscription_not_found`；额度调整要立即影响 `GET /v1/entitlements` 的 `used/remaining`。

### 订单与退款

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/admin/orders?q=&status=&provider=&page=&page_size=` | staff | `q` 匹配订单号/外部单号 |
| GET | `/v1/admin/orders/{id}` | staff | `{order, refunds, invoice?, audit?}`；不存在 404 `order_not_found` |
| POST | `/v1/admin/refunds/{id}/approve` | admin | body 可空 `{note}`；已成功幂等返回 `duplicate=true`；审计 `order.refund.approve` |
| POST | `/v1/admin/refunds/{id}/reject` | admin | `note`/`reason` 必填 ≥2 字符；缺失 422 `refund_note_required`；已成功 409 `refund_already_succeeded`；审计 `order.refund.reject` |
| GET | `/v1/admin/refunds?order_id=` | staff | 返回 `{items: [...], refunds: [...]}`（`refunds` 为旧前端别名，保留一段时间） |
| GET | `/v1/admin/orders/{id}/refund-quote` | staff | 按已用量/剩余时长估算可退金额 |
| POST | `/v1/admin/orders/{id}/refund` | admin | 直接退款（可选 `amount_cents`，默认全退） |

### 任务看板

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/admin/tasks/dashboard` | staff | `queue_depth / running_count / failed_count / retryable_count / generated_at / running / failed / by_status` |
| POST | `/v1/admin/tasks/{id}/retry` | admin | 仅 `failed/canceled`；重置失败/运行中的步骤、清零错误；审计 `task.retry`；否则 409 `task_not_retryable` |
| GET | `/v1/admin/tasks?status=&account_id=&limit=` | staff | 最近任务概览 |

`retryable_count` 口径为 `failed` 且 `attempts < 3`。

### 告警与通知

| 方法 | 路径 | 权限 | 说明 / 审计 |
|---|---|---|---|
| GET | `/v1/admin/alerts?page=&page_size=` | staff | `usage_anomaly` 通知分页 + 24h 内通知/回调失败计数 |
| GET | `/v1/admin/notifications?status=&channel=&page=&page_size=` | staff | 发送记录分页，`template` 字段即 category |
| POST | `/v1/admin/notifications/{id}/retry` | admin | 仅 `failed/skipped`；重置次数并回 `queued`；审计 `notification.retry`；否则 409 `delivery_not_retryable` |
| POST | `/v1/admin/notifications` | admin | 给账号发 `admin_message`（可选渠道 inapp/email/sms） |
| GET | `/v1/admin/notification-deliveries?status=&channel=&limit=` | staff | 兼容旧前端的简版列表 |

### 审计与运维

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/v1/admin/audit-logs?page=&page_size=&account_id=&actor_id=&action=&target_type=&target_id=&start_at=&end_at=&limit=` | staff | 服务端分页 + 过滤；`account_id` 与 `actor_id` 均按操作人过滤；`limit` 兼容前端旧参数 |
| POST | `/v1/admin/subscriptions/expire-due` | admin | 到期清扫；审计 `subscription.expire_due` |
| GET | `/v1/admin/reconcile-reports` | staff | 对账报告列表（兼容旧前端） |
| GET | `/v1/admin/invoices?status=` | staff | `status=rejected` 映射为 `voided`（同时匹配历史 `rejected` 行）；返回 `{items, invoices}`，每项含 `status=voided` 与 `legacy_status=rejected` |
| POST | `/v1/admin/invoices/{id}` | admin | `{status: requested/issued/voided（rejected 归一为 voided）, note}`；审计 `invoice.update` |
| GET | `/v1/admin/payments/reconcile`、`POST .../reconcile`、`GET .../reconcile/export` | staff / admin | 对账查询、生成、CSV 导出 |
| GET | `/v1/admin/renewal-reminders` | staff | 续费提醒（概览探测用） |

## 3. 错误码

| HTTP | code | 场景 |
|---|---|---|
| 403 | `admin_required` | support/普通用户调用写接口 |
| 403 | `staff_required` | 非 admin/support 调用读接口 |
| 404 | `user_not_found` / `subscription_not_found` / `order_not_found` / `refund_not_found` / `task_not_found` / `invoice_not_found` / `delivery_not_found` / `plan_not_found` | 资源不存在 |
| 409 | `cannot_ban_admin` / `task_not_retryable` / `delivery_not_retryable` / `refund_already_succeeded` / `plan_unavailable` | 状态冲突（`plan_unavailable`：下单引用了已下架套餐） |
| 422 | `refund_note_required` | 驳回备注缺失 |

## 4. 与前端仍不一致 / 需注意的点

1. **审计日志前端仍拉 `limit` 并做本地过滤**：服务端已支持完整分页与过滤，但管理端页面未切换到 `page/page_size`；`limit` 已兼容，结果集仍受 200 上限约束。
2. **发票作废**：前端发送 `status=rejected`，服务端归一为 `voided`；列表响应同时给出
   `status=voided` 与 `legacy_status=rejected`，查询 `status=rejected` 也会同时匹配历史 `rejected` 与新的 `voided` 行。
3. **列表数组命名**：退款列表已统一返回 `items`，并保留 `refunds` 别名；发票列表返回 `items` +
   `invoices` 别名。前端可优先读取 `items`。
4. **support 的告警/通知菜单**：前端对 support 隐藏「对账」「告警与通知」，但服务端 `GET /alerts`、
   `GET /notifications` 实际允许 support 只读；属于前端展示策略差异，不构成 403。
5. **CORS**：服务端已支持白名单，不再需要同域反代；跨域部署只需配置 `CORS_ALLOW_ORIGINS`。

## 5. 测试

`tests/test_admin_ext.py`（10 条）+ `tests/test_cors.py`（3 条）+ 既有支付/审计用例覆盖：越权 403、
support 只读、封禁后登录与任务提交被拒、额度调整生效、退款审批幂等、审计分页过滤、
任务重试与通知重试、发票 legacy 状态、退款/发票列表别名、CORS 预检与未知来源拒绝。
