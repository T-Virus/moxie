# 墨写 · 运营管理后台（admin/）

独立的 Vue 3 + Vite + TypeScript 管理端。拥有自己的 `package.json`、构建配置与产物，开发端口固定 **5180**，不与桌面端 `web/` 冲突。

> 本目录只包含前端代码，未修改 `server/`、`src/`、`web/`、`data/`。服务端管理接口已补齐，用户、订阅、订单、退款、发票、对账、任务看板、告警、通知、审计页面均使用真实接口。

---

## 一、快速开始

要求 Node.js 18+。

```bash
cd admin
npm install
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
npm run dev               # http://localhost:5180
```

默认开发代理：

```
/v1      -> VITE_API_PROXY_TARGET（默认 http://127.0.0.1:8000）
/healthz -> 同上
/readyz  -> 同上
/metrics -> 同上
```

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | 空 | 浏览器请求的 API 根地址。留空表示同源（开发时由 Vite 代理转发）。生产跨域部署时填服务端完整地址。 |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | 仅开发 / `vite preview` 使用的代理目标。 |

生产构建：

```bash
npm run build       # 产物 admin/dist/
npm run preview     # http://localhost:5180，仍使用代理配置
```

### 跨域说明

服务端已启用 `CORSMiddleware`，默认允许 `http://127.0.0.1:5180` 与 `http://localhost:5180`。生产环境请通过 `CORS_ALLOW_ORIGINS` 增加管理端来源，或采用同域反向代理（推荐）：

1. 管理端与 API 同域，Nginx 把 `/v1`、`/healthz`、`/readyz`、`/metrics` 反代到服务端；
2. 跨域时把 `VITE_API_BASE` 指向服务端地址，并确保来源在白名单内。

---

## 二、目录结构

```
admin/
├── index.html
├── package.json
├── vite.config.ts          # 5180 端口 + /v1、/healthz、/readyz、/metrics 代理
├── tsconfig.json
├── tsconfig.node.json
├── .env.example
├── README.md
├── dist/                   # npm run build 产物
└── src/
    ├── main.ts             # 应用入口、会话丢失跳转
    ├── App.vue
    ├── router.ts           # hash 路由 + 登录/权限守卫
    ├── guard.ts            # 权限不足原因
    ├── api.ts              # fetch 封装、错误解析、接口探测、全部接口定义
    ├── auth.ts             # 登录、刷新、定时刷新、登出
    ├── session.ts          # sessionStorage 会话读写（不落 URL / 日志）
    ├── roles.ts            # admin/support 权限矩阵、菜单可见性
    ├── types.ts            # 接口数据类型
    ├── ui.ts               # 状态映射、时间/金额格式化
    ├── style.css           # 亮色主题（#0D9488 主色 / #7C3AED 辅助色）
    ├── components/
    │   ├── AppShell.vue    # 侧边栏 + 顶栏布局
    │   ├── Icon.vue
    │   ├── Modal.vue
    │   ├── Pager.vue
    │   ├── PageHeader.vue
    │   ├── StateBlock.vue  # 加载 / 空 / 错误 / 未就绪
    │   ├── NotReadyBanner.vue
    │   ├── StatusBadge.vue
    │   └── ToastStack.vue
    └── views/
        ├── Login.vue
        ├── Overview.vue
        ├── Users.vue
        ├── Subscriptions.vue
        ├── Orders.vue
        ├── Invoices.vue
        ├── Reconcile.vue
        ├── TaskBoard.vue
        ├── Alerts.vue
        ├── AuditLogs.vue
        └── Forbidden.vue
```

---

## 三、登录与会话

- 仅允许 `admin`、`support` 角色登录；其他角色即使密码正确也会被前端拒绝并提示「没有管理后台权限」。
- Token 仅存于 **sessionStorage**（关闭标签页即失效），不写入 URL、不打印到控制台、不进入任何导出内容。
- 访问 Token 到期前 60 秒自动刷新；收到 401 时自动尝试刷新并重放一次请求；刷新失败立即清空会话并跳转登录页。
- 路由守卫在进入页面前检查会话与权限；权限不足跳转 `/#/forbidden` 并显示缺少的具体权限。
- 退出登录会调用 `POST /v1/auth/logout`，即使服务端不可达也会清理本地会话。

### 权限矩阵

服务端只读接口使用 `require_staff`（admin / support），写接口使用 `require_admin`，且写操作全部写入审计日志。

