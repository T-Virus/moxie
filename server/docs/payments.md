# 支付接入说明（微信支付 v3 / 支付宝 / Stripe）

> **真实扣款必须由商户提供凭据**。本仓库在缺少凭据时使用 `fake`/`mock` provider 与本地测试夹具，
> 已覆盖验签、解密、幂等、退款、升级补差、对账的完整逻辑；拿到凭据后按本文「切换生产」清单逐项替换即可。
> 所有密钥只从环境变量/文件读取，**不写日志、不入库、不出现在 API 响应**。

## 1. 代码结构

```
app/payments/
├─ base.py       # PaymentProvider 抽象、金额换算、sha256/hmac、外部订单号
├─ mock.py       # 本地 mock（同步返回回调参数，HMAC 签名）
├─ fake.py       # 无凭据时的 fake provider（测试/演示）
├─ wechat.py     # 微信支付 v3：JSAPI/Native/H5、验签、AES-GCM、退款、对账单
├─ alipay.py     # 支付宝：电脑网站/当面付、RSA2 验签、退款、对账单
├─ stripe.py     # Stripe：Checkout、Webhook、Portal、退款、对账单
└─ __init__.py   # PROVIDERS 注册表 + get_provider(name, settings)
app/services/
├─ orders.py          # 订单状态机、退款、升级补差、权益回收
├─ payment_flow.py    # 回调幂等入库 → 金额校验 → 开通/退款
├─ reconcile.py       # 日对账差异分类
└─ subscription.py    # 订阅开通/续期/升级/到期
app/api/
├─ billing.py     # 下单/续费/回调（原始 body 验签）
└─ payments.py    # Portal、退款、发票、管理端对账/导出
```

统一订单号：`external_order_no = "MX" + 12 位订单 id`，渠道回调只用它关联本地订单。
订单状态机：

```
created → pending → paid → refunded
                  ↘ closed / failed
```

`paid` 之后仅允许 `refunded`；退款按 `refunds` 表逐笔记录，订单 `refunded_cents` 累加。

## 2. 凭据与环境变量

全部变量见 `server/.env.example`。常用：

| 渠道 | 必填 | 说明 |
|---|---|---|
| 微信 | `WECHAT_MCH_ID`、`WECHAT_APP_ID`、`WECHAT_API_V3_KEY`、`WECHAT_PRIVATE_KEY_PATH`（或 `_PEM`）、`WECHAT_CERT_SERIAL_NO`、`WECHAT_PLATFORM_CERT_PATH`（或 `_PEM`/`_SERIAL_NO`） | API v3 密钥 32 字节；商户私钥 apiclient_key.pem；平台证书用于回调验签 |
| 支付宝 | `ALIPAY_APP_ID`、`ALIPAY_PRIVATE_KEY_PATH`（或 `_PEM`）、`ALIPAY_PUBLIC_KEY_PATH`（或 `_PEM`）、`ALIPAY_SELLER_ID` | 应用私钥 + 支付宝公钥（RSA2）；`ALIPAY_GATEWAY` 沙箱改成 `https://openapi-sandbox.dl.alipaydev.com/gateway.do` |
| Stripe | `STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET` | 测试用 `sk_test_…` / `whsec_…`；有官方 `stripe` 包时优先使用官方验签 |

另有通用：

```dotenv
PAYMENTS_MOCK_ENABLED=false         # 仅 ENV=test/dev 可显式开启；生产开启即启动失败
PAYMENTS_FAKE_ENABLED=false         # 同上
MOCK_PAYMENT_SECRET=                # 启用 mock/fake 时必填（回调 HMAC 密钥）
WEBHOOK_TOLERANCE_SECONDS=300       # 回调时间戳容差
PAYMENT_WEBHOOK_IP_ALLOWLIST=       # 可选：逗号分隔 IP；留空只依赖签名
PAYMENT_RECONCILE_PROVIDERS=wechat,alipay,stripe
```

> `*_PEM` 与 `*_PATH` 二选一；PEM 多行值在 `.env` 中用双引号包裹并把换行写成 `\n`。

## 3. 回调 URL

统一入口：

```
POST /v1/webhooks/wechat
POST /v1/webhooks/alipay
POST /v1/webhooks/stripe
POST /v1/webhooks/mock     # 本地开发
```

- 端点先 `await request.body()` 读取**原始字节**，再做验签/解密；不会先 JSON 解析破坏签名。
- 成功返回 `{"ok": true, "duplicate": bool, "order_status": ...}`。
- 失败返回规范错误 `{"error":{"code","message","request_id"}}`，并写审计 `payment.webhook_rejected`
  （渠道、错误码、是否可重试、回调原文 sha256 摘要，不含敏感明文）。
