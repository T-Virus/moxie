# 电子发票渠道对接

服务端把开票抽象为 `InvoiceProvider`，业务层只处理状态机与审计，渠道差异封装在适配器里。
代码：`app/payments/invoice.py`、`app/services/invoicing.py`、`app/api/payments.py`。

## 1. 渠道与配置

| 渠道 | `INVOICE_PROVIDER` | 说明 |
| --- | --- | --- |
| 本地模拟 | `stub`（默认） | 纯内存即时开票；配置 `INVOICE_STUB_URL` 后改为调用本地 HTTP 模拟服务 |
| 诺诺开放平台形态 | `nuonuo` | 真实渠道适配位；凭据缺失时返回 `501 invoice_provider_not_configured` |

```dotenv
INVOICE_PROVIDER=stub
# 回调验签密钥（stub 与真实渠道共用）；缺失时回调返回 501
INVOICE_CALLBACK_SECRET=
# stub 可选：本地 HTTP 模拟服务地址，例如 http://127.0.0.1:9100
INVOICE_STUB_URL=
# 真实渠道凭据（缺任意一项 -> 501）
INVOICE_API_BASE=https://open.nuonuo.com
INVOICE_APP_KEY=
INVOICE_APP_SECRET=
INVOICE_SELLER_TAX_NO=
```

`nuonuo` 适配器按「appKey + timestamp + body」HMAC-SHA256 签名，调用
`/api/invoice/apply`、`/api/invoice/query`、`/api/invoice/void`；
字段按常见国内电子发票服务商形态映射（`orderNo`、`buyerName`、`buyerTaxNum`、
`invoiceAmount`、`invoiceNo`）。接入具体服务商时只需改这一个类，业务/接口不变。

## 2. 状态机

```
requested ──→ issuing ──→ issued ──→ voided
    │            └──→ failed ──→ issuing（重试）
    ├──→ voided（未提交渠道前可撤销）
    └──→ issued（管理端人工开票，兼容旧接口）
```

- 非法流转统一返回 `409 illegal_invoice_transition`。
- `issued_at` 在进入 `issued` 时写入。
- 渠道信息保存在 `invoice_requests.meta`：`provider`、`provider_invoice_id`、
  `invoice_url`、`failure_reason`、`callback_ids`。

## 3. 接口

### 客户端（Bearer）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/v1/orders/{order_id}/invoice` | 创建开票申请（`requested`） |
| GET | `/v1/invoices` | 我的发票列表 |
| GET | `/v1/invoices/{id}` | 发票详情 |
| POST | `/v1/invoices/{id}/apply` | 提交渠道开票（`requested/failed → issuing`） |
| POST | `/v1/invoices/{id}/void` | 作废；`issued` 会先调渠道作废 |

### 管理端

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/v1/admin/orders/{order_id}/invoice` | admin | 管理端代客创建申请（`requested`，幂等） |
| GET | `/v1/admin/invoices` | staff | 分页 `page/page_size`，`status=rejected` 映射 `voided` |
| GET | `/v1/admin/invoices/{id}` | staff | 详情 |
| POST | `/v1/admin/invoices/{id}/issue` | admin | 提交渠道开票，可传 `{"provider": "nuonuo"}` |
| POST | `/v1/admin/invoices/{id}/void` | admin | 作废，`reason` 必填（≥2 字符），否则 `422 invoice_void_reason_required` |
| POST | `/v1/admin/invoices/{id}` | admin | 旧版人工状态流转（保留兼容） |

列表同时返回 `items` 与 `invoices` 别名；`status` 为 `voided` 时附带
`legacy_status: "rejected"`。

### 渠道回调

`POST /v1/payments/invoices/callback`（无需登录）

```json
{
  "event_id": "evt-123",
  "invoice_id": 42,
  "status": "issued",
  "provider": "stub",
  "provider_invoice_id": "STUB-00000042",
  "message": "开票成功"
}
```

- 验签：请求头 `X-Invoice-Signature`（也接受 `X-Signature` / `sign`），值为
  `HMAC-SHA256(INVOICE_CALLBACK_SECRET, 原始请求体)` 的十六进制小写字符串。
  **必须对原始字节验签，不能先反序列化再重新序列化。**
- 验签失败：`403 invoice_callback_signature_invalid`。
- 幂等：`event_id` 写入 `meta.callback_ids`（保留最近 20 条）；重复回调返回
  `200 {"duplicate": true}`，不重复写状态/审计。
- 非法状态流转：`409 illegal_invoice_transition`。
- 其它错误：`404 invoice_not_found`、`422 invalid_callback_body`、
  `501 invoice_provider_not_configured`（缺回调密钥）。

## 4. 审计

所有写操作都会写 `audit_logs`：

| action | 触发 |
| --- | --- |
| `invoice.request` | 创建申请 |
| `invoice.apply` | 提交渠道（含 provider/status） |
| `invoice.void` | 作废（含 reason） |
| `invoice.callback` | 渠道回调（actor 为空，含 event_id/status） |

## 5. 测试

`tests/test_invoicing.py`（7 个）：

1. stub 全流程（申请→渠道开票→查询→作废→审计）；
2. 回调幂等 + 非法状态 409；
3. 回调验签失败 403；
4. 真实渠道缺凭据 501；
5. 状态机非法流转 409；
6. 客户端越权查询 404 / 本人作废成功；
7. 管理端代客创建开票申请与重复请求幂等。

运行：

```bash
cd server
python -m pytest -o addopts="" -q tests/test_invoicing.py
```

## 6. 仍缺条件

- `nuonuo` 适配器未用真实商户凭据联调，字段/签名需按目标服务商文档二次确认；
- 回调仅支持 JSON 体；若服务商使用 form-data 或 XML，需要在适配器里增加解析；
- 发票 PDF/邮件重发、红字发票等能力未实现。