| 能力 | admin | support |
| --- | --- | --- |
| 用户查看 / 详情 | ✓ | ✓ |
| 封禁 / 解封 | ✓ | — |
| 订阅调整 / 额度调整 | ✓ | — |
| 订单 / 退款查看 | ✓ | ✓ |
| 退款审批 / 直接退款 | ✓ | — |
| 发票查看 | ✓ | ✓ |
| 开具 / 作废 | ✓ | — |
| 对账查看 / CSV 导出 | ✓ | ✓（只读） |
| 生成对账 | ✓ | — |
| 任务看板查看 | ✓ | ✓ |
| 任务重试 | ✓ | — |
| 告警与通知查看 | ✓ | ✓（只读，重试按钮隐藏） |
| 审计日志查看 | ✓ | ✓ |

---

## 四、页面清单

| 页面 | 路由 | 功能 |
| --- | --- | --- |
| 登录 | `/login` | 邮箱/手机号 + 密码，角色校验，token 不进 URL |
| 概览 | `/overview` | 会话、角色能力、健康检查、管理接口探测 |
| 用户管理 | `/users` | 搜索、状态筛选、分页、详情聚合（账号/设备/订阅/任务/用量）、封禁/解封（原因必填） |
| 订阅与权益 | `/subscriptions` | 订阅列表、套餐/到期时间调整、额度手工调整、审计记录回显 |
| 订单与退款 | `/orders` | 全量订单、订单详情、退款审批（通过/拒绝+备注）、直接退款、状态跟踪 |
| 发票 | `/invoices` | 开票记录、开具、作废（原因必填） |
| 对账 | `/reconcile` | 按渠道+日期查询、差异分类、CSV 导出（admin 另有「生成对账」） |
| 任务看板 | `/tasks` | 队列深度、运行中/失败任务、重试；30 秒自动刷新 |
| 告警与通知 | `/alerts` | 异常用量告警、通知发送记录、失败/跳过重试（admin） |
| 审计日志 | `/audit` | 服务端过滤与分页：操作人、操作类型、对象类型/ID、时间范围 |
| 权限不足 | `/forbidden` | 明确所需权限与隐藏菜单说明 |

所有列表页包含加载态、空态、错误态；接口缺失时仍会显示「接口未就绪」，便于服务端回退排查。

---

## 五、接口约定

- 基础前缀：`/v1`；认证：`Authorization: Bearer <access_token>`。
- 错误结构沿用服务端现有约定：

```json
{ "error": { "code": "not_found", "message": "Not Found", "request_id": "..." } }
```

- **列表统一读取 `items`**：`{ items, total, page, page_size }`。旧字段（如 `refunds`、`invoices`）仅在 `items` 缺失时作为兜底，不再作为主要数据源。

### 管理接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/v1/auth/login` / `refresh` / `logout` | 登录、刷新、退出 |
| GET | `/v1/admin/users?q=&status=&page=&page_size=` | 用户列表 |
| GET | `/v1/admin/users/{id}` | 用户详情聚合 |
| POST | `/v1/admin/users/{id}/ban`、`.../unban` | 封禁 / 解封（`reason` 必填） |
| GET | `/v1/admin/subscriptions?q=&status=&page=&page_size=` | 订阅列表 |
| PATCH | `/v1/admin/subscriptions/{id}` | 调整套餐 / 到期时间（`note` 必填） |
| POST | `/v1/admin/accounts/{id}/quota-adjustments` | 额度调整（`quantity` 整数、`reason` 必填） |
| GET | `/v1/admin/accounts/{id}/quota-adjustments?page=&page_size=` | 额度调整记录 |
| GET | `/v1/admin/orders?q=&status=&provider=&page=&page_size=` | 全量订单 |
| GET | `/v1/admin/orders/{id}` | 订单详情 + 退款记录 |
| POST | `/v1/admin/orders/{id}/refund` | 直接退款 |
| GET | `/v1/admin/refunds?order_id=` | 退款列表（同时返回 `items` 与 `refunds` 别名） |
| POST | `/v1/admin/refunds/{id}/approve` | 退款通过（`note` 可选） |
| POST | `/v1/admin/refunds/{id}/reject` | 退款拒绝（`note` 必填） |
| GET | `/v1/admin/invoices?status=&page=&page_size=` | 开票记录 |
| POST | `/v1/admin/invoices/{id}` | 开具 `issued` / 作废 `voided` |
| GET | `/v1/admin/payments/reconcile?provider=&biz_date=` | 查询对账报告 |
| POST | `/v1/admin/payments/reconcile` | 生成对账 |
| GET | `/v1/admin/payments/reconcile/export?provider=&biz_date=` | CSV 导出（Bearer + Blob） |
| GET | `/v1/admin/tasks/dashboard` | 队列深度、运行中 / 失败任务 |
| POST | `/v1/admin/tasks/{id}/retry` | 任务重试 |
| GET | `/v1/admin/alerts?page=&page_size=` | 异常用量告警 |
| GET | `/v1/admin/notifications?status=&page=&page_size=` | 通知发送记录 |
| POST | `/v1/admin/notifications/{id}/retry` | 通知重试 |
| GET | `/v1/admin/audit-logs?page=&page_size=&actor_id=&action=&target_type=&target_id=&start_at=&end_at=` | 审计日志 |
| GET | `/v1/admin/renewal-reminders` / `/v1/plans` | 续费提醒、套餐候选 |

