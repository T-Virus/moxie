# 合规与安全闸门（Legal Gates）

本文件列出服务端**硬性闸门**：mock 支付、License 私钥、云端版权确认、回调验签。闸门失败时
返回明确错误码或启动失败，不允许降级静默通过。

## 1. mock / fake 支付

| 闸门 | 行为 | 错误 |
|---|---|---|
| 默认值 | `PAYMENTS_MOCK_ENABLED=false`、`PAYMENTS_FAKE_ENABLED=false` | — |
| 环境限制 | 仅 `ENV=test` / `ENV=dev` 允许注册与调用 mock/fake | 403 `provider_not_allowed_in_env` |
| 未显式开启 | `get_provider("mock"/"fake")` 直接拒绝 | 403 `mock_payment_disabled` / `fake_payment_disabled` |
| 缺少签名密钥 | `MOCK_PAYMENT_SECRET` 为空时拒绝注册；回调也再次校验 | 403 `mock_secret_missing` |
| 生产启动 | `ENV=prod/production` 且 mock/fake 开启 → 应用构造即失败 | `RuntimeError`（启动失败） |

回调链接（`POST /v1/webhooks/{provider}`）：

1. 先读原始字节，禁止重新序列化（否则签名失效）；
2. 可选 `PAYMENT_WEBHOOK_IP_ALLOWLIST`：不在白名单 → 403 `webhook_source_rejected` 并审计；
3. 交由渠道 `parse_webhook` 验签/解密：mock 用 `HMAC-SHA256(event_id:order_id:amount_cents)`，
   微信 v3 使用平台证书验签 + AES-GCM 解密，支付宝 RSA2，Stripe `Stripe-Signature` v1；
4. 只有验签通过的事件才进入 `payment_flow.handle_event`；
5. **唯一开通路径**：`handle_event(status=paid)` → `activate_paid_order`。代码中不存在
   “回调不验签直接开通”的旁路；后台手工退款/额度调整走独立审计接口，不改变支付单状态来源。

测试证据：

- `test_mock_provider_rejected_in_production`
- `test_mock_disabled_by_default_even_in_test_env`
- `test_mock_secret_missing_rejects_provider_and_webhook`
- `test_production_mock_checkout_returns_4xx_and_no_subscription`（401/403 且 `subscriptions/current` 仍 404）
- `test_bad_webhook_signature_is_rejected`（伪造签名 400 `invalid_signature`）

## 2. License 私钥

- 生产启动（`ENV=prod/production`）必须配置 `LICENSE_PRIVATE_KEY_PEM`，否则 `create_app` 抛
  `RuntimeError`；多 worker 部署**禁止**自动生成临时密钥。
- 非生产环境也必须显式开启 `LICENSE_ALLOW_EPHEMERAL_KEY=true` 才允许进程内临时密钥；
  默认 `false`，缺失私钥直接 `ValueError`（启动/签发失败）。
- 私钥只存服务端，客户端内置公钥。

生成命令：

```bash
openssl genpkey -algorithm ed25519 -out license_private.pem
python -c "from app.security import LicenseSigner; print(LicenseSigner.generate_pem())"
```

```dotenv
LICENSE_PRIVATE_KEY_PEM="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
LICENSE_KEY_ID=moxie-license-1
LICENSE_ALLOW_EPHEMERAL_KEY=false
```

测试证据：`test_production_startup_requires_license_key`、`test_ephemeral_license_key_must_be_opted_in`、
`tests/test_license.py` 中的签发/校验用例。

## 3. 云端版权确认（拆解 / 改编）

- 开关 `LEGAL_GATE_ENABLED=true`（默认开）；
- 创建 `type=decompose|adapt` 任务必须显式声明：
  - body `params.rights_confirmed=true`，或请求头 `X-Rights-Confirmed: true`
  - 服务端自动补 `params.aigc_label=true` 与 `rights_confirmed_at`
- 缺失时返回 **422 `rights_confirmation_required`**，任务不会创建、不会入队、不会预占额度；
- 审计 `task.create` 的 `meta.rights_confirmed` 记录确认结果，任务参数随任务落库，供后续审查。
- 桌面端 UI 后续补齐；当前服务端闸门已生效。

测试证据：`test_rights_confirmation_gate`、`test_rights_confirmation_header_also_accepted`。

## 4. 环境变量速查

```dotenv
ENV=prod
PAYMENTS_MOCK_ENABLED=false
PAYMENTS_FAKE_ENABLED=false
MOCK_PAYMENT_SECRET=
PAYMENT_WEBHOOK_IP_ALLOWLIST=
LICENSE_PRIVATE_KEY_PEM=
LICENSE_ALLOW_EPHEMERAL_KEY=false
LEGAL_GATE_ENABLED=true
```

> 生产部署检查：`ENV=prod` + mock/fake 关闭 + 私钥已配置 + `LEGAL_GATE_ENABLED=true`。
> 任一不满足，应用应在启动阶段失败，而不是带病运行。
