# 通知通道（站内信 / 邮件 / 短信）

统一出口 `app/services/notifications.py`：先写站内信（`notifications`），再按渠道创建
`notification_deliveries` 并投递。邮件走 SMTP（可关），短信为 no-op 适配位（可关）。

## 1. 模板与触发点

| category | 触发 | 触发方 |
|---|---|---|
| `subscription_renewal_reminder` | 到期前 `SUBSCRIPTION_REMINDER_DAYS` | scheduler |
| `subscription_expired` | 订阅过期 | scheduler |
| `payment_succeeded` / `payment_failed` | 支付回调处理 | `services/payment_flow` |
| `quota_insufficient` | 额度拒绝（402） | `services/quota` |
| `usage_anomaly` | 日用量超阈值 | scheduler |
| `credit_pack_expiring` | 额度包 7 天内到期 | scheduler |
| `admin_message` | 管理员主动发送 | `POST /v1/admin/notifications` |

模板只含标题与正文，上下文变量由调用方传入，服务端渲染；不包含提示词或密钥。

## 2. 幂等与重试

- 站内信唯一键：`(account_id, dedupe_key)`；
- 投递唯一键：`(channel, dedupe_key)`，其中 `dedupe_key = f"{account_id}:{业务键}:{channel}"`；
- 发送失败写入 `status=failed`、`last_error`、`next_retry_at`（`NOTIFICATION_RETRY_BACKOFF_SECONDS` 递增）；
- `scheduler.retry_notifications` 每轮调用 `retry_deliveries`：成功或达到 `NOTIFICATION_MAX_ATTEMPTS` 后不再重试；
- 管理员可手动重试：`POST /v1/admin/notifications/{id}/retry`（仅 `failed/skipped`，重置计数并回到 `queued`）。

## 3. 渠道行为

| 渠道 | 配置 | 行为 |
|---|---|---|
| `inapp` | `NOTIFICATION_INAPP_ENABLED=true` | 仅写库，客户端拉取 |
| `email` | `NOTIFICATION_EMAIL_ENABLED`、`SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS` | SMTP 直连；未配置 `SMTP_HOST` 记 `skipped`（`reason=smtp_not_configured`），不阻塞业务 |
| `sms` | `NOTIFICATION_SMS_ENABLED`、`SMS_PROVIDER=noop` | 当前固定 no-op：记 `skipped`，接口与重试链路已就绪 |

默认：站内信开启、邮件/短信关闭（`notification_email_enabled=false`、`notification_sms_enabled=false`）。
`NOTIFICATIONS_ENABLED=false` 时 `emit` 直接返回，不落库。

## 4. 接口

用户侧：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/notifications?limit=&unread_only=` | 我的站内信 |
| POST | `/v1/notifications/{id}/read` | 标记已读（仅本人） |
| POST | `/v1/notifications/read-all` | 全部已读 |

管理侧（`support` 可读、`admin` 可写）：

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/v1/admin/notifications?status=&channel=&page=&page_size=` | staff | 发送记录分页，`template` 即 category |
| POST | `/v1/admin/notifications/{id}/retry` | admin | 重投失败/跳过记录，写审计 `notification.retry` |
| POST | `/v1/admin/notifications` | admin | 给指定账号发 `admin_message` |
| GET | `/v1/admin/notification-deliveries` | staff | 兼容旧前端的简版列表 |

分页返回统一 `{items, total, page, page_size}`。

## 5. 配置示例

```dotenv
NOTIFICATIONS_ENABLED=true
NOTIFICATION_INAPP_ENABLED=true
NOTIFICATION_EMAIL_ENABLED=false
NOTIFICATION_SMS_ENABLED=false
NOTIFICATION_MAX_ATTEMPTS=3
NOTIFICATION_RETRY_BACKOFF_SECONDS=300
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=no-reply@example.com
SMTP_USE_TLS=true
SMS_PROVIDER=noop
```

## 6. 测试

`tests/test_notifications.py`（5 条）：幂等 emit、站内信已读、邮件未配置降级为 skipped、
重试次数与退避、管理员查询/重试。