- 幂等键 `(provider, event_id)`；重复投递返回 `duplicate=true`，不重复开通权益。

本地调试（ngrok / cpolar / frp 任选）：

```powershell
# 1) 本机启动 API
uvicorn app.main:app --port 8000
# 2) 内网穿透
ngrok http 8000
# 3) 把 https://xxxx.ngrok-free.app 填到渠道回调配置
#    微信：商户平台 → 产品中心 → 开发配置 → 支付回调 URL
#    支付宝：应用网关/异步通知地址
#    Stripe：stripe listen --forward-to localhost:8000/v1/webhooks/stripe
```

Stripe 本地推荐：

```powershell
stripe listen --forward-to localhost:8000/v1/webhooks/stripe
# 把输出里的 whsec_... 填入 STRIPE_WEBHOOK_SECRET
```

## 4. 各渠道要点

### 微信支付 v3

- 下单：`POST /v3/pay/transactions/jsapi|native|h5`，签名串
  `METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY\n`，头 `Authorization: WECHATPAY2-SHA256-RSA2048 ...`。
- 回调验签串：`timestamp\nnonce\n原始body\n`，RSA-SHA256 + 平台证书公钥；时间戳超过
  `WEBHOOK_TOLERANCE_SECONDS` 拒绝。
- 资源解密：`AEAD_AES_256_GCM`，key=`WECHAT_API_V3_KEY`，附加数据 `associated_data`，nonce 12 字节。
- 金额单位：**分**；校验 `mchid`、`appid`、`amount.total == order.amount_cents`。
- 退款：`POST /v3/refund/domestic/refunds`；退款回调同路径验签解密。
- 对账单：`GET /v3/bill/tradebill?bill_date=YYYY-MM-DD&bill_type=ALL`，返回下载链接后再 GET CSV，
  `parse_tradebill()` 解析为 `{external_order_no, provider_txn_id, amount_cents, status}`。

### 支付宝

- 下单：电脑网站 `alipay.trade.page.pay`、当面付 `alipay.trade.precreate`。
- 签名/验签：RSA2（SHA256withRSA），参数按 key 升序、剔除空值与 `sign`，`k=v&` 拼接。
- 异步通知：表单参数验签；校验 `app_id`、`seller_id`、`total_amount`（**元**）、`notify_time` 容差。
- 退款：`alipay.trade.refund` / `alipay.trade.fastpay.refund.query`。
- 对账单：`alipay.data.dataservice.bill.downloadurl.query`，`parse_alipay_bill()` 解析。

### Stripe

- Checkout Session（`mode=subscription` 或 `payment`），成功后回跳 `/v1/payments/stripe/success`。
- Webhook：`Stripe-Signature: t=...,v1=...`，`HMAC-SHA256(secret, "t.raw")`，容差 300s；
  安装官方 `stripe` 包时使用 `stripe.Webhook.construct_event`。
- 事件：`checkout.session.completed` / `invoice.paid` / `charge.refunded`。
- Customer Portal：`POST /v1/subscriptions/{id}/portal` 返回一次性 URL。
- 退款：`POST /v1/refunds`，带 `Idempotency-Key`。
- 对账单：`GET /v1/balance_transactions?created[gte]=…&created[lt]=…`，按 `source` 关联订单号。

## 5. 本地无凭据验证（fake 全流程）

```powershell
$env:PAYMENTS_FAKE_ENABLED="true"
$env:MOCK_PAYMENT_SECRET="local-secret"
python -m pytest tests/test_payments.py -q
```

测试覆盖（8 passed + 3 live skipped）：

1. 微信回调验签成功 / 篡改失败 / 重复投递；
2. 支付宝通知验签、金额不符拒绝、重复/篡改；
3. Stripe 签名成功 / 过期 / 重复 / 篡改；
4. fake：下单 → 回调 → 权益开通 → 续费 → 退款（幂等）→ 权益回收；
5. 升级按比例补差、降级拒绝；
6. 对账差异分类 + 管理端查询/CSV 导出；
7. 发票申请 + 管理端开票；
8. 未配置渠道返回 `501 provider_not_configured`。

`live` 用例用 `pytest -m live` 单独跑，缺凭据自动 skip 并给出原因：

```powershell
python -m pytest -m live -q
```

## 6. 切换生产清单