### 兼容与已知差异

1. **发票状态**：服务端统一为 `voided`；前端按 `voided` 展示与筛选，同时兼容历史 `rejected` 值（同样显示「已作废」，筛选「已作废」时一并包含）。
2. **退款列表**：服务端短期同时返回 `items` 与 `refunds` 别名；前端只读 `items`。
3. **通知状态**：服务端为 `queued / sent / failed / skipped`；仅 `failed`、`skipped` 显示重试入口。
4. **审计过滤**：`action`、`target_type`、`target_id` 为**精确匹配**；日期范围按浏览器本地日界转换后以 UTC 传给服务端。
5. **support 与对账**：对 support 开放只读能力，菜单可见，可查询报告与导出 CSV；「生成对账」按钮隐藏（服务端 `POST /v1/admin/payments/reconcile` 仍为 `require_admin`）。
6. **直接退款路径**：保留服务端既有 `POST /v1/admin/orders/{id}/refund`，审批流使用 `/v1/admin/refunds/{id}/approve|reject`。

---

## 六、构建与冒烟结果

- `npm run build`：通过（Vite 6，77 modules）。
- `npm run typecheck`：通过（`vue-tsc --noEmit`）。
- 本地冒烟：临时 SQLite 数据库 + 服务端 `8010`（`REDIS_ENABLED=false`、`MOCK_PAYMENT_SECRET` 临时值），未改动仓库内 `data/` 与 `server/novel_server.db`；临时 admin / support / 普通用户账号及订阅、订单、退款、发票、失败任务、告警、通知数据：
  - admin 登录后访问全部页面：用户列表 / 详情、订阅、订单与退款、发票、对账、任务看板、告警、审计均正常渲染，无「接口未就绪」占位；
  - 退款审批：`POST /v1/admin/refunds/1/approve` 返回 `succeeded`，订单变为已退款；订单页复核显示「已退款」；
  - 额度调整：`POST /v1/admin/accounts/3/quota-adjustments` 将 `books_month` 从 0 调到 2，生成审计记录 `quota.adjust`（对象 `account #3`）；订阅页与审计页均可复核；
  - 审计过滤：`action=quota.adjust` 精确查询返回上述记录；页面默认列表也可见；
  - support：告警 / 通知只读接口返回 200，重试与封禁接口返回 403；侧边栏可见「告警与通知」与「对账」；
  - support 对账：查询昨日微信报告返回 3 条差异与 summary；CSV 导出 200（184 bytes，表头 `type,external_order_no,order_id,amount_cents,channel_amount_cents,count`）；「生成对账」POST 返回 403；页面显示「只读模式」且无「生成对账」按钮；
  - 浏览器控制台无 error。
- 说明：浏览器自动化在较小视口下对弹窗底部按钮的点击受到限制，退款审批与额度调整最终通过同源 API 执行，并在 UI 中复核结果；页面渲染、权限与状态展示均已验证。
- 测试结束后停止临时服务并清理临时数据库与账号，仓库内无测试数据。

---

## 七、安全说明

- 前端不硬编码任何密钥、Token、支付凭据。
- Token 只存 sessionStorage，不进入 URL query / hash、不 `console.log`、不写入导出文件。
- CSV 导出通过带 `Authorization` 的 `fetch` 下载 Blob，避免「带 token 的下载链接」。
- 管理端不请求任何提示词接口，不展示提示词明文。
- 写操作（封禁、额度、退款、开具/作废、重试）均要求填写原因或备注，并依赖服务端写入审计日志。
