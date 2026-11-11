# 额度包（Credit Packs）

一次性额度包与套餐额度并存：**套餐优先扣减，不足部分再扣额度包**；额度包 12 个月有效、不随月度清零。

## 1. 数据模型

| 表 | 说明 |
|---|---|
| `credit_packs` | 可售额度包：`code / metric / quantity / price_cents / validity_days / active` |
| `credit_grants` | 发放账本：一单一条，`quantity_granted / used / reserved / status / valid_from / expires_at`；`(account_id, idempotency_key)` 与 `order_id` 唯一 |
| `orders.pack_id` | 额度包订单；此时 `plan_id` 为空 |
| `tasks.reserved_plan_quantity` / `reserved_pack_items` | 任务预占拆分（套餐部分 + 各额度包明细），用于断点/取消恢复 |

内置包（`app/seed.py`，启动时幂等写入）：

| code | metric | quantity | 价格 |
|---|---|---|---|
| `books_5` | `books_month` | 5 | 9900 分 |
| `adapt_200` | `adapt_chapters` | 200 | 9900 分 |
| `managed_2m` | `managed_chars` | 2,000,000 | 19900 分 |

## 2. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/credit-packs` | 可售包列表（未登录可访问） |
| POST | `/v1/credit-packs/{code}/purchase` | 下单购买，`Idempotency-Key` 必填（或 body `idempotency_key`），返回 `pack / order / payment` |

购买请求：

```json
{"provider": "mock"}
```

- `provider` 默认 `mock`；生产环境 mock/fake 被 `get_provider` 拒绝（见 [legal-gates.md](legal-gates.md)）。
- 支付回调成功后 `subscription.activate_paid_order` 识别 `order.kind == "credit_pack"`，调用 `credits.grant_for_order`（以 `order_id` 幂等），有效期 `now + validity_days`。
- 审计动作：`credit_pack.purchase`。

## 3. 扣减优先级与预占

1. `QuotaService.reserve` 先算套餐剩余：`limit < 0`（无限）直接满足，否则 `max(limit - used - reserved, 0)`；
2. 套餐不足部分调用 `credits.reserve_pack`，按 `expires_at` 升序预占（先到期先扣）；
3. 两者都不足 → 回滚预占并返回 `402 credit_pack_insufficient`（并触发 `quota_insufficient` 通知）；
4. `commit` 只把套餐部分写入 `usage_aggregates`，额度包部分由 `credits.commit_pack` 结算；
5. `release` 同时释放套餐与额度包预占，任务取消/失败不会漏额度。

`GET /v1/entitlements` 额外返回：

```json
{
  "credits": [{"id": 1, "metric": "books_month", "remaining": 4, "expires_at": "..."}],
  "metrics": [{"metric": "books_month", "limit": 10, "used": 3, "reserved": 1,
               "pack_remaining": 4, "total_remaining": 10}]
}
```

## 4. 有效期与退款

- `scheduler.sweep_credits` 每轮：过期未用完的 grant 置 `expired`；临近到期（7 天）发 `credit_pack_expiring` 通知（按 grant 幂等）。
- 退款：`services/refunds.quote` 对 `credit_pack` 订单按**未使用比例**计算可退金额；`orders._recover_entitlements` 全额退款吊销 grant，部分退款按比例缩减 `quantity_granted`（`services/credits.revoke_for_refund`）。

## 5. 配置

```dotenv
CREDIT_PACK_VALIDITY_DAYS=365
REFUND_PRORATION_ENABLED=true
```

## 6. 测试

`tests/test_credits.py`（4 条）：

- 购买 → 回调 → grant 发放幂等；
- 套餐优先、包补足；
- 超额 `402 credit_pack_insufficient`；
- 过期与退款回收。

运行：

```powershell
python -m pytest tests/test_credits.py -q
```