1. `PAYMENTS_FAKE_ENABLED=false`；
2. 填入三家中实际启用的渠道凭据（未启用的留空即可，接口返回 `501`）；
3. 回调域名必须是 **HTTPS 公网地址**，并在渠道后台配置
   `https://<domain>/v1/webhooks/wechat|alipay|stripe`；
4. 微信上传 API 证书、下载平台证书；支付宝配置 RSA2 公钥；Stripe 配置 webhook endpoint 与 `whsec`；
5. 执行迁移：`alembic upgrade head`（新增 `refunds`、`reconcile_reports`、`invoice_requests` 及订单列）；
6. 先跑一笔最小金额（如 0.01 元）验证：下单 → 回调 → 订单 `paid` → 权益开通；
7. 再验证退款：管理端 `POST /v1/admin/orders/{id}/refund` 或渠道后台发起 → 退款回调 → 权益回收；
8. 次日验证对账：`POST /v1/admin/payments/reconcile` 或 scheduler 自动执行，检查差异报告；
9. 打开 `SCHEDULER_ENABLED=true` 或独立进程 `python -m app.scheduler`。

## 7. 退款与发票

- 退款必须先有 `paid` 订单；`POST /v1/admin/orders/{id}/refund` 传 `amount_cents`（缺省按报价全额）、
  `reason`、`idempotency_key`（必填，重放返回同一退款记录）。
- 报价：`GET /v1/admin/orders/{id}/refund-quote` 按已用量/剩余时长估算（额度包按未使用额度比例）。
- 审批：`POST /v1/admin/refunds/{id}/approve`（body 可空，已成功幂等返回 `duplicate=true`）、
  `POST /v1/admin/refunds/{id}/reject`（备注必填，缺失 422 `refund_note_required`）。
- 退款成功后 `orders.refunded_cents` 累加；全额退款会把订阅置为 `refunded` 并回收权益
  （额度包吊销/按比例缩减、升级回退上一套餐、部分退款按比例缩短当前周期）。
- 发票：用户 `POST /v1/orders/{id}/invoice` 提交抬头/税号/邮箱；管理端
  `GET /v1/admin/invoices`、`POST /v1/admin/invoices/{id}` 状态流转 `requested → issued → voided`
  （兼容旧叫法 `rejected`，服务端归一为 `voided`）。**不做自动开票**。

## 8. 对账

- 任务：`python -m app.scheduler --once`（每日自动拉取前一日账单），或管理端手动触发。
- 差异分类：`amount_mismatch` / `channel_only` / `local_only` / `duplicate_payment`。
- 结果写 `reconcile_reports`（唯一 `provider + biz_date`），并写审计 `payment.reconcile`；
  单渠道失败写 `payment.reconcile.failed`，不影响其它渠道。
- 查询/导出：
  - `GET /v1/admin/payments/reconcile?provider=&biz_date=`
  - `GET /v1/admin/payments/reconcile/export?provider=&biz_date=`（CSV）

## 9. 常见失败码

| code | 场景 | 处理 |
|---|---|---|
| `provider_not_configured` | 渠道凭据缺失 | 补齐 `.env` 后重启 |
| `invalid_signature` | 验签失败/平台证书不匹配 | 检查平台证书序列号、API v3 key、原始 body 是否被代理改写 |
| `timestamp_expired` | 回调时间戳超出容差 | 校准服务器时间；代理不要缓存回调 |
| `amount_mismatch` | 回调金额与订单不一致 | 检查币种/单位（微信分、支付宝元）；不要在前端改金额 |
| `unknown_order` | 回调里的 `external_order_no` 本地不存在 | 检查下单渠道与回调渠道是否一致 |
| `webhook_source_rejected` | 来源 IP 不在白名单 | 调整 `PAYMENT_WEBHOOK_IP_ALLOWLIST` 或留空 |
| `provider_error` | 渠道 REST 返回非 2xx | 查看审计里的 `digest` 与渠道请求日志（不含密钥） |
| `refund_amount_invalid` | 退款金额为 0/超过可退金额 | 用订单详情核对 `amount_cents - refunded_cents` |

## 10. 安全约束

- 私钥/API key 只读环境变量或文件，日志字段名（`authorization`、`api_key`、`token`、`secret`）自动脱敏；
- 回调审计只保存 sha256 摘要，不存原始回调 body；
- API 响应不返回私钥、平台证书明文或渠道密钥；
- Stripe/微信/支付宝回调失败均返回统一错误码与 `request_id`，便于按日志追查。
